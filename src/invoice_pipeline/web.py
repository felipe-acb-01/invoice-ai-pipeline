"""The approval screen: a queue of invoices, each shown next to its original document.

    python -m invoice_pipeline serve        # http://127.0.0.1:8040
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from starlette.requests import Request

from . import i18n
from .export import approved_workbook
from .pdf import page_count, page_png
from .store import STATUSES, Record, Store
from .pipeline import NOT_AN_INVOICE
from .validate import FLAGS, norm_number

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
MEDIA = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
TAB_LABELS = {"pending": "To approve", "approved": "Approved", "rejected": "Rejected", "error": "Set aside"}


def money(value: float, currency: str) -> str:
    if currency.upper() == "CLP":
        return "$" + f"{round(value):,}".replace(",", ".") + " CLP"
    symbol = {"USD": "$", "EUR": "€"}.get(currency.upper())
    text = f"{abs(value):,.2f}"
    sign = "-" if value < 0 else ""
    return f"{sign}{symbol}{text}" if symbol else f"{sign}{text} {currency}"


def nice_date(value: str | None, lang: str = "en") -> str:
    return i18n.nice_date(value, lang)


def explain(flag: str, inv, lang: str = "en") -> str:
    """The alert with its numbers, so the approver never has to redo the arithmetic."""
    m = lambda v: money(v, inv.currency)  # noqa: E731
    t = lambda text, **values: i18n.tr(text, lang, **values)  # noqa: E731

    def off(diff: float) -> str:
        return t("{amount} too much" if diff > 0 else "{amount} too little", amount=m(abs(diff)))

    if flag == "iva_mismatch":
        expected = round(inv.subtotal * 0.19)
        return t("The IVA should be {expected} (19 % of {net}); the invoice says {tax}, {off}.",
                 expected=m(expected), net=m(inv.subtotal), tax=m(inv.tax), off=off(inv.tax - expected))
    if flag == "total_mismatch":
        expected = inv.subtotal + inv.tax
        return t("Subtotal {subtotal} plus tax {tax} is {expected}; the invoice says {total}, {off}.",
                 subtotal=m(inv.subtotal), tax=m(inv.tax), expected=m(expected), total=m(inv.total),
                 off=off(inv.total - expected))
    if flag == "subtotal_mismatch":
        lines = sum(li.amount for li in inv.line_items)
        return t("The lines add up to {lines}; the subtotal says {subtotal}, {off}.",
                 lines=m(lines), subtotal=m(inv.subtotal), off=off(inv.subtotal - lines))
    if flag == "line_math":
        bad = next(li for li in inv.line_items if abs(li.quantity * li.unit_price - li.amount) > 0.01)
        return t("“{description}”: {quantity} × {price} = {product}, but the line says {amount}.",
                 description=bad.description, quantity=f"{bad.quantity:g}", price=m(bad.unit_price),
                 product=m(bad.quantity * bad.unit_price), amount=m(bad.amount))
    if flag == "date_order":
        return t("Due {due}, before the issue date {issued}.",
                 due=nice_date(inv.due_date, lang), issued=nice_date(inv.issue_date, lang))
    if flag == "foreign_currency":
        return t("The invoice is in {currency}, not in the currency the books are kept in.", currency=inv.currency)
    return t(FLAGS[flag])


@pass_context
def _translate(context, text: str, **values) -> str:
    return i18n.tr(text, context.get("lang", "en"), **values)


@pass_context
def _date_filter(context, value) -> str:
    return nice_date(value, context.get("lang", "en"))


@pass_context
def _decimal_filter(context, value: float, places: int = 1) -> str:
    return i18n.decimal(value, places, context.get("lang", "en"))


TEMPLATES.env.filters["money"] = money
TEMPLATES.env.globals["explain"] = explain
TEMPLATES.env.globals["NOT_AN_INVOICE"] = NOT_AN_INVOICE
TEMPLATES.env.filters["nice_date"] = _date_filter
TEMPLATES.env.filters["dec"] = _decimal_filter
TEMPLATES.env.globals["_"] = _translate
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


NOTICES = {  # the only messages the URL may carry: codes, never free text
    "reset": "Started a fresh demo with the sample invoices.",
}
COOKIE = "demo_sandbox"
CASE_URL = {  # the case study on the portfolio, in each language
    "en": "https://felipe-cortes.felipe-acb01.workers.dev/invoices/",
    "es": "https://felipe-cortes.felipe-acb01.workers.dev/es/facturas/",
}


def create_app(store: Store | None = None, approver: str = "Approver", after_decision=None, demo=None) -> FastAPI:
    """One store for a real deployment, or `demo` (a demo.Demo) for a private sandbox per visitor.

    `after_decision` runs after each approval or rejection (e.g. copy approved invoices to Google Sheets).
    If it fails, the decision still stands: the error is logged and the next run catches up."""
    app = FastAPI(title="Invoice approvals", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def language(request: Request, call_next):
        asked = request.query_params.get("lang")
        chosen = asked if asked in i18n.LANGS else None
        request.state.lang = chosen or (request.cookies.get(i18n.COOKIE) if request.cookies.get(i18n.COOKIE) in i18n.LANGS else "en")
        response = await call_next(request)
        if chosen:
            response.set_cookie(i18n.COOKIE, chosen, max_age=365 * 24 * 3600, samesite="lax",
                                secure=request.url.scheme == "https")
        return response

    if demo is not None:
        @app.middleware("http")
        async def sandbox_cookie(request: Request, call_next):
            sandbox = request.cookies.get(COOKIE)
            new = not demo.valid_id(sandbox)
            request.state.sandbox = demo.new_id() if new else sandbox
            response = await call_next(request)
            if new or getattr(request.state, "reset", False):
                response.set_cookie(COOKIE, request.state.sandbox, max_age=24 * 3600, httponly=True, samesite="lax",
                                    secure=request.url.scheme == "https")
            return response

    def S(request: Request) -> Store:
        return demo.store(request.state.sandbox) if demo is not None else store

    def ctx(request: Request, st: Store, **extra) -> dict:
        lang = request.state.lang
        base = {"counts": st.counts(), "approver": approver, "demo": demo is not None, "lang": lang,
                "lang_urls": {code: str(request.url.include_query_params(lang=code)) for code in i18n.LANGS},
                "case_url": CASE_URL[lang]}
        if demo is not None:
            base["remaining"] = demo.remaining(request.state.sandbox)
        return {**base, **extra}

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/")
    def home() -> RedirectResponse:
        return RedirectResponse("/invoices", status_code=303)

    @app.get("/invoices")
    def queue(request: Request, status: str = Query("pending"), notice: str = Query("", alias="msg")):
        if status not in STATUSES:
            raise HTTPException(404)
        st = S(request)
        return TEMPLATES.TemplateResponse(request, "queue.html", ctx(
            request, st, records=st.list(status), status=status, spent=sum(r.cost_usd for r in st.list()),
            notice=NOTICES.get(notice), upload_error=None))

    @app.get("/invoices/{invoice_id}")
    def detail(request: Request, invoice_id: int):
        st = S(request)
        rec = st.get(invoice_id)
        if rec is None:
            raise HTTPException(404)
        is_pdf = Path(rec.stored_as).suffix.lower() == ".pdf"
        return TEMPLATES.TemplateResponse(request, "detail.html", ctx(
            request, st, rec=rec, is_pdf=is_pdf, pages=page_count(st.docs / rec.stored_as) if is_pdf else 0,
            matches=earlier_matches(st, rec)))

    def decide(request: Request, invoice_id: int, status: str, note: str) -> RedirectResponse:
        st = S(request)
        if st.get(invoice_id) is None:
            raise HTTPException(404)
        if st.decide(invoice_id, status, approver, note) and after_decision:
            try:
                after_decision()
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger("invoice_pipeline").exception("After-decision step failed; will retry on next sync")
        waiting = [r.id for r in st.list("pending")]
        following = [i for i in waiting if i > invoice_id] or waiting
        return RedirectResponse(f"/invoices/{following[0]}" if following else "/invoices", status_code=303)

    @app.post("/invoices/{invoice_id}/approve")
    def approve(request: Request, invoice_id: int, note: str = Form("")):
        return decide(request, invoice_id, "approved", note)

    @app.post("/invoices/{invoice_id}/reject")
    def reject(request: Request, invoice_id: int, note: str = Form("")):
        return decide(request, invoice_id, "rejected", note)

    @app.get("/documents/{invoice_id}")
    def document(request: Request, invoice_id: int):
        st = S(request)
        rec = st.get(invoice_id)
        if rec is None:
            raise HTTPException(404)
        path = st.docs / rec.stored_as
        return FileResponse(path, media_type=MEDIA[path.suffix.lower()],
                            headers={"Content-Disposition": f'inline; filename="{rec.file_name}"'})

    @app.get("/documents/{invoice_id}/pages/{page}.png")
    def page_image(request: Request, invoice_id: int, page: int):
        """PDF pages as images: every browser shows them the same way, phones included."""
        st = S(request)
        rec = st.get(invoice_id)
        if rec is None or not rec.stored_as.endswith(".pdf"):
            raise HTTPException(404)
        png = page_png(st.docs / rec.stored_as, page)
        if png is None:
            raise HTTPException(404)
        return Response(png, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/export.xlsx")
    def export(request: Request) -> Response:
        return Response(approved_workbook(S(request)),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="approved-invoices.xlsx"'})

    if demo is not None:
        from .demo import DemoLimit

        @app.post("/invoices")
        async def upload(request: Request, document: UploadFile = File(...)):
            data = await document.read(5 * 1024 * 1024 + 1)
            try:
                new_id = demo.read_upload(request.state.sandbox, document.filename or "upload", data)
            except DemoLimit as exc:
                st = S(request)
                return TEMPLATES.TemplateResponse(request, "queue.html", ctx(
                    request, st, records=st.list("pending"), status="pending",
                    spent=sum(r.cost_usd for r in st.list()), notice=None,
                    upload_error=i18n.tr(exc.template, request.state.lang, **exc.values)), status_code=400)
            return RedirectResponse(f"/invoices/{new_id}", status_code=303)

        @app.post("/demo/restart")
        def restart(request: Request):
            request.state.sandbox = demo.new_id()
            request.state.reset = True
            return RedirectResponse("/invoices?msg=reset", status_code=303)

    return app


def app_from_env() -> FastAPI:
    return create_app(Store(Path(os.environ.get("INVOICE_DATA_DIR", "data"))), os.environ.get("APPROVER_NAME", "Approver"))
