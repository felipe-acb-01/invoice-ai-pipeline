"""The hard bank: invoices built to make a model fail, plus the right answer for each.

    python -m invoice_pipeline.synth_hard          # writes samples_hard/ (deterministic)

What makes them hard:
  chile      Chilean electronic invoices: RUT, folio, Neto / IVA 19 %, "$ 1.234.567", dates in Spanish
  photo      phone photos (JPG): perspective, shadow, low light
  two_page   30-odd lines that run onto a second page, totals on page 2
  discount   negative discount lines, or two separate tax lines
  ambiguous  US dates like 03/04/2026 with no format label: only the address and "Net 30" settle them
  wrapped    descriptions wrapped over two lines, amount also written in words

Everything is invented. Each document says so in its footer. RUTs use the
99.9xx.xxx range and US tax IDs start with 00-.
"""

from __future__ import annotations

import argparse
import io
import json
import random
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from .schema import Invoice, LineItem
from .synth import CUSTOMER, FOOTER, VENDORS, Vendor, build_invoice, render_pdf

# ── Chile ──────────────────────────────────────────────────────────────────

CL_CUSTOMER = ("Estudio Contable Brightline SpA", "Asesorías contables", "Av. Providencia 1650, of. 1203, Providencia")
CL_FOOTER = "Documento ficticio generado para probar un sistema de facturas. No es una factura real."
MONTHS_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
             "octubre", "noviembre", "diciembre")


def rut(body: int) -> str:
    """Format a RUT with its real check digit (module 11)."""
    digits, factor, total = str(body), 2, 0
    for d in reversed(digits):
        total += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    check = 11 - total % 11
    dv = {11: "0", 10: "K"}.get(check, str(check))
    return f"{body:,}".replace(",", ".") + f"-{dv}"


CL_CUSTOMER_RUT = rut(99_912_330)


@dataclass(frozen=True)
class ClVendor:
    name: str
    giro: str
    address: str
    rut: str
    catalog: tuple[tuple[str, int, tuple[int, ...]], ...]
    terms: tuple[int | None, ...]  # days; None = contado


CL_VENDORS = (
    ClVendor("Limpiezas Cordillera Ltda.", "Servicios de aseo industrial", "Los Leones 1420, Providencia", rut(99_904_118),
             (("Servicio de aseo oficinas, mensual", 385_000, (1,)), ("Limpieza de vidrios", 95_000, (1, 2)),
              ("Insumos de baño", 28_900, (1, 2, 3))), (30, None)),
    ClVendor("Soporte TI Andino SpA", "Servicios informáticos", "Huérfanos 1055, of. 802, Santiago", rut(99_957_603),
             (("Soporte remoto (horas)", 32_000, (1, 2, 3, 5, 8)), ("Visita técnica", 45_000, (1, 2)),
              ("Respaldo en la nube, mensual", 59_990, (1,)), ("Configuración de notebook", 70_000, (1, 2, 3))), (30, 15)),
    ClVendor("Arriendos Oficina Plaza SpA", "Arriendo de oficinas amobladas", "Nueva Providencia 2155, Providencia",
             rut(99_921_874), (("Arriendo oficina 1203, mensual", 1_150_000, (1,)), ("Gastos comunes", 142_300, (1,)),
                               ("Estacionamiento", 85_000, (1, 2))), (None,)),
    ClVendor("Imprenta Del Pacífico Ltda.", "Imprenta y diseño", "San Diego 980, Santiago", rut(99_936_251),
             (("Talonarios de recibos", 18_500, (2, 4, 10)), ("Tarjetas de presentación (caja)", 12_900, (2, 3, 5)),
              ("Diseño de folleto", 120_000, (1,))), (30,)),
)


def build_cl(rng: random.Random, vendor: ClVendor, folio: int) -> Invoice:
    issued = date(2026, 8, 1) + timedelta(days=rng.randrange(0, 92))
    terms = rng.choice(vendor.terms)
    items = []
    for desc, price, quantities in rng.sample(vendor.catalog, k=rng.randint(1, len(vendor.catalog))):
        qty = rng.choice(quantities)
        items.append(LineItem(description=desc, quantity=qty, unit_price=price, amount=qty * price))
    neto = sum(li.amount for li in items)
    iva = round(neto * 0.19)
    return Invoice(invoice_number=str(folio), vendor_name=vendor.name, vendor_tax_id=vendor.rut,
                   customer_name=CL_CUSTOMER[0], issue_date=issued.isoformat(),
                   due_date=(issued + timedelta(days=terms)).isoformat() if terms else None,
                   currency="CLP", line_items=items, subtotal=neto, tax=iva, total=neto + iva)


