"""Generate the synthetic test bank: invoices as PDFs, plus the right answer for each.

Every vendor, customer and number here is invented. Each PDF carries a footer
saying it is a synthetic sample. Tax IDs start with 00-, which no real EIN uses.

    python -m invoice_pipeline.synth            # writes samples/ (deterministic)
    python -m invoice_pipeline.synth --out dir --seed 7
"""

from __future__ import annotations

import argparse
import io
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageFilter
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from .schema import Invoice, LineItem

CUSTOMER = ("Brightline Accounting LLC", "1180 Harbor Street, Suite 400", "Portland, OR 97209")
FOOTER = "Synthetic sample generated to test an invoice pipeline. Not a real invoice."


@dataclass(frozen=True)
class Vendor:
    name: str
    address: tuple[str, str]
    tax_id: str
    currency: str
    tax_rate: float
    number_format: str  # e.g. "INV-{year}-{n:04d}"
    layout: str  # classic | band | plain
    catalog: tuple[tuple[str, float, tuple[float, ...]], ...]  # (description, unit price, plausible quantities)
    net_days: tuple[int | None, ...]  # None = due on receipt


VENDORS = (
    Vendor("Northwind Cleaning Co.", ("88 Alder Way", "Portland, OR 97201"), "00-4821937", "USD", 0.0,
           "INV-{year}-{n:04d}", "classic",
           (("Office cleaning, weekly", 420.0, (1,)), ("Window cleaning", 180.0, (1, 1, 2, 3)),
            ("Carpet deep clean", 95.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5)), ("Restroom supplies restock", 64.5, (1, 1, 2, 3))), (30, 30, 15)),
    Vendor("Cedar IT Support", ("2210 Pine Ave", "Beaverton, OR 97005"), "00-7310442", "USD", 0.0,
           "#{n}", "band",
           (("Remote support", 85.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5)), ("On-site visit", 125.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5)), ("Laptop setup", 140.0, (1, 1, 2, 3)),
            ("Managed backup, monthly", 210.0, (1,)), ("Firewall review", 95.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5))), (15, 30, None)),
    Vendor("Blue Ladder Coworking", ("501 Market St", "Portland, OR 97204"), "00-2295018", "USD", 0.0,
           "BL-{n:05d}", "classic",
           (("Dedicated desk, monthly", 390.0, (1,)), ("Meeting room", 45.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5)),
            ("Mail handling, monthly", 35.0, (1,))), (None, 15)),
    Vendor("Harbor Legal Partners", ("1 Commerce Plaza, Floor 9", "Seattle, WA 98101"), "00-6650371", "USD", 0.0,
           "HLP/{year}/{n:03d}", "plain",
           (("Contract review", 310.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5)), ("Corporate filing", 450.0, (1,)),
            ("Consultation", 275.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5))), (30,)),
    Vendor("Quillwork Design Studio", ("74 Fremont St", "Portland, OR 97212"), "00-9182736", "USD", 0.0825,
           "QW-{year}{n:03d}", "band",
           (("Brochure design", 650.0, (1,)), ("Logo refresh", 900.0, (1,)),
            ("Design hours", 70.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5)), ("Print-ready files", 120.0, (1, 1, 2, 3))), (30, 15)),
    Vendor("Summit Payroll Services", ("3300 Lake Dr", "Lake Oswego, OR 97034"), "00-3374901", "USD", 0.0,
           "SPS-{n:06d}", "classic",
           (("Payroll processing per employee", 12.5, (8, 12, 14, 19, 23)), ("Quarterly tax filing", 180.0, (1,)),
            ("Year-end W-2 preparation", 6.0, (8, 12, 14, 19, 23))), (None, 15)),
    Vendor("Greenleaf Facilities", ("19 Industrial Rd", "Tigard, OR 97223"), "00-5508613", "USD", 0.075,
           "GF{year}-{n:04d}", "plain",
           (("HVAC maintenance visit", 240.0, (1, 1, 2, 3)), ("Filter replacement", 38.0, (1, 1, 2, 3)),
            ("Technician hours", 92.0, (0.5, 1, 1.5, 2, 2.5, 3, 4, 6.5))), (30, 30)),
    Vendor("Atlas Telecom", ("900 Broadway", "Vancouver, WA 98660"), "00-1147285", "USD", 0.0,
           "AT-{year}-{n:05d}", "band",
           (("Business internet, monthly", 189.0, (1,)), ("Phone line", 32.0, (1, 1, 2, 3)),
            ("Static IP", 15.0, (1, 1, 2, 3))), (15,)),
)

