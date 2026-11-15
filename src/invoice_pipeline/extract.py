"""Read one invoice (PDF, or a photo as JPG/PNG) with Claude and return it in the Invoice schema.

The PDF goes to the API as a document block (text layer and page image), so
the same call handles digital and scanned invoices. Structured outputs
guarantee the reply parses into `Invoice`; the rules in validate.py do the
judging afterwards.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .schema import Invoice

# Chosen by the evaluation (see README): Haiku matched Opus on all 100 test documents at ~1/30 of the cost.
FALLBACK_MODEL = "claude-haiku-5-5"


def default_model() -> str:
    """Read at call time, not import time, so a .env loaded later still counts."""
    return os.environ.get("INVOICE_MODEL", FALLBACK_MODEL)

# US$ per million tokens (input, output). Source: Anthropic pricing, Nov 2026.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

SYSTEM = """You extract data from vendor invoices for an accounts-payable team.

Copy every value exactly as printed on the document. Never fix arithmetic:
if a line amount, subtotal or total looks wrong, still return the printed
number. Downstream checks depend on seeing the document's own numbers.

Dates: return YYYY-MM-DD. Read each date with the convention the document
uses (a label such as "DD/MM/YYYY", the vendor's country, the month name).
If no explicit due date is printed (e.g. "due on receipt"), return null.

Amounts: plain numbers, no currency symbols or thousands separators. A
European amount such as "1.234,50 €" is 1234.50 with currency EUR."""

# Short fingerprint of the instructions and the schema: cached results are only reused for the same prompt.
PROMPT_VERSION = hashlib.sha256(
    (SYSTEM + json.dumps(Invoice.model_json_schema(), sort_keys=True)).encode()).hexdigest()[:8]

MEDIA_TYPES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


@dataclass
class Extraction:
    invoice: Invoice | None
    model: str
    seconds: float
    input_tokens: int
    output_tokens: int
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICES.get(self.model, (0.0, 0.0))
        return (self.input_tokens * price_in + self.output_tokens * price_out) / 1_000_000


def extract(pdf: Path, client: anthropic.Anthropic | None = None, model: str | None = None,
            effort: str | None = None) -> Extraction:
    model = model or default_model()
    try:
        client = client or anthropic.Anthropic()
    except anthropic.AnthropicError as exc:  # e.g. no API key configured: report it, never crash the caller
        return Extraction(None, model, 0.0, 0, 0, f"configuration: {exc}")
    data = base64.standard_b64encode(pdf.read_bytes()).decode("ascii")
    media_type = MEDIA_TYPES[pdf.suffix.lower()]
    block_type = "document" if media_type == "application/pdf" else "image"
    started = time.perf_counter()
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": [
                    {"type": block_type, "source": {"type": "base64", "media_type": media_type, "data": data}},
                    {"type": "text", "text": "Extract this invoice."},
                ],
            }],
            output_format=Invoice,
            **({"output_config": {"effort": effort}} if effort else {}),
        )
    except anthropic.APIStatusError as exc:  # SDK already retried 429 and 5xx
        return Extraction(None, model, time.perf_counter() - started, 0, 0, f"{exc.status_code}: {exc.message}")
    except anthropic.APIConnectionError as exc:
        return Extraction(None, model, time.perf_counter() - started, 0, 0, f"connection: {exc}")
    except TypeError as exc:  # SDK 2.x raises this when no API key is configured
        if "authentication" not in str(exc).lower():
            raise
        return Extraction(None, model, 0.0, 0, 0, "configuration: no Anthropic API key is set")

    seconds = time.perf_counter() - started
    usage = response.usage
    if response.stop_reason in ("refusal", "max_tokens") or response.parsed_output is None:
        return Extraction(None, model, seconds, usage.input_tokens, usage.output_tokens,
                          f"stop_reason={response.stop_reason}")
    return Extraction(response.parsed_output, model, seconds, usage.input_tokens, usage.output_tokens)
