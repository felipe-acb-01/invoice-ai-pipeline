import json

import pytest

from invoice_pipeline.evaluate import report, run, same
from invoice_pipeline.schema import Invoice, LineItem
from invoice_pipeline.synth import generate
from invoice_pipeline.validate import Ledger, check


def make(**overrides) -> Invoice:
    base = dict(invoice_number="INV-1", vendor_name="Acme Ltd", vendor_tax_id="00-1", customer_name="Brightline",
                issue_date="2026-09-01", due_date="2026-10-01", currency="USD",
                line_items=[LineItem(description="Work", quantity=2, unit_price=50, amount=100)],
                subtotal=100, tax=0, total=100)
    return Invoice(**{**base, **overrides})


def test_clean_invoice_raises_nothing():
    assert check(make()) == []


@pytest.mark.parametrize("overrides, flag", [
    ({"line_items": [LineItem(description="Work", quantity=2, unit_price=50, amount=140)], "subtotal": 140, "total": 140}, "line_math"),
    ({"subtotal": 90, "total": 90}, "subtotal_mismatch"),
    ({"total": 200}, "total_mismatch"),
    ({"due_date": "2026-08-01"}, "date_order"),
    ({"issue_date": "01/09/2026"}, "bad_date"),
    ({"currency": "EUR"}, "foreign_currency"),
])
def test_each_rule_raises_only_its_flag(overrides, flag):
    assert check(make(**overrides)) == [flag]


def test_ledger_catches_resent_and_renumbered_invoices():
    ledger = Ledger()
    assert ledger.check_and_add(make()) == []
    assert ledger.check_and_add(make(invoice_number="inv 1", vendor_name="ACME LTD.")) == ["duplicate"]
    assert ledger.check_and_add(make(invoice_number="INV-2")) == ["possible_duplicate"]
    assert ledger.check_and_add(make(invoice_number="INV-3", total=101, subtotal=101,
                                     line_items=[LineItem(description="W", quantity=1, unit_price=101, amount=101)])) == []


def test_money_and_names_compare_loosely_dates_strictly():
    assert same("total", 100.0, 100.004)
    assert not same("total", 100.0, 100.02)
    assert same("vendor_name", "Northwind Cleaning Co.", "NORTHWIND CLEANING CO")
    assert not same("issue_date", "2026-11-03", "2026-03-11")


@pytest.fixture(scope="module")
def bank(tmp_path_factory):
    out = tmp_path_factory.mktemp("samples")
    generate(out)
    return out


def test_bank_has_the_promised_mix(bank):
    manifest = json.loads((bank / "manifest.json").read_text())
    kinds = [d["kind"] for d in manifest]
    assert (kinds.count("clean"), kinds.count("scanned"), kinds.count("trap")) == (40, 15, 5)
    assert all((bank / d["file"]).stat().st_size > 1000 for d in manifest)


def test_bank_is_deterministic(bank, tmp_path):
    generate(tmp_path)
    assert (tmp_path / "manifest.json").read_text() == (bank / "manifest.json").read_text()


def test_with_perfect_reading_every_trap_and_nothing_else_is_flagged(bank):
    """The dry run feeds the right answers: any miss here is a bug in the rules or the bank, not the model."""
    results = run(bank, "dry", None, dry=True, limit=None, fresh=False)
    assert all(r.fields_all_ok for r in results)
    wrong = [(r.file, r.trap, r.expected_flags, r.flags) for r in results if not r.flags_ok]
    assert wrong == []
    assert "Traps caught | **5 / 5**" in report(results, bank, "dry", None, dry=True)


# ── Hard bank ──────────────────────────────────────────────────────────────

from invoice_pipeline.synth_hard import generate as generate_hard, in_words, rut  # noqa: E402
from invoice_pipeline.validate import norm_number  # noqa: E402


def test_rut_check_digit():
    assert rut(76_086_428) == "76.086.428-5"
    assert rut(11_111_111) == "11.111.111-1"


