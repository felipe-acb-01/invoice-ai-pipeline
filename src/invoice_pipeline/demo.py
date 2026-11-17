"""The public demo: every visitor gets a private sandbox, pre-filled with sample invoices.

    python -m invoice_pipeline.demo build-seed     # pick sample invoices + Haiku's real answers into demo_seed/
    python -m invoice_pipeline demo                # serve on 0.0.0.0:$PORT (what Railway runs)

The samples are not read again on each visit: demo_seed/ holds the answers
Claude Haiku gave for them during the evaluation (with their real cost and
time), so opening the demo costs nothing. Only files a visitor uploads are
sent to the API, within these limits:

  - DEMO_SANDBOX_LIMIT uploads per visitor per day (default 5)
  - DEMO_DAILY_LIMIT uploads per day for everyone together (default 60)
  - PDF, JPG or PNG; at most 5 MB and 3 pages
  - sandboxes, uploads included, are deleted after 24 hours
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .extract import Extraction, extract
from .pipeline import process_folder
from .schema import Invoice
from .store import Store

SEED = Path(os.environ.get("DEMO_SEED_DIR", Path(__file__).resolve().parents[2] / "demo_seed"))
BASES = ("USD", "CLP")
MAX_BYTES = 5 * 1024 * 1024
MAX_PAGES = 3
MAGIC = {b"%PDF": ".pdf", b"\xff\xd8\xff": ".jpg", b"\x89PNG": ".png"}

# (bank, how to find the document in its manifest). Order = arrival order in the queue.
SEED_PICKS = (
    ("samples", {"kind": "clean"}),
    ("samples_hard", {"kind": "chile"}),
    ("samples", {"trap": "total off by 100"}),
    ("samples_hard", {"kind": "two_page"}),
    ("samples_hard", {"kind": "photo", "base_currency": "USD"}),
    ("samples", {"kind": "scanned"}),
    ("samples_hard", {"trap": "IVA off by $1.000"}),
    ("samples", {"trap": "billed in EUR"}),
    ("samples_hard", {"kind": "discount"}),
    ("samples_hard", {"trap": "quote"}),
)


class DemoLimit(Exception):
    """A visitor-facing reason an upload was not read."""


# ── Seed ───────────────────────────────────────────────────────────────────


def build_seed(root: Path = Path("."), out: Path = SEED, cache_version: str | None = None) -> list[str]:
    from .extract import PROMPT_VERSION

    version = cache_version or PROMPT_VERSION
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    answers, names = {}, []
    for n, (bank, match) in enumerate(SEED_PICKS, start=1):
        manifest = json.loads((root / bank / "manifest.json").read_text())
        doc = next(d for d in manifest if all(d.get(k) == v for k, v in match.items()))
        cached = root / "runs" / bank / "claude-haiku-5-5" / version / (Path(doc["file"]).stem + ".json")
        if not cached.exists():
            raise SystemExit(f"No Haiku answer cached for {bank}/{doc['file']}: run the evaluation with Haiku first.")
        name = f"{n:02d}-{bank.replace('samples_hard', 'hard').replace('samples', 'std')}-{doc['file']}"
        shutil.copy(root / bank / doc["file"], out / name)
        answers[name] = json.loads(cached.read_text())
        names.append(name)
    (out / "answers.json").write_text(json.dumps(answers, indent=1, ensure_ascii=False) + "\n")
    return names


def _seed_reader(seed: Path):
    answers = json.loads((seed / "answers.json").read_text())

    def read(path: Path) -> Extraction:
        a = answers[path.name]
        inv = Invoice.model_validate(a["invoice"]) if a["invoice"] else None
        return Extraction(inv, a["model"], a["seconds"], a["input_tokens"], a["output_tokens"], a["error"])
    return read


# ── Sandboxes and limits ───────────────────────────────────────────────────


@dataclass
class Demo:
    root: Path
    sandbox_limit: int = 5
    daily_limit: int = 60
    ttl_seconds: int = 24 * 3600
    seed: Path = SEED
    extractor: object = None  # injectable for tests
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_env(cls, root: Path) -> Demo:
        return cls(root, int(os.environ.get("DEMO_SANDBOX_LIMIT", 5)), int(os.environ.get("DEMO_DAILY_LIMIT", 60)))

    @staticmethod
    def new_id() -> str:
        return secrets.token_hex(12)

    @staticmethod
    def valid_id(value: str | None) -> bool:
        return bool(value) and len(value) == 24 and all(c in "0123456789abcdef" for c in value)

    def store(self, sandbox: str) -> Store:
        path = self.root / "sandboxes" / sandbox
        fresh = not (path / "invoices.db").exists()
        store = Store(path)
        if fresh:
            self.cleanup()
            process_folder(self.seed, store, _seed_reader(self.seed), alert=lambda m: None, base_currency=BASES,
                           sources={p.name: "sample invoice" for p in self.seed.iterdir()})
        return store

    def cleanup(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        for box in (self.root / "sandboxes").glob("*"):
            if box.is_dir() and box.stat().st_mtime < cutoff:
                shutil.rmtree(box, ignore_errors=True)

    # usage

    def _usage(self) -> dict:
        path = self.root / "usage.json"
        data = json.loads(path.read_text()) if path.exists() else {}
        return data if data.get("day") == date.today().isoformat() else {"day": date.today().isoformat(), "all": 0}

    def remaining(self, sandbox: str) -> int:
        usage = self._usage()
        return max(0, min(self.sandbox_limit - usage.get(sandbox, 0), self.daily_limit - usage["all"]))

    def _take(self, sandbox: str) -> None:
        with self._lock:
            usage = self._usage()
            if usage.get(sandbox, 0) >= self.sandbox_limit:
                raise DemoLimit(f"This demo reads {self.sandbox_limit} uploads per visitor per day. Try again tomorrow.")
            if usage["all"] >= self.daily_limit:
                raise DemoLimit("The demo reached today's upload limit. Try again tomorrow, or open a sample invoice.")
            usage[sandbox] = usage.get(sandbox, 0) + 1
            usage["all"] += 1
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / "usage.json").write_text(json.dumps(usage))

    # uploads

    def read_upload(self, sandbox: str, filename: str, data: bytes) -> int:
        """Check the file, spend one upload, read it, and return the new queue id."""
        if not data:
            raise DemoLimit("The file is empty.")
        if len(data) > MAX_BYTES:
            raise DemoLimit("The file is larger than 5 MB.")
        ext = next((e for magic, e in MAGIC.items() if data.startswith(magic)), None)
        if ext is None:
            raise DemoLimit("Upload a PDF, JPG or PNG.")
        if ext == ".pdf":
            from .pdf import page_count

            try:
                pages = page_count(data)
            except Exception:  # noqa: BLE001
                raise DemoLimit("That PDF could not be opened.") from None
            if pages > MAX_PAGES:
                raise DemoLimit(f"The demo reads documents of up to {MAX_PAGES} pages; this one has {pages}.")
        store = self.store(sandbox)
        import hashlib

        already = store.id_for(hashlib.sha256(data).hexdigest())
        if already is not None:  # the same file again: show it, do not spend an upload
            return already
        self._take(sandbox)
        stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in Path(filename or "upload").stem)[:60] or "upload"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / f"{stem}{ext}"
            path.write_bytes(data)
            reader = self.extractor or (lambda p: extract(p, model=os.environ.get("INVOICE_MODEL", "claude-haiku-5-5")))
            summary = process_folder(Path(tmp), store, reader, alert=lambda m: None, base_currency=BASES,
                                     sources={path.name: "uploaded in the demo"})
        return summary.ids[-1]


if __name__ == "__main__":
    if sys.argv[1:] == ["build-seed"]:
        print("\n".join(build_seed()))
    else:
        print(__doc__)
