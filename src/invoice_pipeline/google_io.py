"""Gmail in, approval emails out, approved invoices to Google Sheets.

Gmail uses the mailbox owner's consent (OAuth, desktop flow): the first run
opens a browser once and the token is kept in secrets/. Sheets uses a service
account, so writing to the spreadsheet never needs a person to log in again.

Nothing here decides anything: it moves documents and messages around the
pipeline, and every failure becomes an alert instead of a silent skip.
"""

from __future__ import annotations

import base64
import html
import logging
import mimetypes
import re
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path

from .pipeline import ACCEPTED, DOCUMENT_LIKE
from .store import Record, Store
from .validate import FLAGS
from .web import explain, money, nice_date

log = logging.getLogger("invoice_pipeline")

SECRETS = Path("secrets")
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # read, label and send; never delete
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
PROCESSED_LABEL = "Invoices/Processed"
SHEET_HEADER = ["Document ID", "Vendor", "Vendor tax ID", "Invoice number", "Issue date", "Due date", "Currency", "Subtotal",
                "Tax", "Total", "Approved at (UTC)", "Approved by", "Note", "Source"]


# ── Credentials ────────────────────────────────────────────────────────────


def gmail_service(secrets: Path = SECRETS, interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token = secrets / "google_token.json"
    creds = Credentials.from_authorized_user_file(str(token), GMAIL_SCOPES) if token.exists() else None
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:  # noqa: BLE001 - an expired or revoked token means: ask again
            creds = None
    if not creds or not creds.valid:
        if not interactive:
            raise RuntimeError("Gmail is not authorized. Run: python -m invoice_pipeline authorize")
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets / "google_oauth_client.json"), GMAIL_SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
        token.write_text(creds.to_json())
        token.chmod(0o600)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def sheets_service(secrets: Path = SECRETS):
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_file(
        str(secrets / "google_service_account.json"), scopes=SHEETS_SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


# ── Gmail ──────────────────────────────────────────────────────────────────


@dataclass
class Fetched:
    files: list[Path]
    sources: dict[str, str]  # file name → "sender · subject"
    messages: int


def _parts(payload: dict):
    yield payload
    for part in payload.get("parts", []) or []:
        yield from _parts(part)


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:80] or "attachment"


class Gmail:
    def __init__(self, service):
        self.svc = service
        self._label_id: str | None = None

    def address(self) -> str:
        return self.svc.users().getProfile(userId="me").execute()["emailAddress"]

    def label_id(self) -> str:
        if self._label_id:
            return self._label_id
        labels = self.svc.users().labels().list(userId="me").execute().get("labels", [])
        found = next((l["id"] for l in labels if l["name"] == PROCESSED_LABEL), None)
        if not found:
            found = self.svc.users().labels().create(userId="me", body={
                "name": PROCESSED_LABEL, "labelListVisibility": "labelShow", "messageListVisibility": "show"}).execute()["id"]
        self._label_id = found
        return found

    def fetch_invoices(self, into: Path, max_messages: int = 50) -> Fetched:
        """Save the PDF and image attachments of unprocessed inbox messages, then label those messages.

        A message with no PDF, JPG or PNG but with a document-like attachment (an iPhone HEIC photo, an XML, a Word
        file) keeps that attachment too, so it lands in Set aside with an alert instead of vanishing. Next to a PDF
        those files are skipped: a Chilean invoice arrives as PDF + XML of the same document."""
        into.mkdir(parents=True, exist_ok=True)
        query = f'in:inbox has:attachment -label:"{PROCESSED_LABEL}" -subject:"[Approve]" -subject:"[Alert]"'
        found = self.svc.users().messages().list(userId="me", q=query, maxResults=max_messages).execute()
        files, sources = [], {}
        messages = found.get("messages", [])
        for ref in reversed(messages):  # oldest first, so duplicates are judged in arrival order
            msg = self.svc.users().messages().get(userId="me", id=ref["id"]).execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
            sender = parseaddr(headers.get("from", ""))[1] or headers.get("from", "unknown sender")
            source = f"{sender} · {headers.get('subject', '(no subject)')}"
            parts = [(p["filename"], p["body"]["attachmentId"]) for p in _parts(msg["payload"])
                     if p.get("filename") and p.get("body", {}).get("attachmentId")]
            readable = [p for p in parts if Path(p[0]).suffix.lower() in ACCEPTED]
            keep = readable or [p for p in parts if Path(p[0]).suffix.lower() in DOCUMENT_LIKE]
            for name, att_id in keep:
                data = self.svc.users().messages().attachments().get(
                    userId="me", messageId=ref["id"], id=att_id).execute()["data"]
                path = into / f"{ref['id'][:10]}-{_safe(name)}"
                path.write_bytes(base64.urlsafe_b64decode(data))
                files.append(path)
                sources[path.name] = source
            self.svc.users().messages().modify(userId="me", id=ref["id"],
                                               body={"addLabelIds": [self.label_id()]}).execute()
        return Fetched(files, sources, len(messages))

    def send(self, to: str, subject: str, text: str, html_body: str | None = None,
             attachments: tuple[Path, ...] = ()) -> None:
        msg = EmailMessage()
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(text)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
        for path in attachments:
            kind = (mimetypes.guess_type(path.name)[0] or "application/octet-stream").split("/")
            msg.add_attachment(path.read_bytes(), maintype=kind[0], subtype=kind[1], filename=path.name)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        self.svc.users().messages().send(userId="me", body={"raw": raw}).execute()


