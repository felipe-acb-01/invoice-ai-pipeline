"""Command line.

    python -m invoice_pipeline process --inbox inbox/      read new documents and queue them for approval
    python -m invoice_pipeline serve                       open the approval screen on http://127.0.0.1:8040
    python -m invoice_pipeline export out.xlsx             write approved invoices to Excel

Settings come from the environment (or a .env file): ANTHROPIC_API_KEY, INVOICE_MODEL,
INVOICE_DATA_DIR (default: data), BASE_CURRENCIES (default: USD; e.g. "USD,CLP"), APPROVER_NAME.
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
    args = parser.parse_args()

    from .store import Store

    store = Store(Path(os.environ.get("INVOICE_DATA_DIR", "data")))
    if args.command == "process":
        from .pipeline import process_folder

        bases = tuple(c.strip().upper() for c in os.environ.get("BASE_CURRENCIES", "USD").split(",") if c.strip())
        print(process_folder(args.inbox, store, base_currency=bases))
    elif args.command == "serve":
        import uvicorn

        from .web import create_app

        uvicorn.run(create_app(store, os.environ.get("APPROVER_NAME", "Approver")), host="127.0.0.1", port=args.port)
    elif args.command == "export":
        from .export import approved_workbook

        args.out.write_bytes(approved_workbook(store))
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