def _clp(value: float) -> str:
    return "$ " + f"{int(round(value)):,}".replace(",", ".")


def render_cl(inv: Invoice, vendor: ClVendor, rng: random.Random) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    red = HexColor("#C0161B")
    issued = date.fromisoformat(inv.issue_date)

    c.setFont("Helvetica-Bold", 13)
    c.drawString(48, h - 60, vendor.name.upper())
    c.setFont("Helvetica", 9)
    c.drawString(48, h - 75, f"Giro: {vendor.giro}")
    c.drawString(48, h - 87, vendor.address)

    c.setStrokeColor(red)
    c.setLineWidth(2)
    c.rect(w - 230, h - 120, 182, 80, stroke=1, fill=0)
    c.setFillColor(red)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(w - 139, h - 58, f"R.U.T.: {vendor.rut}")
    if inv.exempt_amount and not inv.subtotal:  # all of it exempt: the SII's own document type
        c.setFont("Helvetica-Bold", 9.5)
        c.drawCentredString(w - 139, h - 72, "FACTURA NO AFECTA O")
        c.drawCentredString(w - 139, h - 83, "EXENTA ELECTRÓNICA")
        c.setFont("Helvetica-Bold", 11)
    else:
        c.drawCentredString(w - 139, h - 76, "FACTURA ELECTRÓNICA")
    c.drawCentredString(w - 139, h - 94, f"N° {inv.invoice_number}")
    c.setFont("Helvetica", 8)
    c.drawCentredString(w - 139, h - 134, "S.I.I. - SANTIAGO CENTRO")
    c.setFillColor(HexColor("#000000"))
    c.setStrokeColor(HexColor("#000000"))
    c.setLineWidth(0.6)

    y = h - 165
    c.setFont("Helvetica", 9.5)
    rows = (("Fecha Emisión", f"{issued.day} de {MONTHS_ES[issued.month - 1]} de {issued.year}"),
            ("Señor(es)", CL_CUSTOMER[0]), ("R.U.T.", CL_CUSTOMER_RUT), ("Giro", CL_CUSTOMER[1]),
            ("Dirección", CL_CUSTOMER[2]),
            ("Condición de pago", "Contado" if inv.due_date is None else f"{(date.fromisoformat(inv.due_date) - issued).days} días"))
    for i, (label, value) in enumerate(rows):
        c.drawString(48, y - i * 13, f"{label}")
        c.drawString(150, y - i * 13, f": {value}")
    if inv.due_date:
        c.drawString(360, y, f"Fecha Vencimiento: {date.fromisoformat(inv.due_date).strftime('%d-%m-%Y')}")

    y -= 105
    cols = ((48, "Código"), (100, "Descripción"), (390, "Cantidad"), (470, "Precio Unit."), (560, "Valor"))
    c.setFillColor(HexColor("#EEEEEE"))
    c.rect(40, y - 5, w - 80, 17, stroke=0, fill=1)
    c.setFillColor(HexColor("#000000"))
    c.setFont("Helvetica-Bold", 8.5)
    for x, label in cols:
        c.drawString(x, y, label) if x < 300 else c.drawRightString(x, y, label)
    c.setFont("Helvetica", 9)
    y -= 22
    for n, li in enumerate(inv.line_items, start=1):
        c.drawString(48, y, f"{rng.randint(100, 999)}")
        c.drawString(100, y, li.description)
        c.drawRightString(390, y, f"{li.quantity:g}")
        c.drawRightString(470, y, _clp(li.unit_price))
        c.drawRightString(560, y, _clp(li.amount))
        y -= 17

    y -= 16
    totals = [("MONTO NETO", inv.subtotal, False), ("I.V.A. 19%", inv.tax, False), ("TOTAL", inv.total, True)]
    if inv.exempt_amount:
        totals.insert(1, ("MONTO EXENTO", inv.exempt_amount, False))
        if not inv.subtotal:
            totals = [t for t in totals if t[0] not in ("MONTO NETO", "I.V.A. 19%")]
    if inv.other_taxes:
        totals.insert(-1, ("IMPTO. ADICIONAL ILA 20,5%", inv.other_taxes, False))
    for label, value, bold in totals:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 10.5 if bold else 9.5)
        c.drawRightString(470, y, label)
        c.drawRightString(560, y, _clp(value))
        y -= 16

    # A stand-in for the SII stamp: a grey block pattern, clearly not a real barcode.
    c.setFillColor(HexColor("#555555"))
    for i in range(70):
        if rng.random() < 0.55:
            c.rect(48 + i * 3, 120, 2, 38 + rng.randint(-6, 6), stroke=0, fill=1)
    c.setFillColor(HexColor("#000000"))
    c.setFont("Helvetica", 7.5)
    c.drawString(48, 108, "Timbre Electrónico SII · Res. 0 de 2026 · Verifique documento: www.sii.cl")
    c.setFillColor(HexColor("#777777"))
    c.setFont("Helvetica", 7)
    c.drawString(48, 40, CL_FOOTER)
    c.showPage()
    c.save()
    return buf.getvalue()