# The foreign-currency trap: a European vendor, decimal commas, DD/MM dates.
EUR_VENDOR = Vendor("Lumen Translation Services Lda.", ("Rua das Flores 112", "1200-195 Lisboa, Portugal"),
                    "PT 000123456", "EUR", 0.23, "LT-{year}-{n:03d}", "plain",
                    (("Translation, per 1,000 words", 95.0, (4, 7, 12, 18)), ("Certified copy", 40.0, (1, 1, 2, 3))), (30,))


def _money(value: float, currency: str, style: str) -> str:
    if currency == "EUR":
        whole = f"{value:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
        return f"{whole} €"
    if style == "classic":
        return f"${value:,.2f}"
    if style == "band":
        return f"USD {value:,.2f}"
    return f"{value:.2f}"


def _date(value: date, style: str) -> str:
    if style == "classic":
        return value.strftime("%B %-d, %Y")
    if style == "band":
        return value.strftime("%d %b %Y")
    return value.strftime("%d/%m/%Y")


def _qty(value: float) -> str:
    return f"{value:g}"


# ── Building the right answer ──────────────────────────────────────────────


def build_invoice(rng: random.Random, vendor: Vendor, counter: int) -> Invoice:
    issued = date(2026, 8, 1) + timedelta(days=rng.randrange(0, 92))
    net = rng.choice(vendor.net_days)
    items = []
    for desc, price, quantities in rng.sample(vendor.catalog, k=rng.randint(1, len(vendor.catalog))):
        qty = float(rng.choice(quantities))
        items.append(LineItem(description=desc, quantity=qty, unit_price=price, amount=round(qty * price, 2)))
    subtotal = round(sum(li.amount for li in items), 2)
    tax = round(subtotal * vendor.tax_rate, 2)
    return Invoice(
        invoice_number=vendor.number_format.format(year=issued.year, n=counter),
        vendor_name=vendor.name,
        vendor_tax_id=vendor.tax_id,
        customer_name=CUSTOMER[0],
        issue_date=issued.isoformat(),
        due_date=(issued + timedelta(days=net)).isoformat() if net else None,
        currency=vendor.currency,
        line_items=items,
        subtotal=subtotal,
        tax=tax,
        total=round(subtotal + tax, 2),
    )


# ── Drawing ────────────────────────────────────────────────────────────────


