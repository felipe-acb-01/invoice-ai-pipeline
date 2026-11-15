"""Command line.

    python -m invoice_pipeline process --inbox inbox/      read new documents and queue them for approval
    python -m invoice_pipeline serve                       open the approval screen on http://127.0.0.1:8040
    python -m invoice_pipeline export out.xlsx             write approved invoices to Excel

  With Google (secrets/ holds the credentials):
    python -m invoice_pipeline authorize                   one-time: allow access to the Gmail inbox
    python -m invoice_pipeline run                         Gmail → read → queue → approval emails → Sheets
    python -m invoice_pipeline sync-sheets                 copy approved invoices to the spreadsheet
    python -m invoice_pipeline seed-gmail samples/ --count 5   email sample invoices to the demo inbox

Settings come from the environment (or a .env file): ANTHROPIC_API_KEY, INVOICE_MODEL,
INVOICE_DATA_DIR (default: data), BASE_CURRENCIES (default: USD; e.g. "USD,CLP"), APPROVER_NAME,
SHEET_ID, APPROVER_EMAIL and ALERT_EMAIL (default: the Gmail inbox itself), APP_BASE_URL (default: http://127.0.0.1:8040).
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .evaluate import load_dotenv


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="invoice_pipeline", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("process", help="read new documents from a folder")
    p.add_argument("--inbox", type=Path, default=Path("inbox"))
    s = sub.add_parser("serve", help="open the approval screen")
    s.add_argument("--port", type=int, default=8040)
    e = sub.add_parser("export", help="write approved invoices to Excel")
    e.add_argument("out", type=Path)
    sub.add_parser("authorize", help="one-time Gmail consent")
    sub.add_parser("run", help="Gmail → queue → approval emails → Sheets")
    sub.add_parser("sync-sheets", help="copy approved invoices to Google Sheets")
    sd = sub.add_parser("seed-gmail", help="email sample invoices to the demo inbox")
    sd.add_argument("folder", type=Path)
    sd.add_argument("--count", type=int, default=5)
    args = parser.parse_args()

    from .store import Store

    store = Store(Path(os.environ.get("INVOICE_DATA_DIR", "data")))
    bases = tuple(c.strip().upper() for c in os.environ.get("BASE_CURRENCIES", "USD").split(",") if c.strip())
    sheet_id = os.environ.get("SHEET_ID")
    base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8040")

    if args.command == "process":
        from .pipeline import process_folder

        print(process_folder(args.inbox, store, base_currency=bases))
    elif args.command == "serve":
        import uvicorn

        from .web import create_app

        after = None
        if sheet_id:
            from .google_io import sheets_service, sync_approved

            after = lambda: sync_approved(store, sheets_service(), sheet_id)  # noqa: E731
        uvicorn.run(create_app(store, os.environ.get("APPROVER_NAME", "Approver"), after), host="127.0.0.1", port=args.port)
    elif args.command == "authorize":
        from .google_io import Gmail, gmail_service

        print(f"Authorized: {Gmail(gmail_service()).address()}")
    elif args.command == "run":
        from .google_io import Gmail, email_alert, gmail_service, notify_pending, sheets_service, sync_approved
        from .pipeline import process_folder

        gmail = Gmail(gmail_service(interactive=False))
        me = gmail.address()
        alert = email_alert(gmail, os.environ.get("ALERT_EMAIL", me))
        try:
            fetched = gmail.fetch_invoices(store.root / "incoming")
            print(f"Gmail: {fetched.messages} new messages, {len(fetched.files)} attachments")
            print(process_folder(store.root / "incoming", store, alert=alert, base_currency=bases,
                                 sources=fetched.sources))
            print(f"Approval emails sent: {notify_pending(store, gmail, os.environ.get('APPROVER_EMAIL', me), base_url)}")
            if sheet_id:
                print(f"Rows added to the sheet: {sync_approved(store, sheets_service(), sheet_id)}")
        except Exception as exc:  # noqa: BLE001 - say so by email, then fail loudly
            alert(f"The pipeline stopped: {type(exc).__name__}: {exc}")
            raise
    elif args.command == "sync-sheets":
        from .google_io import sheets_service, sync_approved

        print(f"Rows added: {sync_approved(store, sheets_service(), sheet_id)}")
    elif args.command == "seed-gmail":
        from .google_io import Gmail, gmail_service

        gmail = Gmail(gmail_service(interactive=False))
        me = gmail.address()
        files = sorted(p for p in args.folder.iterdir() if p.suffix.lower() in (".pdf", ".jpg", ".png"))[: args.count]
        for path in files:
            gmail.send(me, f"Invoice attached ({path.name})", "Hi, please find our invoice attached.\n\nRegards",
                       attachments=(path,))
        print(f"Sent {len(files)} sample invoices to {me}")
    elif args.command == "export":
        from .export import approved_workbook

        args.out.write_bytes(approved_workbook(store))
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
