"""The system around the reader: inbox → queue → decision → Excel. A fake reader returns the right answers ($0)."""

import io
import json
import shutil

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from invoice_pipeline.extract import Extraction
from invoice_pipeline.pipeline import process_folder
from invoice_pipeline.schema import Invoice
from invoice_pipeline.store import Store
from invoice_pipeline.synth import generate
from invoice_pipeline.web import create_app, money


@pytest.fixture(scope="module")
def bank(tmp_path_factory):
    out = tmp_path_factory.mktemp("bank")
    generate(out)
    return out


def fake_reader(bank):
    truth = {d["file"]: Invoice.model_validate(d["truth"]) for d in json.loads((bank / "manifest.json").read_text())}

    def read(path):
        if path.name == "broken.pdf":
            return Extraction(None, "fake", 0.1, 0, 0, "stop_reason=refusal")
        return Extraction(truth[path.name], "fake", 0.1, 100, 10)
    return read


@pytest.fixture
def system(bank, tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for d in json.loads((bank / "manifest.json").read_text()):
        shutil.copy(bank / d["file"], inbox / d["file"])
    (inbox / "notes.txt").write_text("not an invoice")
    alerts = []
    store = Store(tmp_path / "data")
    summary = process_folder(inbox, store, fake_reader(bank), alert=alerts.append)
    return dict(inbox=inbox, store=store, summary=summary, alerts=alerts, bank=bank)


def test_every_invoice_is_queued_and_traps_arrive_marked(system):
    s, store = system["summary"], system["store"]
    assert (s.seen, s.queued, s.flagged, s.errors) == (60, 60, 5, 0)
    flagged = sorted(f for r in store.list("pending") for f in r.flags)
    assert flagged == sorted(["duplicate", "possible_duplicate", "total_mismatch", "line_math", "foreign_currency"])


def test_running_again_processes_nothing_new(system):
    again = process_folder(system["inbox"], system["store"], fake_reader(system["bank"]))
    assert (again.queued, again.skipped) == (0, 60)


def test_duplicates_are_caught_across_runs(system, tmp_path):
    """The ledger is rebuilt from the database, so a re-sent invoice is caught even in a later batch."""
    store = system["store"]
    first = store.list()[0]
    later = tmp_path / "later"
    later.mkdir()
    shutil.copy(system["inbox"] / first.file_name, later / "resent.pdf")
    with open(later / "resent.pdf", "ab") as f:
        f.write(b"\n% re-saved")  # different bytes, same invoice
    reader = fake_reader(system["bank"])
    process_folder(later, store, lambda p: reader(system["inbox"] / first.file_name))
    assert store.list()[-1].flags == ["duplicate"]


def test_unreadable_document_goes_to_errors_and_alerts(system):
    (system["inbox"] / "broken.pdf").write_bytes(b"%PDF-1.4 nothing")
    s = process_folder(system["inbox"], system["store"], fake_reader(system["bank"]), alert=system["alerts"].append)
    assert s.errors == 1
    assert system["store"].counts()["error"] == 1
    assert "broken.pdf" in system["alerts"][-1]


def test_approve_and_reject_from_the_screen_then_export(system):
    store = system["store"]
    client = TestClient(create_app(store, "Ana"))
    queue = client.get("/invoices")
    assert queue.status_code == 200 and "To approve" in queue.text

    first, second = store.list("pending")[:2]
    page = client.get(f"/invoices/{first.id}")
    assert 'formaction="/invoices/%d/approve"' % first.id in page.text  # press the screen's own button
    r = client.post(f"/invoices/{first.id}/approve", data={"note": "cost center 12"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/invoices/{second.id}"
    client.post(f"/invoices/{second.id}/reject", data={"note": ""})

    assert store.get(first.id).status == "approved" and store.get(first.id).decided_by == "Ana"
    assert store.get(second.id).status == "rejected"
    # a decided invoice cannot be decided again
    assert store.decide(first.id, "rejected", "Ana") is False

    wb = load_workbook(io.BytesIO(client.get("/export.xlsx").content))
    rows = list(wb["Invoices"].iter_rows(values_only=True))
    assert len(rows) == 2 and rows[1][0] == first.id and rows[1][12] == "cost center 12"
    assert len(list(wb["Lines"].iter_rows())) == 1 + len(first.invoice.line_items)


def test_flagged_invoice_page_explains_why(system):
    store = system["store"]
    rec = next(r for r in store.list("pending") if r.flags)
    page = TestClient(create_app(store)).get(f"/invoices/{rec.id}")
    assert "Review before approving" in page.text
    doc = TestClient(create_app(store)).get(f"/documents/{rec.id}")
    assert doc.status_code == 200 and doc.headers["content-type"] == "application/pdf"


def test_unknown_ids_are_404(system):
    client = TestClient(create_app(system["store"]))
    for url in ("/invoices/99999", "/documents/99999", "/invoices?status=bogus"):
        assert client.get(url).status_code == 404
    assert client.post("/invoices/99999/approve").status_code == 404


def test_money_formats():
    assert money(1234.5, "USD") == "$1,234.50"
    assert money(-139.4, "USD") == "-$139.40"
    assert money(359368, "CLP") == "$359.368 CLP"
    assert money(1402.2, "EUR") == "€1,402.20"


def test_duplicate_links_to_the_earlier_invoice_and_pdf_pages_render(system):
    store = system["store"]
    dup = next(r for r in store.list("pending") if r.flags == ["duplicate"])
    client = TestClient(create_app(store))
    page = client.get(f"/invoices/{dup.id}").text
    assert "Compare with:" in page and "same number" in page
    original = next(r for r in store.list() if r.id < dup.id and r.invoice.invoice_number == dup.invoice.invoice_number)
    assert f'href="/invoices/{original.id}"' in page
    img = client.get(f"/documents/{original.id}/pages/1.png")
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    assert client.get(f"/documents/{original.id}/pages/9.png").status_code == 404


def test_export_never_turns_document_text_into_formulas(tmp_path):
    """Whoever sends an invoice controls its text; in the accountant's Excel it must stay text."""
    from invoice_pipeline.export import approved_workbook
    from invoice_pipeline.schema import Invoice, LineItem
    from invoice_pipeline.store import Store

    store = Store(tmp_path)
    evil = Invoice(invoice_number="=1+1", vendor_name='=HYPERLINK("http://evil.example","Click")', vendor_tax_id=None,
                   customer_name="Me", issue_date="2026-11-01", due_date=None, currency="USD",
                   line_items=[LineItem(description="=cmd|' /C calc'!A0", quantity=1, unit_price=10, amount=10)],
                   subtotal=10, tax=0, total=10)
    rid = store.add(sha256="x", file_name="evil.pdf", stored_as="x.pdf", status="pending", flags=[], invoice=evil,
                    model="m", cost_usd=0, seconds=0, error=None)
    store.decide(rid, "approved", "Ana", "=2+2")
    wb = load_workbook(io.BytesIO(approved_workbook(store)))
    cells = [c for ws in wb for row in ws.iter_rows(min_row=2) for c in row if isinstance(c.value, str)]
    texts = {c.value for c in cells}
    assert {'=HYPERLINK("http://evil.example","Click")', "=1+1", "=2+2", "=cmd|' /C calc'!A0"} <= texts
    assert [c.coordinate for c in cells if c.data_type == "f"] == []