# ── Approval and alert emails ──────────────────────────────────────────────


def approval_email(rec: Record, review_url: str) -> tuple[str, str, str]:
    """Subject, plain text and HTML for the email that asks someone to approve an invoice.

    The email links to the review screen instead of carrying Approve/Reject links itself:
    mail scanners open links, and a decision must never happen because a scanner did.
    """
    inv = rec.invoice
    total = money(inv.total, inv.currency)
    flag_lines = [explain(f, inv) for f in rec.flags]
    status = "needs a closer look" if flag_lines else "all checks passed"
    subject = f"[Approve] {inv.vendor_name} · {total} · {status}"
    text = "\n".join([
        f"{inv.vendor_name} sent invoice {inv.invoice_number} for {total}.",
        f"Issued {nice_date(inv.issue_date)}, due {nice_date(inv.due_date) if inv.due_date else 'on receipt'}.",
        "",
        *(["Review before approving:", *[f"- {line}" for line in flag_lines], ""] if flag_lines else ["All checks passed.", ""]),
        f"Review and decide: {review_url}",
        "The original document is attached.",
    ])
    e = html.escape
    checks = ("<p style='margin:0 0 6px;font-weight:600;color:#9A5B00'>Review before approving</p><ul style='margin:0;padding-left:18px'>"
              + "".join(f"<li>{e(line)}</li>" for line in flag_lines) + "</ul>") if flag_lines else \
             "<p style='margin:0;font-weight:600;color:#0F6A47'>All checks passed</p>"
    bg = "#FDF1DD" if flag_lines else "#E3F4EC"
    html_body = f"""<div style="font-family:-apple-system,Segoe UI,sans-serif;color:#17202B;max-width:560px">
<p style="margin:0;color:#5C6774">{e(inv.vendor_name)} · invoice {e(inv.invoice_number)}</p>
<p style="margin:4px 0 2px;font-size:26px;font-weight:700">{e(total)}</p>
<p style="margin:0 0 16px;color:#5C6774">Issued {e(nice_date(inv.issue_date))} · due {e(nice_date(inv.due_date) if inv.due_date else 'on receipt')}</p>
<div style="background:{bg};border-radius:8px;padding:12px 14px;margin-bottom:16px">{checks}</div>
<p><a href="{e(review_url)}" style="display:inline-block;background:#1C4E80;color:#fff;text-decoration:none;font-weight:600;padding:10px 16px;border-radius:6px">Review and decide</a></p>
<p style="color:#8A939E;font-size:12px">The original document is attached. Read by {e(rec.model or '')} in {rec.seconds:.1f} s.</p></div>"""
    return subject, text, html_body


def notify_pending(store: Store, gmail: Gmail, to: str, base_url: str) -> int:
    """Send one approval email per waiting invoice that has not had one yet."""
    sent = 0
    for rec in store.list("pending"):
        if rec.notified_at:
            continue
        subject, text, html_body = approval_email(rec, f"{base_url.rstrip('/')}/invoices/{rec.id}")
        gmail.send(to, subject, text, html_body, attachments=(store.docs / rec.stored_as,))
        store.mark_notified(rec.id)
        sent += 1
    return sent


def email_alert(gmail: Gmail, to: str):
    def alert(message: str) -> None:
        log.error("ALERT: %s", message)
        try:
            gmail.send(to, "[Alert] Invoice pipeline", message)
        except Exception as exc:  # noqa: BLE001 - the alert must not take the pipeline down with it
            log.error("Could not email the alert: %s", exc)
    return alert


# ── Sheets ─────────────────────────────────────────────────────────────────


def document_key(rec: Record) -> str:
    """The sheet's key: a fingerprint of the original file. Unlike a database id, it never collides
    between two databases (a reset, a second machine), so the sync can never skip or duplicate a row."""
    return rec.sha256[:12]


def sheet_row(rec: Record) -> list:
    inv = rec.invoice
    return [document_key(rec), inv.vendor_name, inv.vendor_tax_id or "", inv.invoice_number, inv.issue_date, inv.due_date or "",
            inv.currency, inv.subtotal, inv.tax, inv.total, rec.decided_at, rec.decided_by, rec.note or "",
            rec.source or rec.file_name]


def sync_approved(store: Store, service, sheet_id: str) -> int:
    """Append approved invoices that are not in the sheet yet. Safe to run any number of times."""
    values = service.spreadsheets().values()
    column = values.get(spreadsheetId=sheet_id, range="A:A").execute().get("values", [])
    present = {str(row[0]) for row in column[1:] if row}
    rows = [] if column else [SHEET_HEADER]
    rows += [sheet_row(r) for r in store.list("approved") if document_key(r) not in present]
    new = len(rows) - (0 if column else 1)
    if new or not column:
        values.append(spreadsheetId=sheet_id, range="A1", valueInputOption="RAW", insertDataOption="INSERT_ROWS",
                      body={"values": rows}).execute()
    return new
