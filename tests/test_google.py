"""Gmail and Sheets glue, against small fakes of the Google clients (no network)."""

import base64
import json
import shutil
from email import message_from_bytes, policy

import pytest
from fastapi.testclient import TestClient

from invoice_pipeline.extract import Extraction
from invoice_pipeline.google_io import Gmail, approval_email, notify_pending, sync_approved
from invoice_pipeline.pipeline import process_folder
from invoice_pipeline.schema import Invoice
from invoice_pipeline.store import Store
from invoice_pipeline.synth import generate
from invoice_pipeline.web import create_app


class Call:
    """Mimics googleapiclient's chained-builder style: svc.users().messages().list(...).execute()."""

    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGmail:
    def __init__(self, messages):
        self.msgs = messages  # id -> dict(payload, attachments)
        self.label_list = []
        self.labelled = {}
        self.sent = []

    def users(self): return self

    def getProfile(self, userId): return Call(lambda: {"emailAddress": "demo@example.com"})

    def list(self, userId, q=None, maxResults=None):
        if q is None:  # labels().list
            return Call(lambda: {"labels": list(self.label_list)})
        unprocessed = [m for m in self.msgs if m not in self.labelled]
        return Call(lambda: {"messages": [{"id": m} for m in unprocessed]})

    def create(self, userId, body):
        def go():
            self.label_list.append({"id": "L1", "name": body["name"]})
            return {"id": "L1"}
        return Call(go)

    def get(self, userId, id, messageId=None):
        if messageId is not None:  # attachments().get
            return Call(lambda: {"data": base64.urlsafe_b64encode(self.msgs[messageId]["attachments"][id]).decode()})
        return Call(lambda: self.msgs[id])

    def modify(self, userId, id, body):
        return Call(lambda: self.labelled.setdefault(id, body["addLabelIds"]))

    def send(self, userId, body):
        return Call(lambda: self.sent.append(message_from_bytes(base64.urlsafe_b64decode(body["raw"]), policy=policy.default)))



class GmailService(FakeGmail):
    def labels(self): return self
    def messages(self): return self
    def attachments(self): return self


class FakeSheets:
    def __init__(self):
        self.rows = []

    def spreadsheets(self): return self
    def values(self): return self

    def get(self, spreadsheetId, range):
        return Call(lambda: {"values": [[r[0]] for r in self.rows]} if self.rows else {})

    def append(self, spreadsheetId, range, valueInputOption, insertDataOption, body):
        return Call(lambda: self.rows.extend(body["values"]))


@pytest.fixture
def world(tmp_path):
    bank = tmp_path / "bank"
    manifest = generate(bank)
    truth = {d["file"]: Invoice.model_validate(d["truth"]) for d in manifest}
    pdf_a, pdf_b = manifest[0]["file"], manifest[1]["file"]
    svc = GmailService({
        "m1": {"payload": {"headers": [{"name": "From", "value": "Northwind <billing@northwind.example>"},
                                       {"name": "Subject", "value": "October invoice"}],
                           "parts": [{"filename": pdf_a, "body": {"attachmentId": "a1"}},
                                     {"filename": "logo.gif", "body": {"attachmentId": "a2"}}]},
               "attachments": {"a1": (bank / pdf_a).read_bytes(), "a2": b"GIF89a"}},
        "m2": {"payload": {"headers": [{"name": "From", "value": "ap@cedar.example"}, {"name": "Subject", "value": "Inv"}],
                           "parts": [{"mimeType": "multipart/mixed",
                                      "parts": [{"filename": pdf_b, "body": {"attachmentId": "b1"}}]}]},
               "attachments": {"b1": (bank / pdf_b).read_bytes()}},
    })
    store = Store(tmp_path / "data")
    reader = lambda p: Extraction(truth[p.name.split("-", 1)[1]], "fake", 0.1, 10, 1)  # noqa: E731
    return dict(svc=svc, gmail=Gmail(svc), store=store, reader=reader, tmp=tmp_path)


