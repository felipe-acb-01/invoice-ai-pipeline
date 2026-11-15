"""Where processed invoices live: one SQLite file and a folder with the original documents.

Every document is stored by its content hash, so dropping the same file into
the inbox twice never processes it twice. (The same invoice sent as a
different file, like a re-scan, is still caught: that is the ledger's job.)
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .schema import Invoice
from .validate import Ledger

STATUSES = ("pending", "approved", "rejected", "error")

SCHEMA = """
create table if not exists invoices (
    id            integer primary key,
    sha256        text not null unique,
    file_name     text not null,
    stored_as     text not null,
    received_at   text not null,
    status        text not null check (status in ('pending', 'approved', 'rejected', 'error')),
    flags         text not null default '[]',
    data          text,
    model         text,
    cost_usd      real not null default 0,
    seconds       real not null default 0,
    error         text,
    decided_at    text,
    decided_by    text,
    note          text,
    source        text,
    notified_at   text
);
"""

# Columns added after the first version: added in place, so an existing database keeps its data.
LATER_COLUMNS = {"source": "text", "notified_at": "text"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Record:
    id: int
    sha256: str
    file_name: str
    stored_as: str
    received_at: str
    status: str
    flags: list[str]
    invoice: Invoice | None
    model: str | None
    cost_usd: float
    seconds: float
    error: str | None
    decided_at: str | None
    decided_by: str | None
    note: str | None
    source: str | None = None
    notified_at: str | None = None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> Record:
        data = row["data"]
        return cls(row["id"], row["sha256"], row["file_name"], row["stored_as"], row["received_at"], row["status"],
                   json.loads(row["flags"]), Invoice.model_validate_json(data) if data else None, row["model"],
                   row["cost_usd"], row["seconds"], row["error"], row["decided_at"], row["decided_by"], row["note"],
                   row["source"], row["notified_at"])


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.docs = root / "documents"
        self.docs.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "invoices.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        have = {r["name"] for r in self.db.execute("pragma table_info(invoices)")}
        for name, kind in LATER_COLUMNS.items():
            if name not in have:
                self.db.execute(f"alter table invoices add column {name} {kind}")
        self.db.commit()

    # ── writing ──

    def has(self, sha256: str) -> bool:
        return self.db.execute("select 1 from invoices where sha256 = ?", (sha256,)).fetchone() is not None

    def keep_document(self, source: Path, sha256: str) -> str:
        name = f"{sha256[:16]}{source.suffix.lower()}"
        shutil.copyfile(source, self.docs / name)
        return name

    def add(self, *, sha256: str, file_name: str, stored_as: str, status: str, flags: list[str],
            invoice: Invoice | None, model: str | None, cost_usd: float, seconds: float, error: str | None,
            source: str | None = None) -> int:
        cur = self.db.execute(
            "insert into invoices (sha256, file_name, stored_as, received_at, status, flags, data, model, cost_usd,"
            " seconds, error, source) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sha256, file_name, stored_as, now(), status, json.dumps(flags),
             invoice.model_dump_json() if invoice else None, model, cost_usd, seconds, error, source))
        self.db.commit()
        return cur.lastrowid

    def decide(self, invoice_id: int, status: str, who: str, note: str | None = None) -> bool:
        """Approve or reject an invoice that is waiting. Returns False if it was not waiting."""
        if status not in ("approved", "rejected"):
            raise ValueError(status)
        cur = self.db.execute(
            "update invoices set status = ?, decided_at = ?, decided_by = ?, note = ? where id = ? and status = 'pending'",
            (status, now(), who, (note or "").strip() or None, invoice_id))
        self.db.commit()
        return cur.rowcount == 1

    def mark_notified(self, invoice_id: int) -> None:
        self.db.execute("update invoices set notified_at = ? where id = ?", (now(), invoice_id))
        self.db.commit()

    # ── reading ──

    def get(self, invoice_id: int) -> Record | None:
        row = self.db.execute("select * from invoices where id = ?", (invoice_id,)).fetchone()
        return Record.from_row(row) if row else None

    def list(self, status: str | None = None) -> list[Record]:
        if status:
            rows = self.db.execute("select * from invoices where status = ? order by id", (status,))
        else:
            rows = self.db.execute("select * from invoices order by id")
        return [Record.from_row(r) for r in rows]

    def counts(self) -> dict[str, int]:
        found = dict(self.db.execute("select status, count(*) from invoices group by status").fetchall())
        return {s: found.get(s, 0) for s in STATUSES}

    def ledger(self) -> Ledger:
        """Everything read so far, in arrival order, to catch duplicates of earlier invoices."""
        ledger = Ledger()
        for rec in self.list():
            if rec.invoice is not None:
                ledger.check_and_add(rec.invoice)
        return ledger