# ── Chilean taxes beyond IVA: the bank samples_cl ────────────────────────────

CL_EXTRA_VENDORS = (
    ClVendor("Capacitación Andes Ltda.", "Educación y capacitación", "Agustinas 1185, of. 501, Santiago", rut(99_948_327),
             (("Curso Excel avanzado (exento)", 180_000, (1, 2)),), (30,)),
    ClVendor("Eventos Quillay SpA", "Organización de eventos", "Av. Italia 1320, Ñuñoa", rut(99_965_102),
             (("Arriendo de salón", 450_000, (1,)), ("Coffee break (20 personas)", 90_000, (1,)),
              ("Charla de capacitación (exento)", 250_000, (1,))), (30,)),
    ClVendor("Distribuidora de Vinos Maule Ltda.", "Distribución de vinos", "San Pablo 3120, Quinta Normal",
             rut(99_972_446), (("Vino tinto reserva 750 ml", 4_990, (12, 24)), ("Vino blanco 750 ml", 3_990, (12,))),
             (30,)),
)
ILA_WINE = 0.205


def build_cl_tax(rng: random.Random, kind: str, folio: int) -> tuple[ClVendor, Invoice, list[str]]:
    """An exempt invoice, net + exempt, or wine with ILA; 'ila_bad_iva' is the trap: IVA taken over net + ILA."""
    vendor = CL_EXTRA_VENDORS[{"exenta": 0, "mixta": 1}.get(kind, 2)]
    issued = date(2026, 9, 1) + timedelta(days=rng.randrange(0, 60))
    items = [LineItem(description=d, quantity=q, unit_price=p, amount=q * p)
             for d, p, qs in vendor.catalog for q in (rng.choice(qs),)]
    exempt = sum(li.amount for li in items if "(exento)" in li.description)
    neto = sum(li.amount for li in items) - exempt
    iva = round(neto * 0.19)
    ila = round(neto * ILA_WINE) if vendor is CL_EXTRA_VENDORS[2] else 0
    flags = []
    if kind == "ila_bad_iva":
        iva, flags = round((neto + ila) * 0.19), ["iva_mismatch"]
    inv = Invoice(invoice_number=str(folio), vendor_name=vendor.name, vendor_tax_id=vendor.rut,
                  customer_name=CL_CUSTOMER[0], issue_date=issued.isoformat(),
                  due_date=(issued + timedelta(days=30)).isoformat(), currency="CLP", line_items=items,
                  subtotal=neto, tax=iva, exempt_amount=exempt, other_taxes=ila, total=neto + exempt + iva + ila)
    return vendor, inv, flags