def render_pdf(inv: Invoice, vendor: Vendor) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"Invoice {inv.invoice_number}")
    w, h = letter
    style = vendor.layout
    cur = inv.currency
    issued = date.fromisoformat(inv.issue_date)
    due = date.fromisoformat(inv.due_date) if inv.due_date else None
    body = "Courier" if style == "plain" else "Helvetica"
    bold = "Courier-Bold" if style == "plain" else "Helvetica-Bold"

    if style == "band":
        c.setFillColor(HexColor("#1F3A5F"))
        c.rect(0, h - 110, w, 110, stroke=0, fill=1)
        c.setFillColor(HexColor("#FFFFFF"))
        c.setFont(bold, 20)
        c.drawString(48, h - 58, vendor.name)
        c.setFont(body, 9)
        c.drawString(48, h - 76, f"{vendor.address[0]} · {vendor.address[1]} · EIN {vendor.tax_id}")
        c.setFont(bold, 26)
        c.drawRightString(w - 48, h - 62, "INVOICE")
        c.setFillColor(HexColor("#000000"))
        y = h - 150
        c.setFont(bold, 9)
        for i, (label, value) in enumerate((("INVOICE NO.", inv.invoice_number), ("DATE", _date(issued, style)),
                                            ("DUE", _date(due, style) if due else "Upon receipt"))):
            c.drawString(320 + i * 90, y, label)
        c.setFont(body, 10)
        for i, value in enumerate((inv.invoice_number, _date(issued, style), _date(due, style) if due else "Upon receipt")):
            c.drawString(320 + i * 90, y - 14, value)
        c.setFont(bold, 9)
        c.drawString(48, y, "BILLED TO")
        c.setFont(body, 10)
        for i, line in enumerate(CUSTOMER):
            c.drawString(48, y - 14 - i * 13, line)
        y -= 80
    elif style == "classic":
        c.setFont(bold, 15)
        c.drawString(48, h - 60, vendor.name)
        c.setFont(body, 9)
        c.drawString(48, h - 75, vendor.address[0])
        c.drawString(48, h - 87, vendor.address[1])
        c.drawString(48, h - 99, f"Tax ID: {vendor.tax_id}")
        c.setFont(bold, 22)
        c.drawRightString(w - 48, h - 62, "Invoice")
        c.setFont(body, 10)
        c.drawRightString(w - 48, h - 82, f"Invoice # {inv.invoice_number}")
        c.drawRightString(w - 48, h - 96, f"Date: {_date(issued, style)}")
        c.drawRightString(w - 48, h - 110, f"Due date: {_date(due, style)}" if due else "Due on receipt")
        c.rect(48, h - 190, 250, 62, stroke=1, fill=0)
        c.setFont(bold, 9)
        c.drawString(56, h - 142, "Bill to")
        c.setFont(body, 10)
        for i, line in enumerate(CUSTOMER):
            c.drawString(56, h - 156 - i * 12, line)
        y = h - 225
    else:  # plain
        c.setFont(bold, 12)
        c.drawString(48, h - 60, vendor.name.upper())
        c.setFont(body, 9)
        c.drawString(48, h - 74, f"{vendor.address[0]}, {vendor.address[1]}")
        c.drawString(48, h - 86, f"{'VAT' if cur == 'EUR' else 'EIN'}: {vendor.tax_id}")
        c.setFont(body, 10)
        rows = (("INVOICE", inv.invoice_number), ("Date (DD/MM/YYYY)", _date(issued, style)),
                ("Payment due", _date(due, style) if due else "on receipt"), ("Customer", CUSTOMER[0]),
                ("Currency", cur))
        for i, (label, value) in enumerate(rows):
            c.drawString(48, h - 120 - i * 14, f"{label:<20}{value}")
        y = h - 205

    # Line table
    cols = (48, 330, 400, 480) if style != "plain" else (48, 320, 390, 470)
    c.setFont(bold, 9)
    if style == "band":
        c.setFillColor(HexColor("#E8EEF5"))
        c.rect(40, y - 5, w - 80, 18, stroke=0, fill=1)
        c.setFillColor(HexColor("#000000"))
    headers = ("Description", "Hours/Qty" if style != "classic" else "Qty", "Rate", "Amount")
    for x, text in zip(cols, headers):
        c.drawString(x, y, text) if x == cols[0] else c.drawRightString(x + 50, y, text)
    c.setLineWidth(0.6)
    c.line(40, y - 8, w - 40, y - 8)
    c.setFont(body, 10)
    y -= 26
    for li in inv.line_items:
        c.drawString(cols[0], y, li.description)
        c.drawRightString(cols[1] + 50, y, _qty(li.quantity))
        c.drawRightString(cols[2] + 50, y, _money(li.unit_price, cur, style))
        c.drawRightString(cols[3] + 50, y, _money(li.amount, cur, style))
        if style == "classic":
            c.setStrokeColor(HexColor("#BBBBBB"))
            c.line(40, y - 6, w - 40, y - 6)
            c.setStrokeColor(HexColor("#000000"))
        y -= 22

    # Totals
    y -= 10
    tax_label = f"VAT {vendor.tax_rate:.0%}" if cur == "EUR" else (f"Sales tax {vendor.tax_rate * 100:g}%" if vendor.tax_rate else "Tax")
    for label, value, is_total in (("Subtotal", inv.subtotal, False), (tax_label, inv.tax, False),
                                   ("Total due" if style != "plain" else "TOTAL", inv.total, True)):
        c.setFont(bold if is_total else body, 11 if is_total else 10)
        c.drawRightString(cols[2] + 50, y, label)
        c.drawRightString(cols[3] + 50, y, _money(value, cur, style))
        y -= 18

    c.setFont(body, 9)
    c.drawString(48, 90, "Payment by bank transfer. Please include the invoice number as reference.")
    c.setFont(body, 7)
    c.setFillColor(HexColor("#777777"))
    c.drawString(48, 40, FOOTER)
    c.showPage()
    c.save()
    return buf.getvalue()


def scan(pdf_bytes: bytes, rng: random.Random) -> bytes:
    """Make a text PDF look photocopied: a skewed, noisy, compressed image with no text layer."""
    page = pdfium.PdfDocument(pdf_bytes)[0]
    img = page.render(scale=110 / 72).to_pil().convert("L")
    img = img.rotate(rng.uniform(-2.2, 2.2), expand=True, fillcolor=255)
    noise = Image.effect_noise(img.size, rng.uniform(40, 60))
    img = Image.blend(img.point(lambda v: 30 + v * 0.8), noise, 0.16).filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.8)))
    jpg = io.BytesIO()
    img.save(jpg, "JPEG", quality=rng.randint(25, 40))
    out = io.BytesIO()
    Image.open(jpg).save(out, "PDF", resolution=110)
    return out.getvalue()