def test_amount_in_words():
    assert in_words(1450.0) == "One thousand four hundred fifty and 00/100 US dollars"
    assert in_words(219.5) == "Two hundred nineteen and 50/100 US dollars"


def test_chilean_iva_rule():
    neto = make(currency="CLP", line_items=[LineItem(description="x", quantity=1, unit_price=100000, amount=100000)],
                subtotal=100000, tax=19000, total=119000)
    assert check(neto, "CLP") == []
    assert check(neto.model_copy(update=dict(tax=20000, total=120000)), "CLP") == ["iva_mismatch"]


def test_invoice_numbers_compare_without_labels():
    assert norm_number("N° 1234") == norm_number("1234") == norm_number("#1234") == norm_number("No. 1234")
    assert norm_number("INV-2026-0412") == norm_number("INV 2026 0412")
    assert norm_number("1234") != norm_number("1243")


@pytest.fixture(scope="module")
def hard_bank(tmp_path_factory):
    out = tmp_path_factory.mktemp("samples_hard")
    generate_hard(out)
    return out


def test_hard_bank_mix_and_files(hard_bank):
    manifest = json.loads((hard_bank / "manifest.json").read_text())
    assert len(manifest) == 44
    assert sum(d['kind'] == 'not_invoice' for d in manifest) == 4
    assert sum(d["kind"] == "trap" for d in manifest) == 4
    assert all((hard_bank / d["file"]).exists() for d in manifest)
    assert any(d["file"].endswith(".jpg") for d in manifest)


def test_hard_bank_with_perfect_reading_flags_exactly_the_traps(hard_bank):
    results = run(hard_bank, "dry", None, dry=True, limit=None, fresh=False)
    wrong = [(r.file, r.trap, r.expected_flags, r.flags) for r in results if not r.flags_ok]
    assert wrong == []


def test_cache_is_separate_per_bank(tmp_path):
    from invoice_pipeline.evaluate import _cache_path
    a = _cache_path(tmp_path, "samples", "m", None, "001.pdf")
    b = _cache_path(tmp_path, "samples_hard", "m", None, "001.pdf")
    assert a != b


def test_model_setting_is_read_when_used_not_when_imported(monkeypatch):
    """Regression: a .env loaded after import used to be ignored, so a run billed Opus instead of Haiku."""
    from invoice_pipeline.extract import default_model
    monkeypatch.delenv("INVOICE_MODEL", raising=False)
    assert default_model() == "claude-haiku-5-5"
    monkeypatch.setenv("INVOICE_MODEL", "claude-sonnet-5-5")
    assert default_model() == "claude-sonnet-5-5"


def test_is_invoice_is_required_for_the_model_and_changes_the_cache_version():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter
    assert "is_invoice" in transform_schema(TypeAdapter(Invoice).json_schema())["required"]
    assert Invoice.model_validate({**make().model_dump(), "is_invoice": True}).is_invoice


def test_a_document_that_is_not_an_invoice_goes_to_errors(tmp_path):
    from invoice_pipeline.extract import Extraction
    from invoice_pipeline.pipeline import process_folder
    from invoice_pipeline.store import Store
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "cat.jpg").write_bytes(b"\xff\xd8 not really a cat")
    store = Store(tmp_path / "data")
    alerts = []
    s = process_folder(inbox, store, lambda p: Extraction(make(is_invoice=False), "fake", 0, 0, 0), alert=alerts.append)
    rec = store.list()[0]
    assert (rec.status, rec.error, s.not_invoices, alerts) == ("error", "This does not look like an invoice.", 1, [])


def test_missing_api_key_is_reported_not_raised(monkeypatch, tmp_path):
    """Regression: without ANTHROPIC_API_KEY the client constructor raised and the demo returned a 500."""
    from invoice_pipeline.extract import extract
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no CLI profile on disk either
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    ex = extract(pdf)
    assert ex.invoice is None and ex.error.startswith("configuration:")
