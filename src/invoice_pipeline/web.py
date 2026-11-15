"""The approval screen: a queue of invoices, each shown next to its original document.

    python -m invoice_pipeline serve        # http://127.0.0.1:8040
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from .export import approved_workbook
from .store import STATUSES, Record, Store
from .validate import FLAGS, norm_number

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MEDIA = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
TAB_LABELS = {"pending": "To approve", "approved": "Approved", "rejected": "Rejected", "error": "Could not read"}


def money(value: float, currency: str) -> str:
    if currency.upper() == "CLP":
        return "$" + f"{round(value):,}".replace(",", ".") + " CLP"
    symbol = {"USD": "$", "EUR": "€"}.get(currency.upper())
    text = f"{abs(value):,.2f}"
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{text}" if symbol else f"{sign}{text} {currency}"


def nice_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return value
    return f"{d.strftime('%b')} {d.day}, {d.year}"


def explain(flag: str, inv) -> str:
    """The alert with its numbers, so the approver never has to redo the arithmetic."""
    m = lambda v: money(v, inv.currency)  # noqa: E731

    def off(diff: float) -> str:
        return f"{m(abs(diff))} {'too much' if diff > 0 else 'too little'}"

    if flag == "iva_mismatch":
        expected = round(inv.subtotal * 0.19)
        return (f"The IVA should be {m(expected)} (19 % of {m(inv.subtotal)}); the invoice says {m(inv.tax)}, "
                f"{off(inv.tax - expected)}.")
    if flag == "total_mismatch":
        expected = inv.subtotal + inv.tax
        return (f"Subtotal {m(inv.subtotal)} plus tax {m(inv.tax)} is {m(expected)}; the invoice says "
                f"{m(inv.total)}, {off(inv.total - expected)}.")
    if flag == "subtotal_mismatch":
        lines = sum(li.amount for li in inv.line_items)
        return (f"The lines add up to {m(lines)}; the subtotal says {m(inv.subtotal)}, "
                f"{off(inv.subtotal - lines)}.")
    if flag == "line_math":
        bad = next(li for li in inv.line_items if abs(li.quantity * li.unit_price - li.amount) > 0.01)
        return (f"“{bad.description}”: {bad.quantity:g} × {m(bad.unit_price)} = {m(bad.quantity * bad.unit_price)}, "
                f"but the line says {m(bad.amount)}.")
    if flag == "date_order":
        return f"Due {nice_date(inv.due_date)}, before the issue date {nice_date(inv.issue_date)}."
    if flag == "foreign_currency":
        return f"The invoice is in {inv.currency}, not in the currency the books are kept in."
    return FLAGS[flag]


TEMPLATES.env.filters["money"] = money
TEMPLATES.env.globals["explain"] = explain
TEMPLATES.env.filters["nice_date"] = nice_date
TEMPLATES.env.globals["FLAGS"] = FLAGS
TEMPLATES.env.globals["TAB_LABELS"] = TAB_LABELS


def _vendor(text: str) -> str:
    return "".join(ch for ch in text.lower() if ch.isalnum())


def earlier_matches(store: Store, rec: Record) -> list[tuple[str, Record]]:
    """Earlier invoices this one may repeat, so the approver can compare them side by side."""
    if rec.invoice is None:
        return []
    inv, found = rec.invoice, []
    for other in store.list():
        if other.id >= rec.id or other.invoice is None or _vendor(other.invoice.vendor_name) != _vendor(inv.vendor_name):
            continue
        if norm_number(other.invoice.invoice_number) == norm_number(inv.invoice_number):
            found.append(("same number", other))
        elif other.invoice.issue_date == inv.issue_date and round(other.invoice.total, 2) == round(inv.total, 2):
            found.append(("same date and total", other))
    return found


def page_count(path: Path) -> int:
    import pypdfium2 as pdfium

    return len(pdfium.PdfDocument(path))


def create_app(store: Store, approver: str = "Approver", after_decision=None) -> FastAPI:
    """`after_decision` runs after each approval or rejection (e.g. copy approved invoices to Google Sheets).
    If it fails, the decision still stands: the error is logged and the next run catches up."""
    app = FastAPI(title="Invoice approvals", docs_url=None, redoc_url=None)

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/invoices", status_code=303)

    @app.get("/invoices")
    def queue(request: Request, status: str = Query("pending")):
        if status not in STATUSES:
            raise HTTPException(404)
        records = store.list(status)
        return TEMPLATES.TemplateResponse(request, "queue.html", {
            "records": records, "status": status, "counts": store.counts(),
            "spent": sum(r.cost_usd for r in store.list()), "approver": approver})

    @app.get("/invoices/{invoice_id}")
    def detail(request: Request, invoice_id: int):
        rec = store.get(invoice_id)
        if rec is None:
            raise HTTPException(404)
        is_pdf = Path(rec.stored_as).suffix.lower() == ".pdf"
        return TEMPLATES.TemplateResponse(request, "detail.html", {
            "rec": rec, "counts": store.counts(), "approver": approver, "is_pdf": is_pdf,
            "pages": page_count(store.docs / rec.stored_as) if is_pdf else 0,
            "matches": earlier_matches(store, rec)})

    def decide(invoice_id: int, status: str, note: str) -> RedirectResponse:
        if store.get(invoice_id) is None:
            raise HTTPException(404)
        if store.decide(invoice_id, status, approver, note) and after_decision:
            try:
                after_decision()
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger("invoice_pipeline").exception("After-decision step failed; will retry on next sync")
        waiting = [r.id for r in store.list("pending")]
        following = [i for i in waiting if i > invoice_id] or waiting
        return RedirectResponse(f"/invoices/{following[0]}" if following else "/invoices", status_code=303)

    @app.post("/invoices/{invoice_id}/approve")
    def approve(invoice_id: int, note: str = Form("")):
        return decide(invoice_id, "approved", note)

    @app.post("/invoices/{invoice_id}/reject")
    def reject(invoice_id: int, note: str = Form("")):
        return decide(invoice_id, "rejected", note)

    @app.get("/documents/{invoice_id}")
    def document(invoice_id: int):
        rec = store.get(invoice_id)
        if rec is None:
            raise HTTPException(404)
        path = store.docs / rec.stored_as
        return FileResponse(path, media_type=MEDIA[path.suffix.lower()],
                            headers={"Content-Disposition": f'inline; filename="{rec.file_name}"'})

    @app.get("/documents/{invoice_id}/pages/{page}.png")
    def page_image(invoice_id: int, page: int):
        """PDF pages as images: every browser shows them the same way, phones included."""
        import io

        import pypdfium2 as pdfium

        rec = store.get(invoice_id)
        if rec is None or not rec.stored_as.endswith(".pdf"):
            raise HTTPException(404)
        doc = pdfium.PdfDocument(store.docs / rec.stored_as)
        if not 1 <= page <= len(doc):
            raise HTTPException(404)
        buf = io.BytesIO()
        doc[page - 1].render(scale=1.6).to_pil().save(buf, "PNG", optimize=True)
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/export.xlsx")
    def export() -> Response:
        return Response(approved_workbook(store),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="approved-invoices.xlsx"'})

    return app


def app_from_env() -> FastAPI:
    return create_app(Store(Path(os.environ.get("INVOICE_DATA_DIR", "data"))), os.environ.get("APPROVER_NAME", "Approver"))
