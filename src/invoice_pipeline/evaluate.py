"""Score the extractor against the synthetic bank and write a report.

    python -m invoice_pipeline.evaluate --dry                  # $0: feeds the right answers, tests the plumbing
    python -m invoice_pipeline.evaluate --model claude-haiku-5-5
    python -m invoice_pipeline.evaluate --model claude-opus-5-5 --effort low --limit 10

Each document's API result is cached under runs/, so a second run of the same
model and effort costs nothing. --fresh ignores the cache. The number does not
replace reading: the report prints every failure in full.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .extract import DEFAULT_MODEL, PROMPT_VERSION, Extraction, extract
from .schema import HEADER_FIELDS, Invoice
from .validate import FLAGS, Ledger, check, norm_number

MONEY_FIELDS = {"subtotal", "tax", "total"}


def _norm_text(value: str | None) -> str | None:
    return None if value is None else re.sub(r"\s+", " ", value).strip().casefold()


def same(field_name: str, expected, got) -> bool:
    if field_name == "invoice_number":
        return norm_number(expected) == norm_number(got)
    if field_name in MONEY_FIELDS:
        return abs(float(expected) - float(got)) <= 0.01
    if field_name in ("vendor_name", "customer_name", "vendor_tax_id"):
        norm = lambda v: None if v is None else re.sub(r"[^a-z0-9]", "", v.casefold())  # noqa: E731
        return norm(expected) == norm(got)
    return _norm_text(expected) == _norm_text(got)


def same_lines(expected: Invoice, got: Invoice) -> bool:
    if len(expected.line_items) != len(got.line_items):
        return False
    for a, b in zip(expected.line_items, got.line_items):
        if _norm_text(a.description) != _norm_text(b.description):
            return False
        if any(abs(getattr(a, f) - getattr(b, f)) > 0.01 for f in ("quantity", "unit_price", "amount")):
            return False
    return True


@dataclass
class DocResult:
    file: str
    kind: str
    trap: str | None
    scanned: bool
    expected_flags: list[str]
    extraction: Extraction
    field_ok: dict[str, bool] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)

    @property
    def fields_all_ok(self) -> bool:
        return bool(self.field_ok) and all(self.field_ok.values())

    @property
    def flags_ok(self) -> bool:
        return sorted(self.flags) == sorted(self.expected_flags)


def _cache_path(runs: Path, bank: str, model: str, effort: str | None, file: str) -> Path:
    """One cache per bank, model, effort and prompt version: a result is never reused for a different question."""
    return runs / bank / f"{model}{'-' + effort if effort else ''}" / PROMPT_VERSION / (Path(file).stem + ".json")


def _load_cached(path: Path) -> Extraction | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text())
    inv = Invoice.model_validate(raw["invoice"]) if raw["invoice"] else None
    return Extraction(inv, raw["model"], raw["seconds"], raw["input_tokens"], raw["output_tokens"], raw["error"])


def _save_cached(path: Path, ex: Extraction) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"invoice": ex.invoice.model_dump() if ex.invoice else None, "model": ex.model,
                                "seconds": ex.seconds, "input_tokens": ex.input_tokens,
                                "output_tokens": ex.output_tokens, "error": ex.error}, indent=2) + "\n")


def run(samples: Path, model: str, effort: str | None, dry: bool, limit: int | None, fresh: bool,
        runs: Path = Path("runs")) -> list[DocResult]:
    manifest = json.loads((samples / "manifest.json").read_text())
    if limit:
        manifest = manifest[:limit]
    ledger = Ledger()
    results = []
    for doc in sorted(manifest, key=lambda d: d["received_order"]):
        truth = Invoice.model_validate(doc["truth"])
        if dry:
            ex = Extraction(truth.model_copy(deep=True), "dry-run", 0.0, 0, 0)
        else:
            cache = _cache_path(runs, samples.name, model, effort, doc["file"])
            ex = None if fresh else _load_cached(cache)
            if ex is None:
                ex = extract(samples / doc["file"], model=model, effort=effort)
                _save_cached(cache, ex)
            print(f"  {doc['file']}  {'ok ' if ex.invoice else 'ERR'}  {ex.seconds:5.1f} s  US$ {ex.cost_usd:.4f}")
        res = DocResult(doc["file"], doc["kind"], doc["trap"], doc["scanned"], doc["expected_flags"], ex)
        if ex.invoice is not None:
            got = ex.invoice
            res.field_ok = {f: same(f, getattr(truth, f), getattr(got, f)) for f in HEADER_FIELDS}
            res.field_ok["line_items"] = same_lines(truth, got)
            res.flags = check(got, doc.get("base_currency", "USD")) + ledger.check_and_add(got)
        results.append(res)
    return results


# ── Report ─────────────────────────────────────────────────────────────────


def _pct(n: int, d: int) -> str:
    return "–" if d == 0 else f"{100 * n / d:.1f} %"


def report(results: list[DocResult], samples: Path, model: str, effort: str | None, dry: bool) -> str:
    manifest = {d["file"]: d for d in json.loads((samples / "manifest.json").read_text())}
    n = len(results)
    read = [r for r in results if r.extraction.invoice is not None]
    fields = (*HEADER_FIELDS, "line_items")
    field_hits = Counter(f for r in read for f, ok in r.field_ok.items() if ok)
    total_fields = sum(len(r.field_ok) for r in read)
    cost = sum(r.extraction.cost_usd for r in results)
    secs = [r.extraction.seconds for r in read]

    traps = [r for r in results if r.kind == "trap"]
    caught = [r for r in traps if set(r.expected_flags) <= set(r.flags)]
    calm = [r for r in results if r.kind != "trap" and not r.expected_flags]
    false_alarms = [r for r in calm if r.flags]

    label = "dry run (right answers fed in; checks the plumbing, not the model)" if dry else model + (f", effort {effort}" if effort else "")
    out = [f"# Extraction report: {label}", ""]
    out += ["| | |", "|---|---|",
            f"| Documents | {n} ({', '.join(f'{c} {k}' for k, c in Counter(r.kind for r in results).items())}) |",
            f"| Read without error | {len(read)} / {n} |",
            f"| Fields correct | **{_pct(sum(field_hits.values()), total_fields)}** ({sum(field_hits.values())} / {total_fields}) |",
            f"| Documents with every field correct | {_pct(sum(r.fields_all_ok for r in read), n)} |",
            f"| Traps caught | **{len(caught)} / {len(traps)}** |",
            f"| False alarms on normal invoices | {len(false_alarms)} / {len(calm)} |",
            f"| Cost | US$ {cost:.4f} total, US$ {cost / max(n, 1):.4f} per document |",
            f"| Time per document | {sum(secs) / max(len(secs), 1):.1f} s average, {max(secs, default=0):.1f} s slowest |", ""]

    out += ["## By field", "", "| Field | Correct |", "|---|---|"]
    out += [f"| {f} | {_pct(field_hits[f], len(read))} |" for f in fields]
    out += ["", "## By kind of document", "", "| Kind | Documents | Every field correct |", "|---|---|---|"]
    for kind in sorted({r.kind for r in results}, key=lambda k: (k == "trap", k)):
        group = [r for r in read if r.kind == kind]
        out.append(f"| {kind} | {len(group)} | {_pct(sum(r.fields_all_ok for r in group), len(group))} |")
    out += ["", "## Traps", "", "| File | Trap | Expected | Raised |", "|---|---|---|---|"]
    out += [f"| {r.file} | {r.trap} | {', '.join(r.expected_flags)} | {', '.join(r.flags) or '—'} |" for r in traps]

    failures = [r for r in results if r.extraction.invoice is None or not r.fields_all_ok or not r.flags_ok]
    out += ["", f"## Failures, in full ({len(failures)})", ""]
    if not failures:
        out.append("None.")
    for r in failures:
        truth = manifest[r.file]["truth"]
        out += [f"### {r.file} · {r.kind}{' · scanned' if r.scanned else ''}{' · ' + r.trap if r.trap else ''}", ""]
        if r.extraction.invoice is None:
            out += [f"Not read: `{r.extraction.error}`", ""]
            continue
        got = r.extraction.invoice.model_dump()
        bad = [f for f, ok in r.field_ok.items() if not ok]
        if bad:
            out += ["| Field | Expected | Got |", "|---|---|---|"]
            for f in bad:
                exp, val = truth[f], got[f]
                if f == "line_items":
                    exp = "<br>".join(f"{li['quantity']:g} × {li['unit_price']:.2f} = {li['amount']:.2f} · {li['description']}" for li in exp)
                    val = "<br>".join(f"{li['quantity']:g} × {li['unit_price']:.2f} = {li['amount']:.2f} · {li['description']}" for li in val)
                out.append(f"| {f} | {exp} | {val} |")
            out.append("")
        if not r.flags_ok:
            out += [f"Flags expected: {', '.join(r.expected_flags) or 'none'} · raised: {', '.join(r.flags) or 'none'}",
                    *[f"- `{fl}`: {FLAGS[fl]}" for fl in r.flags], ""]
    return "\n".join(out) + "\n"


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=value lines from .env into the environment, without overriding what is already set."""
    import os

    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    load_dotenv()
    parser =argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--samples", type=Path, default=Path("samples"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--effort", choices=("low", "medium", "high", "xhigh", "max"))
    parser.add_argument("--dry", action="store_true", help="feed the right answers instead of calling the API ($0)")
    parser.add_argument("--limit", type=int, help="only the first N documents")
    parser.add_argument("--fresh", action="store_true", help="ignore cached API results")
    parser.add_argument("--out", type=Path, default=Path("reports"))
    args = parser.parse_args()

    results = run(args.samples, args.model, args.effort, args.dry, args.limit, args.fresh)
    text = report(results, args.samples, args.model, args.effort, args.dry)
    args.out.mkdir(parents=True, exist_ok=True)
    bank = args.samples.name
    name = f"EVAL_{bank}_dry.md" if args.dry else f"EVAL_{bank}_{args.model}{'_' + args.effort if args.effort else ''}.md"
    (args.out / name).write_text(text)
    print("\n".join(text.splitlines()[2:12]))
    print(f"\nReport: {args.out / name}")


if __name__ == "__main__":
    main()