# ── The bank ───────────────────────────────────────────────────────────────


def generate(out: Path, seed: int = 196, clean: int = 40, scanned: int = 15) -> list[dict]:
    rng = random.Random(seed)
    counters = {v.name: rng.randint(100, 900) for v in (*VENDORS, EUR_VENDOR)}

    def next_invoice(vendor: Vendor) -> Invoice:
        counters[vendor.name] += rng.randint(1, 7)
        return build_invoice(rng, vendor, counters[vendor.name])

    docs: list[dict] = []
    for i in range(clean + scanned):
        vendor = rng.choice(VENDORS)
        docs.append({"kind": "scanned" if i >= clean else "clean", "vendor": vendor,
                     "invoice": next_invoice(vendor), "flags": []})
    rng.shuffle(docs)

    def insert_after(original_index: int, doc: dict) -> None:
        docs.insert(rng.randint(original_index + 1, len(docs)), doc)

    # Trap 1: the same invoice sent twice (the second time, as a scan).
    i = rng.randrange(5, 20)
    insert_after(i, {"kind": "trap", "trap": "re-sent as a scan", "vendor": docs[i]["vendor"],
                     "invoice": docs[i]["invoice"].model_copy(deep=True), "flags": ["duplicate"], "scan": True})
    # Trap 2: same vendor, date and total, new number.
    i = rng.randrange(5, 25)
    while docs[i]["kind"] == "trap":
        i += 1
    twin =docs[i]["invoice"].model_copy(deep=True)
    counters[docs[i]["vendor"].name] += 1
    twin.invoice_number = docs[i]["vendor"].number_format.format(year=2026, n=counters[docs[i]["vendor"].name])
    insert_after(i, {"kind": "trap", "trap": "same charge, new number", "vendor": docs[i]["vendor"],
                     "invoice": twin, "flags": ["possible_duplicate"]})
    # Trap 3: the printed total is off by 100.
    vendor = VENDORS[0]
    bad = next_invoice(vendor)
    bad.total = round(bad.total + 100, 2)
    docs.insert(rng.randrange(len(docs)), {"kind": "trap", "trap": "total off by 100", "vendor": vendor,
                                           "invoice": bad, "flags": ["total_mismatch"]})
    # Trap 4: one line's amount does not match quantity × rate.
    vendor = VENDORS[1]
    bad = next_invoice(vendor)
    while len(bad.line_items) < 2:
        bad = next_invoice(vendor)
    bad.line_items[0].amount = round(bad.line_items[0].amount + 40, 2)
    bad.subtotal = round(sum(li.amount for li in bad.line_items), 2)
    bad.tax = round(bad.subtotal * vendor.tax_rate, 2)
    bad.total = round(bad.subtotal + bad.tax, 2)
    docs.insert(rng.randrange(len(docs)), {"kind": "trap", "trap": "line amount wrong", "vendor": vendor,
                                           "invoice": bad, "flags": ["line_math"]})
    # Trap 5: billed in euros.
    docs.insert(rng.randrange(len(docs)), {"kind": "trap", "trap": "billed in EUR", "vendor": EUR_VENDOR,
                                           "invoice": next_invoice(EUR_VENDOR), "flags": ["foreign_currency"]})

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.pdf"):
        old.unlink()
    manifest = []
    for n, doc in enumerate(docs, start=1):
        name = f"{n:03d}.pdf"
        pdf = render_pdf(doc["invoice"], doc["vendor"])
        if doc["kind"] == "scanned" or doc.get("scan"):
            pdf = scan(pdf, rng)
        (out / name).write_bytes(pdf)
        manifest.append({"file": name, "received_order": n, "kind": doc["kind"], "trap": doc.get("trap"),
                         "scanned": doc["kind"] == "scanned" or bool(doc.get("scan")),
                         "layout": doc["vendor"].layout, "expected_flags": doc["flags"],
                         "truth": doc["invoice"].model_dump()})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("samples"))
    parser.add_argument("--seed", type=int, default=196)
    args = parser.parse_args()
    manifest = generate(args.out, args.seed)
    kinds = {k: sum(1 for d in manifest if d["kind"] == k) for k in ("clean", "scanned", "trap")}
    print(f"{len(manifest)} invoices in {args.out}/: {kinds['clean']} clean, {kinds['scanned']} scanned, {kinds['trap']} traps")


if __name__ == "__main__":
    main()
