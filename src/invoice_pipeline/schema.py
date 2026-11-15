"""The shape of an invoice, shared by the generator, the extractor and the evaluation.

The model is asked to fill exactly this schema (structured outputs), and the
ground truth of every synthetic invoice is stored in the same shape, so the
evaluation compares like with like.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class LineItem(BaseModel):
    description: str = Field(description="Line description, as printed.")
    quantity: float = Field(description="Quantity or hours, as printed.")
    unit_price: float = Field(description="Unit price, as printed, without currency symbol.")
    amount: float = Field(description="Line amount, as printed. Do not recompute it.")


def _require_is_invoice(schema: dict) -> None:
    # Defaults to True so older ground-truth files still load, but the model must always answer it.
    if "is_invoice" not in schema.setdefault("required", []):
        schema["required"].insert(0, "is_invoice")


class Invoice(BaseModel):
    model_config = ConfigDict(json_schema_extra=_require_is_invoice)

    is_invoice: bool = Field(default=True, description=(
        "True only for a vendor invoice or tax invoice (factura) asking to be paid. False for anything else: a quote, "
        "a receipt already paid, a contract, a delivery note, a photo of something else. When false, fill the other "
        "fields with empty strings, 0 and empty lists."))
    invoice_number: str = Field(description="Invoice number exactly as printed, including prefixes like 'INV-' or '#'.")
    vendor_name: str = Field(description="Legal name of the company that issued the invoice.")
    vendor_tax_id: str | None = Field(description="Vendor tax ID (EIN, VAT number) as printed, or null if absent.")
    customer_name: str = Field(description="Name of the billed customer.")
    issue_date: str = Field(description="Issue date as YYYY-MM-DD, read with the document's own date convention.")
    due_date: str | None = Field(description="Due date as YYYY-MM-DD, or null when no explicit due date is printed.")
    currency: str = Field(description="ISO 4217 code, e.g. USD or EUR.")
    line_items: list[LineItem]
    subtotal: float = Field(description="Subtotal as printed. Do not recompute it.")
    tax: float = Field(description="Total tax as printed; 0 if none.")
    total: float = Field(description="Total amount due as printed. Do not recompute it.")


# Fields the evaluation scores one by one (line items are scored as a block).
HEADER_FIELDS = (
    "invoice_number",
    "vendor_name",
    "vendor_tax_id",
    "customer_name",
    "issue_date",
    "due_date",
    "currency",
    "subtotal",
    "tax",
    "total",
)
