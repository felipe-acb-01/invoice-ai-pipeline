"""Deterministic checks on an extracted invoice.

The model reads; rules decide. Nothing here calls an LLM: every flag can be
explained to an accountant in one sentence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .schema import Invoice

TOLERANCE = 0.01

# Flag codes, with the sentence an approver reads.
FLAGS = {
    "line_math": "A line's quantity × unit price does not match its amount.",
    "subtotal_mismatch": "The lines do not add up to the subtotal.",
    "total_mismatch": "Subtotal plus tax does not equal the total.",
    "date_order": "The due date is before the issue date.",
    "bad_date": "A date could not be read as YYYY-MM-DD.",
    "foreign_currency": "The invoice is not in the base currency.",
    "duplicate": "This vendor already sent an invoice with this number.",
    "possible_duplicate": "Same vendor, date and total as an earlier invoice, with a different number.",
    "iva_mismatch": "Chilean IVA is not 19 % of the net amount.",
}

CHILE_IVA = 0.19


def _norm(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def norm_number(text: str | None) -> str:
    """Invoice numbers compared without labels (Invoice, Factura, Folio, N°, No., #), spaces or punctuation."""
    text = re.sub(r"^\s*(invoice|factura|folio)\b[\s:]*", "", (text or "").lower())  # the label the model may copy
    stripped = re.sub(r"^\s*(n\s*[°º]|no\.|number|#)\s*", "", text)
    return _norm(stripped)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    return date.fromisoformat(value)


def check(invoice: Invoice, base_currency: str | tuple[str, ...] = "USD") -> list[str]:
    """Flags that only need this one invoice. `base_currency` is the currency, or currencies, the company books in."""
    bases = {base_currency} if isinstance(base_currency, str) else set(base_currency)
    flags: list[str] = []

    if any(abs(li.quantity * li.unit_price - li.amount) > TOLERANCE for li in invoice.line_items):
        flags.append("line_math")
    # Exempt lines are part of the lines but not of the net (Chile: Monto exento); both are 0 everywhere else.
    if abs(sum(li.amount for li in invoice.line_items) - (invoice.subtotal + invoice.exempt_amount)) > TOLERANCE:
        flags.append("subtotal_mismatch")
    if abs(invoice.subtotal + invoice.exempt_amount + invoice.tax + invoice.other_taxes - invoice.total) > TOLERANCE:
        flags.append("total_mismatch")

    try:
        issued, due = _parse_date(invoice.issue_date), _parse_date(invoice.due_date)
    except ValueError:
        flags.append("bad_date")
    else:
        if issued and due and due < issued:
            flags.append("date_order")

    # IVA is 19 % of the net only: an exempt amount and additional taxes (ILA) sit outside it.
    if invoice.currency.upper() == "CLP" and abs(round(invoice.subtotal * CHILE_IVA) - invoice.tax) > 1:
        flags.append("iva_mismatch")

    if invoice.currency.upper() not in bases:
        flags.append("foreign_currency")
    return flags


@dataclass
class Ledger:
    """What has already been received, to catch duplicates across invoices."""

    by_number: set[tuple[str, str]] = field(default_factory=set)
    by_amount: dict[tuple[str, str, float], str] = field(default_factory=dict)

    def check_and_add(self, invoice: Invoice) -> list[str]:
        vendor = _norm(invoice.vendor_name)
        number = norm_number(invoice.invoice_number)
        amount_key = (vendor, invoice.issue_date, round(invoice.total, 2))

        flags: list[str] = []
        if (vendor, number) in self.by_number:
            flags.append("duplicate")
        elif amount_key in self.by_amount and self.by_amount[amount_key] != number:
            flags.append("possible_duplicate")

        self.by_number.add((vendor, number))
        self.by_amount.setdefault(amount_key, number)
        return flags
