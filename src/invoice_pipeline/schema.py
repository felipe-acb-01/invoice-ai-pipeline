"""The shape of an invoice, shared by the generator, the extractor and the evaluation.

The model is asked to fill exactly this schema (structured outputs), and the
ground truth of every synthetic invoice is stored in the same shape, so the
evaluation compares like with like.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = Field(description="Line description, as printed.")
    quantity: float = Field(description="Quantity or hours, as printed.")
    unit_price: float = Field(description="Unit price, as printed, without currency symbol.")
    amount: float = Field(description="Line amount, as printed. Do not recompute it.")


class Invoice(BaseModel):
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