def test_fetch_saves_only_invoice_attachments_and_labels_messages(world):
    gmail, svc = world["gmail"], world["svc"]
    fetched = gmail.fetch_invoices(world["tmp"] / "incoming")
    assert fetched.messages == 2 and len(fetched.files) == 2  # the GIF logo is ignored
    assert set(svc.labelled) == {"m1", "m2"}
    assert any("billing@northwind.example · October invoice" == s for s in fetched.sources.values())
    # nothing new the second time: processed messages carry the label
    assert gmail.fetch_invoices(world["tmp"] / "incoming").messages == 0


def test_end_to_end_gmail_to_approval_email_to_sheet(world):
    gmail, store = world["gmail"], world["store"]
    fetched = gmail.fetch_invoices(world["tmp"] / "incoming")
    process_folder(world["tmp"] / "incoming", store, world["reader"], sources=fetched.sources)
    assert store.list()[0].source.startswith("billing@northwind.example")

    assert notify_pending(store, gmail, "approver@example.com", "http://app.test") == 2
    assert notify_pending(store, gmail, "approver@example.com", "http://app.test") == 0  # never twice
    mail = world["svc"].sent[0]
    assert mail["Subject"].startswith("[Approve] ") and mail["To"] == "approver@example.com"
    assert any(part.get_filename() for part in mail.walk())  # the original document is attached
    body = next(p for p in mail.walk() if p.get_content_type() == "text/plain").get_content()
    assert "http://app.test/invoices/" in body
    assert "/approve" not in body  # decisions only happen on the screen, never from a link a scanner can open

    sheets = FakeSheets()
    first = store.list("pending")[0]
    app = create_app(store, "Ana", after_decision=lambda: sync_approved(store, sheets, "SHEET"))
    TestClient(app).post(f"/invoices/{first.id}/approve", data={"note": "ok"})
    assert sheets.rows[0][0] == "Document ID" and sheets.rows[1][0] == first.sha256[:12] and sheets.rows[1][-1].startswith("billing@")
    assert sync_approved(store, sheets, "SHEET") == 0  # idempotent
    assert len(sheets.rows) == 2


def test_a_failing_sheet_does_not_undo_the_approval(world):
    store = world["store"]
    process_folder(world["gmail"].fetch_invoices(world["tmp"] / "incoming").files[0].parent, store, world["reader"])
    first = store.list("pending")[0]

    def broken():
        raise RuntimeError("Sheets is down")
    TestClient(create_app(store, "Ana", after_decision=broken)).post(f"/invoices/{first.id}/approve")
    assert store.get(first.id).status == "approved"


def test_flagged_invoice_email_says_why():
    inv = Invoice(invoice_number="1", vendor_name="V", vendor_tax_id=None, customer_name="C", issue_date="2026-10-01",
                  due_date=None, currency="USD", line_items=[], subtotal=0, tax=0, total=10)
    from invoice_pipeline.store import Record
    rec = Record(1, "x", "f.pdf", "x.pdf", "", "pending", ["total_mismatch"], inv, "m", 0, 1.0, None, None, None, None)
    subject, text, html = approval_email(rec, "http://x/invoices/1")
    assert "needs a closer look" in subject
    assert "Subtotal $0.00 plus tax $0.00 is $0.00; the invoice says $10.00, $10.00 too much." in text
    assert "<script" not in html


def test_sheet_key_does_not_collide_between_databases(tmp_path):
    """Regression: keyed by database id, invoice #1 of a second database was skipped because #1 was already there."""
    import json
    bank = tmp_path / "bank"
    manifest = generate(bank)
    sheets = FakeSheets()
    for n, name in enumerate(("one", "two")):
        store = Store(tmp_path / name)
        inbox = tmp_path / f"in-{name}"
        inbox.mkdir()
        f = manifest[n]["file"]
        (inbox / f).write_bytes((bank / f).read_bytes())
        process_folder(inbox, store, lambda p, m=manifest[n]: Extraction(Invoice.model_validate(m["truth"]), "fake", 0, 0, 0))
        store.decide(store.list()[0].id, "approved", "Ana")
        assert store.list()[0].id == 1
        assert sync_approved(store, sheets, "S") == 1
    assert len(sheets.rows) == 3