def generate_cl_tax(out: Path, seed: int = 211) -> list[dict]:
    """samples_cl/: kept apart so the 104 documents of the other two banks never change."""
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for n, kind in enumerate(("exenta", "mixta", "ila", "ila_bad_iva"), start=1):
        vendor, inv, flags = build_cl_tax(rng, kind, 300 + n * 7)
        name = f"{n:03d}.pdf"
        (out / name).write_bytes(render_cl(inv, vendor, rng))
        manifest.append({"file": name, "received_order": n, "kind": "trap" if flags else "chile_tax",
                         "trap": "IVA taken over net + ILA" if flags else None, "scanned": False,
                         "base_currency": "CLP", "expected_flags": flags, "truth": inv.model_dump()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


# ── US layouts with hard features ──────────────────────────────────────────

ONES = ("", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen")
TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")


def _words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("-" + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" " + _words(n % 100) if n % 100 else "")
    return _words(n // 1000) + " thousand" + (" " + _words(n % 1000) if n % 1000 else "")


def in_words(amount: float) -> str:
    dollars, cents = int(amount), round((amount - int(amount)) * 100)
    return f"{_words(dollars).capitalize()} and {cents:02d}/100 US dollars"


@dataclass
class Look:
    date_label: str = "Date"
    date_fmt: str = "%B %-d, %Y"
    taxes: tuple[tuple[str, float], ...] = ()  # (label, amount)
    wrap: bool = False
    words: bool = False


def render_us(inv: Invoice, vendor: Vendor, look: Look) -> bytes:
    """Classic layout that paginates, wraps descriptions, prints several tax lines or the total in words."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    issued = date.fromisoformat(inv.issue_date)
    due = date.fromisoformat(inv.due_date) if inv.due_date else None
    money = lambda v: ("-$" if v < 0 else "$") + f"{abs(v):,.2f}"  # noqa: E731

    rows_per_page = 24
    pages = 1 + max(0, len(inv.line_items) - 1) // rows_per_page if not look.wrap else 1
    page = 1

    def header(first: bool) -> float:
        c.setFont("Helvetica-Bold", 15)
        c.drawString(48, h - 60, vendor.name)
        c.setFont("Helvetica", 9)
        c.drawString(48, h - 75, vendor.address[0])
        c.drawString(48, h - 87, vendor.address[1])
        c.drawString(48, h - 99, f"Tax ID: {vendor.tax_id}")
        c.setFont("Helvetica-Bold", 22)
        c.drawRightString(w - 48, h - 62, "Invoice")
        c.setFont("Helvetica", 10)
        number = inv.invoice_number
        c.drawRightString(w - 48, h - 82, f"Invoice {number}" if number.startswith("#") else f"Invoice # {number}")
        if pages > 1:
            c.drawRightString(w - 48, h - 124, f"Page {page} of {pages}")
        if not first:
            c.setFont("Helvetica-Oblique", 9)
            c.drawString(48, h - 130, "(continued)")
            return h - 160
        c.drawRightString(w - 48, h - 96, f"{look.date_label}: {issued.strftime(look.date_fmt)}")
        if due:
            terms = f"Net {(due - issued).days}"
            c.drawRightString(w - 48, h - 110, f"Due: {due.strftime(look.date_fmt)} ({terms})")
        else:
            c.drawRightString(w - 48, h - 110, "Due on receipt")
        c.rect(48, h - 190, 250, 62, stroke=1, fill=0)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(56, h - 142, "Bill to")
        c.setFont("Helvetica", 10)
        for i, line in enumerate(CUSTOMER):
            c.drawString(56, h - 156 - i * 12, line)
        return h - 225

    def table_head(y: float) -> float:
        c.setFont("Helvetica-Bold", 9)
        c.drawString(48, y, "Description")
        for x, label in ((380, "Qty"), (460, "Rate"), (550, "Amount")):
            c.drawRightString(x, y, label)
        c.line(40, y - 8, w - 40, y - 8)
        c.setFont("Helvetica", 9.5)
        return y - 24

    y = table_head(header(True))
    for n, li in enumerate(inv.line_items):
        if n and n % rows_per_page == 0 and not look.wrap:
            c.setFont("Helvetica", 7)
            c.setFillColor(HexColor("#777777"))
            c.drawString(48, 40, FOOTER)
            c.setFillColor(HexColor("#000000"))
            c.showPage()
            page += 1
            y = table_head(header(False))
        lines = simpleSplit(li.description, "Helvetica", 9.5, 250) if look.wrap else [li.description]
        for i, text in enumerate(lines):
            c.drawString(48, y - i * 12, text)
        c.drawRightString(380, y, f"{li.quantity:g}")
        c.drawRightString(460, y, money(li.unit_price))
        c.drawRightString(550, y, money(li.amount))
        y -= 12 * len(lines) + 8

    y -= 12
    totals = [("Subtotal", inv.subtotal, False)]
    totals += [(label, amount, False) for label, amount in look.taxes] or [("Tax", inv.tax, False)]
    totals += [("Total due", inv.total, True)]
    for label, value, bold in totals:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11 if bold else 10)
        c.drawRightString(460, y, label)
        c.drawRightString(550, y, money(value))
        y -= 17
    if look.words:
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(48, y - 8, f"Amount in words: {in_words(inv.total)}")

    c.setFont("Helvetica", 7)
    c.setFillColor(HexColor("#777777"))
    c.drawString(48, 40, FOOTER)
    c.showPage()
    c.save()
    return buf.getvalue()


# ── Phone photo ────────────────────────────────────────────────────────────


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(n):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def _perspective(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    """Coefficients PIL needs to map output pixels (dst) back to input pixels (src)."""
    a, b = [], []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b += [u, v]
    return _solve(a, b)


def photo(pdf_bytes: bytes, rng: random.Random) -> bytes:
    """A phone snapshot of the printed page: on a desk, tilted, unevenly lit. Returns JPEG bytes."""
    page = pdfium.PdfDocument(pdf_bytes)[0].render(scale=140 / 72).to_pil().convert("RGB")
    pw, ph = page.size
    W, H = int(pw * 1.18), int(ph * 1.12)
    j = lambda s: rng.uniform(-s, s)  # noqa: E731
    mx, my = (W - pw) / 2, (H - ph) / 2
    corners = [(mx + j(60), my + j(40)), (mx + pw + j(60), my + j(40)),
               (mx + pw + j(70), my + ph + j(30)), (mx + j(70), my + ph + j(30))]
    coeffs = _perspective([(0, 0), (pw, 0), (pw, ph), (0, ph)], corners)
    desk = Image.new("RGB", (W, H), (rng.randint(70, 110), rng.randint(55, 85), rng.randint(40, 60)))
    warped = page.transform((W, H), Image.Transform.PERSPECTIVE, coeffs, Image.Resampling.BICUBIC, fillcolor=None)
    mask = Image.new("L", page.size, 255).transform((W, H), Image.Transform.PERSPECTIVE, coeffs, fillcolor=0)
    desk.paste(warped, (0, 0), mask)
    # Uneven light: a shadow falling from one side.
    shade = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(shade)
    side = rng.choice((0, 1))
    for i in range(W):
        level = int(110 * (i / W if side else 1 - i / W) ** 2)
        draw.line([(i, 0), (i, H)], fill=level)
    desk = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), desk, shade.filter(ImageFilter.GaussianBlur(40)))
    desk = desk.filter(ImageFilter.GaussianBlur(rng.uniform(0.6, 1.1)))
    out = io.BytesIO()
    desk.resize((int(W * 0.7), int(H * 0.7))).save(out, "JPEG", quality=rng.randint(45, 65))
    return out.getvalue()


# ── Documents that are not invoices ────────────────────────────────────────


def _page(draw) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    draw(c, *letter)
    c.setFont("Helvetica", 7)
    c.setFillColor(HexColor("#777777"))
    c.drawString(48, 40, FOOTER)
    c.showPage()
    c.save()
    return buf.getvalue()


def quote_pdf() -> bytes:
    def draw(c, w, h):
        c.setFont("Helvetica-Bold", 15); c.drawString(48, h - 60, "Quillwork Design Studio")
        c.setFont("Helvetica-Bold", 22); c.drawRightString(w - 48, h - 62, "Quotation")
        c.setFont("Helvetica", 10)
        c.drawRightString(w - 48, h - 82, "Quote # Q-2026-118")
        c.drawRightString(w - 48, h - 96, "Valid until: December 15, 2026")
        c.drawString(48, h - 140, "Prepared for: Brightline Accounting LLC")
        y = h - 190
        for desc, amount in (("Annual report design (estimate)", 2400.0), ("Infographics, up to 6", 900.0)):
            c.drawString(48, y, desc); c.drawRightString(w - 60, y, f"${amount:,.2f}"); y -= 20
        c.setFont("Helvetica-Bold", 11); c.drawRightString(w - 60, y - 10, "Estimated total  $3,300.00")
        c.setFont("Helvetica", 9)
        c.drawString(48, y - 50, "This is a quotation, not a request for payment. An invoice will follow once the work is approved.")
    return _page(draw)


def receipt_pdf() -> bytes:
    def draw(c, w, h):
        c.setFont("Helvetica-Bold", 15); c.drawString(48, h - 60, "Atlas Telecom")
        c.setFont("Helvetica-Bold", 22); c.drawRightString(w - 48, h - 62, "Payment receipt")
        c.setFont("Helvetica", 10)
        c.drawString(48, h - 120, "Thank you! We received your payment.")
        c.drawString(48, h - 140, "Paid on: October 3, 2026   ·   Card ending 4242   ·   Reference AT-PAY-77310")
        c.drawString(48, h - 160, "Applied to invoice AT-2026-00881")
        c.setFont("Helvetica-Bold", 12); c.drawString(48, h - 195, "Amount paid: $219.00")
        c.setFont("Helvetica", 10); c.drawString(48, h - 215, "Balance due: $0.00")
    return _page(draw)


def contract_pdf() -> bytes:
    def draw(c, w, h):
        c.setFont("Helvetica-Bold", 16); c.drawCentredString(w / 2, h - 70, "SERVICE AGREEMENT")
        c.setFont("Helvetica", 10)
        text = ("This Service Agreement is entered into between Brightline Accounting LLC (the Client) and Cedar IT "
                "Support (the Provider). 1. Services. The Provider will deliver remote and on-site IT support as "
                "described in Schedule A. 2. Fees. Support hours are billed at $85.00 per hour, invoiced monthly, "
                "payable within 30 days of each invoice. 3. Term. This agreement starts on September 1, 2026 and "
                "renews every twelve months unless either party gives 60 days written notice. 4. Confidentiality. "
                "Each party will keep the other's information confidential.")
        y = h - 110
        for line in simpleSplit(text, "Helvetica", 10, w - 96):
            c.drawString(48, y, line); y -= 15
        c.drawString(48, y - 40, "Signed: ____________________          ____________________")
    return _page(draw)


def snapshot_jpg(rng: random.Random) -> bytes:
    """A phone photo of a whiteboard after a meeting: an image with text that is not a document."""
    img = Image.new("RGB", (1200, 900), (rng.randint(225, 240),) * 3)
    d = ImageDraw.Draw(img)
    for i in range(40):
        x, y = rng.randrange(1200), rng.randrange(900)
        d.ellipse([x, y, x + rng.randint(20, 120), y + rng.randint(20, 120)],
                  outline=(rng.randrange(255), rng.randrange(120), rng.randrange(255)), width=3)
    for i, text in enumerate(("Q4 planning", "- close books by Dec 12", "- new AP tool?", "- team lunch Friday")):
        d.text((120, 160 + i * 90), text, fill=(30, 60, 160))
    img = img.resize((1600, 1200)).filter(ImageFilter.GaussianBlur(1.2))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=55)
    return out.getvalue()


NOT_INVOICE = Invoice(is_invoice=False, invoice_number="", vendor_name="", vendor_tax_id=None, customer_name="",
                      issue_date="", due_date=None, currency="", line_items=[], subtotal=0, tax=0, total=0)


# ── The bank ───────────────────────────────────────────────────────────────

LONG_DESCRIPTIONS = (
    ("Quarterly review of accounts payable workflow, including vendor master cleanup and approval matrix update", 1450.0),
    ("On-site network assessment for the second floor, with cable certification report and remediation plan", 980.0),
    ("Migration of shared drive folders to the new document management system, with permission mapping", 1720.0),
    ("Emergency after-hours call-out to restore the main printer and scanner queue for month-end close", 340.0),
)


def generate(out: Path, seed: int = 197) -> list[dict]:
    rng = random.Random(seed)
    counters = {v.name: rng.randint(200, 900) for v in (*VENDORS, *CL_VENDORS)}
    docs: list[dict] = []

    def us_invoice(vendor: Vendor) -> Invoice:
        counters[vendor.name] += rng.randint(1, 6)
        return build_invoice(rng, vendor, counters[vendor.name])

    def cl_invoice(vendor: ClVendor) -> Invoice:
        counters[vendor.name] += rng.randint(1, 9)
        return build_cl(rng, vendor, counters[vendor.name])

    # Chilean invoices
    for _ in range(9):
        v = rng.choice(CL_VENDORS)
        docs.append(dict(kind="chile", vendor=v, invoice=cl_invoice(v), base="CLP"))
    # Phone photos: three Chilean, five US
    for i in range(8):
        if i < 3:
            v = rng.choice(CL_VENDORS)
            docs.append(dict(kind="photo", vendor=v, invoice=cl_invoice(v), base="CLP", photo=True))
        else:
            v = rng.choice(VENDORS)
            docs.append(dict(kind="photo", vendor=v, invoice=us_invoice(v), photo=True))
    # Two pages: itemized support hours
    support = VENDORS[1]
    for _ in range(5):
        inv = us_invoice(support)
        start = date.fromisoformat(inv.issue_date) - timedelta(days=40)
        lines = []
        for d in sorted(rng.sample(range(40), k=rng.randint(26, 34))):
            qty = rng.choice((0.5, 1, 1.5, 2, 2.5))
            day = start + timedelta(days=d)
            lines.append(LineItem(description=f"Remote support, {day.strftime('%b')} {day.day}", quantity=qty,
                                  unit_price=85.0, amount=round(qty * 85.0, 2)))
        sub = round(sum(li.amount for li in lines), 2)
        inv = inv.model_copy(update=dict(line_items=lines, subtotal=sub, tax=0.0, total=sub))
        docs.append(dict(kind="two_page", vendor=support, invoice=inv, look=Look()))
    # Discounts and split taxes
    for i in range(5):
        v = rng.choice(VENDORS)
        inv = us_invoice(v)
        lines = list(inv.line_items)
        if i < 3:
            gross = sum(li.amount for li in lines)
            disc = -round(gross * rng.choice((0.05, 0.1, 0.15)), 2)
            lines.append(LineItem(description=f"Discount ({round(-disc / gross * 100):g}%)", quantity=1,
                                  unit_price=disc, amount=disc))
            sub = round(sum(li.amount for li in lines), 2)
            tax = round(sub * v.tax_rate, 2)
            look = Look(taxes=((f"Sales tax {v.tax_rate * 100:g}%", tax),) if tax else ())
        else:
            sub = round(sum(li.amount for li in lines), 2)
            state, county = round(sub * 0.04, 2), round(sub * 0.015, 2)
            tax = round(state + county, 2)
            look = Look(taxes=(("State tax 4%", state), ("County tax 1.5%", county)))
        inv = inv.model_copy(update=dict(line_items=lines, subtotal=sub, tax=tax, total=round(sub + tax, 2)))
        docs.append(dict(kind="discount", vendor=v, invoice=inv, look=look))
    # Ambiguous dates: day and month both ≤ 12, US vendor, no format label
    for _ in range(4):
        v = rng.choice([x for x in VENDORS if 30 in x.net_days])
        inv = us_invoice(v)
        issued = date(2026, rng.randint(8, 10), rng.randint(1, 12))
        inv = inv.model_copy(update=dict(issue_date=issued.isoformat(), due_date=(issued + timedelta(days=30)).isoformat()))
        docs.append(dict(kind="ambiguous", vendor=v, invoice=inv, look=Look(date_label="Date", date_fmt="%m/%d/%Y")))
    # Wrapped descriptions and amount in words
    for _ in range(5):
        v = VENDORS[3]
        inv = us_invoice(v)
        lines = [LineItem(description=d, quantity=1, unit_price=p, amount=p)
                 for d, p in rng.sample(LONG_DESCRIPTIONS, k=rng.randint(2, 3))]
        sub = round(sum(li.amount for li in lines), 2)
        inv = inv.model_copy(update=dict(line_items=lines, subtotal=sub, tax=0.0, total=sub))
        docs.append(dict(kind="wrapped", vendor=v, invoice=inv, look=Look(wrap=True, words=True)))

    for d in docs:
        d.setdefault("flags", [])
    rng.shuffle(docs)

    # Traps
    i = next(n for n, d in enumerate(docs) if d["kind"] == "chile" and n >= 3)
    insert_at = rng.randint(i + 1, len(docs))
    docs.insert(insert_at, dict(kind="trap", trap="Chilean invoice photographed again", vendor=docs[i]["vendor"],
                                invoice=docs[i]["invoice"].model_copy(deep=True), base="CLP", photo=True,
                                flags=["duplicate"]))
    v = rng.choice(CL_VENDORS)
    bad = cl_invoice(v)
    bad = bad.model_copy(update=dict(tax=bad.tax + 1000, total=bad.total + 1000))
    docs.insert(rng.randrange(len(docs)), dict(kind="trap", trap="IVA off by $1.000", vendor=v, invoice=bad,
                                               base="CLP", flags=["iva_mismatch"]))
    tp = next(d for d in docs if d["kind"] == "two_page")
    bad = tp["invoice"].model_copy(deep=True)
    counters[support.name] += 1
    bad.invoice_number = support.number_format.format(year=2026, n=counters[support.name])
    bad.subtotal = round(bad.subtotal - bad.line_items[-1].amount, 2)  # forgot the last line, on page 2
    bad.total = bad.subtotal
    docs.insert(rng.randrange(len(docs)), dict(kind="trap", trap="subtotal skips the last line on page 2",
                                               vendor=support, invoice=bad, look=Look(),
                                               flags=["subtotal_mismatch"]))
    i = next(n for n, d in enumerate(docs) if d["kind"] == "chile" and d["invoice"].due_date)
    twin = docs[i]["invoice"].model_copy(deep=True)
    counters[docs[i]["vendor"].name] += 1
    twin.invoice_number = str(counters[docs[i]["vendor"].name])
    docs.insert(rng.randint(i + 1, len(docs)), dict(kind="trap", trap="same Chilean charge, new folio",
                                                    vendor=docs[i]["vendor"], invoice=twin, base="CLP",
                                                    flags=["possible_duplicate"]))

    # Documents that arrive in an invoice inbox but are not invoices
    for name, make in (("quote", quote_pdf), ("receipt", receipt_pdf), ("contract", contract_pdf),
                       ("snapshot", lambda: snapshot_jpg(rng))):
        docs.insert(rng.randrange(len(docs)), dict(kind="not_invoice", trap=name, invoice=NOT_INVOICE, raw=make(),
                                                   raw_ext=".jpg" if name == "snapshot" else ".pdf", flags=[]))

    out.mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("*.pdf"), *out.glob("*.jpg")]:
        old.unlink()
    manifest = []
    for n, d in enumerate(docs, start=1):
        inv, vendor = d["invoice"], d.get("vendor")
        if "raw" in d:
            name = f"{n:03d}{d['raw_ext']}"
            (out / name).write_bytes(d["raw"])
            manifest.append({"file": name, "received_order": n, "kind": d["kind"], "trap": d["trap"],
                             "scanned": False, "base_currency": "USD", "expected_flags": [], "truth": inv.model_dump()})
            continue
        if isinstance(vendor, ClVendor):
            pdf = render_cl(inv, vendor, rng)
        elif "look" in d:
            pdf = render_us(inv, vendor, d["look"])
        else:
            pdf = render_pdf(inv, replace(vendor, layout=rng.choice(("classic", "band"))))
        name = f"{n:03d}.pdf"
        if d.get("photo"):
            name = f"{n:03d}.jpg"
            (out / name).write_bytes(photo(pdf, rng))
        else:
            (out / name).write_bytes(pdf)
        manifest.append({"file": name, "received_order": n, "kind": d["kind"], "trap": d.get("trap"),
                         "scanned": bool(d.get("photo")), "base_currency": d.get("base", "USD"),
                         "expected_flags": d["flags"], "truth": inv.model_dump()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("samples_hard"))
    parser.add_argument("--seed", type=int, default=197)
    parser.add_argument("--cl-tax", action="store_true", help="write the Chilean-tax bank (samples_cl/) instead")
    args = parser.parse_args()
    manifest = generate_cl_tax(Path("samples_cl")) if args.cl_tax else generate(args.out, args.seed)
    from collections import Counter
    print(f"{len(manifest)} documents in {'samples_cl' if args.cl_tax else args.out}/:", dict(Counter(d["kind"] for d in manifest)))


if __name__ == "__main__":
    main()
