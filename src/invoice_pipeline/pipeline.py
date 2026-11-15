"""Take new documents from an inbox folder, read them, check them and queue them for approval.

    python -m invoice_pipeline process --inbox inbox/

Every invoice goes to the approval queue. The ones that tripped a check arrive
marked, with the reason in one sentence. A document that cannot be read goes
to `error` and raises an alert; it never disappears silently.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .extract import Extraction, extract
from .store import Store
from .validate import check

log = logging.getLogger("invoice_pipeline")

ACCEPTED = (".pdf", ".jpg", ".jpeg", ".png")

Extractor = Callable[[Path], Extraction]
Alert = Callable[[str], None]


def log_alert(message: str) -> None:
    log.error("ALERT: %s", message)


@dataclass
class Summary:
    seen: int = 0
    skipped: int = 0
    queued: int = 0
    flagged: int = 0
    errors: int = 0
    cost_usd: float = 0.0
    ids: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        return (f"{self.seen} files: {self.queued} queued for approval ({self.flagged} with alerts), "
                f"{self.errors} could not be read, {self.skipped} already processed · US$ {self.cost_usd:.4f}")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def process_folder(inbox: Path, store: Store, extractor: Extractor | None = None, alert: Alert = log_alert,
                   base_currency: str | tuple[str, ...] = "USD", model: str | None = None,
                   sources: dict[str, str] | None = None) -> Summary:
    """`sources` maps a file name to where it came from (e.g. the email's sender and subject)."""
    sources = sources or {}
    extractor = extractor or (lambda p: extract(p, model=model))
    files = sorted(p for p in inbox.iterdir() if p.suffix.lower() in ACCEPTED)
    ledger = store.ledger()
    summary = Summary(seen=len(files))

    for path in files:
        digest = sha256_of(path)
        if store.has(digest):
            summary.skipped += 1
            continue
        stored_as = store.keep_document(path, digest)
        ex = extractor(path)
        summary.cost_usd += ex.cost_usd

        if ex.invoice is None:
            new_id = store.add(sha256=digest, file_name=path.name, stored_as=stored_as, status="error", flags=[],
                               invoice=None, model=ex.model, cost_usd=ex.cost_usd, seconds=ex.seconds, error=ex.error,
                               source=sources.get(path.name))
            summary.errors += 1
            alert(f"{path.name} could not be read ({ex.error}). It is in the Errors tab.")
        else:
            flags = check(ex.invoice, base_currency) + ledger.check_and_add(ex.invoice)
            new_id = store.add(sha256=digest, file_name=path.name, stored_as=stored_as, status="pending",
                               flags=flags, invoice=ex.invoice, model=ex.model, cost_usd=ex.cost_usd,
                               seconds=ex.seconds, error=None, source=sources.get(path.name))
            summary.queued += 1
            summary.flagged += bool(flags)
        summary.ids.append(new_id)
        log.info("%s → #%s", path.name, new_id)
    return summary