def test_alerts_carry_their_numbers():
    """He had to redo the IVA arithmetic by hand to understand an alert: the alert now does it."""
    from invoice_pipeline.schema import LineItem
    from invoice_pipeline.web import explain
    inv = Invoice(invoice_number="827", vendor_name="Soporte TI Andino SpA", vendor_tax_id=None, customer_name="C",
                  issue_date="2026-09-30", due_date=None, currency="CLP",
                  line_items=[LineItem(description="x", quantity=1, unit_price=340990, amount=340990)],
                  subtotal=340990, tax=65788, total=406778)
    assert explain("iva_mismatch", inv) == ("The IVA should be $64.788 CLP (19 % of $340.990 CLP); the invoice says "
                                            "$65.788 CLP, $1.000 CLP too much.")
    bad = inv.model_copy(update=dict(line_items=[LineItem(description="Visita", quantity=2, unit_price=45000, amount=100000)]))
    assert explain("line_math", bad) == "“Visita”: 2 × $45.000 CLP = $90.000 CLP, but the line says $100.000 CLP."


def test_an_unreadable_attachment_is_set_aside_with_an_alert_never_dropped(world):
    """An iPhone photo (HEIC) alone in an email used to vanish: the message was labelled and nobody knew."""
    svc, gmail, store = world["svc"], world["gmail"], world["store"]
    svc.msgs["m3"] = {"payload": {"headers": [{"name": "From", "value": "pepe@local.example"}, {"name": "Subject", "value": "boleta"}],
                                  "parts": [{"filename": "IMG_0042.HEIC", "body": {"attachmentId": "c1"}},
                                            {"filename": "invite.ics", "body": {"attachmentId": "c2"}}]},
                      "attachments": {"c1": b"\x00\x00\x00\x18ftypheic", "c2": b"BEGIN:VCALENDAR"}}
    pdf = next(iter(svc.msgs["m2"]["attachments"].values()))
    svc.msgs["m4"] = {"payload": {"headers": [{"name": "From", "value": "dte@proveedor.example"}, {"name": "Subject", "value": "DTE"}],
                                  "parts": [{"filename": "factura.pdf", "body": {"attachmentId": "d1"}},
                                            {"filename": "factura.xml", "body": {"attachmentId": "d2"}}]},
                      "attachments": {"d1": pdf + b"\n%m4", "d2": b"<DTE/>"}}
    fetched = gmail.fetch_invoices(world["tmp"] / "incoming")
    names = sorted(p.name.split("-", 1)[1] for p in fetched.files)
    assert "IMG_0042.HEIC" in names and "invite.ics" not in names  # the photo is kept, the calendar invite is not
    assert "factura.xml" not in names  # next to its PDF, a Chilean DTE's XML is the same invoice again

    alerts = []
    process_folder(world["tmp"] / "incoming", store, lambda p: Extraction(None, "fake", 0, 0, 0, "unused")
                   if "factura" in p.name else world["reader"](p), alert=alerts.append, sources=fetched.sources)
    heic = next(r for r in store.list("error") if r.file_name.endswith(".HEIC"))
    assert heic.source.startswith("pepe@local.example") and heic.cost_usd == 0  # never sent to the API
    assert any("IMG_0042.HEIC" in a and "Set aside" in a for a in alerts)

    client = TestClient(create_app(store, "Ana"))
    page = client.get(f"/invoices/{heic.id}")
    assert "A file type that cannot be read" in page.text and "<img" not in page.text.split("viewer")[1].split("</section>")[0]
    doc = client.get(f"/documents/{heic.id}")
    assert doc.status_code == 200 and doc.headers["content-disposition"].startswith("attachment")
    queue = client.get("/invoices?status=error")
    assert "Not a PDF or image" in queue.text


def test_a_folder_sets_aside_what_it_cannot_read_and_skips_hidden_files(tmp_path):
    inbox = tmp_path / "inbox"; inbox.mkdir()
    (inbox / ".DS_Store").write_bytes(b"junk")
    (inbox / "invoice.docx").write_bytes(b"PK\x03\x04 word")
    store, alerts = Store(tmp_path / "data"), []
    summary = process_folder(inbox, store, lambda p: (_ for _ in ()).throw(AssertionError("not read")), alert=alerts.append)
    assert summary.seen == 1 and store.counts()["error"] == 1 and "invoice.docx" in alerts[0]
