"""Approved invoices as an Excel workbook: one sheet of invoices, one of lines."""

from __future__ import annotations

import io

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

from .store import Store

INVOICE_COLUMNS = ("ID", "Vendor", "Vendor tax ID", "Invoice number", "Issue date", "Due date", "Currency",
                   "Subtotal", "Tax", "Total", "Approved at (UTC)", "Approved by", "Note", "Source file")
LINE_COLUMNS = ("Invoice ID", "Vendor", "Invoice number", "Description", "Quantity", "Unit price", "Amount")


def approved_workbook(store: Store) -> bytes:
    wb = Workbook()
    inv_ws = wb.active
    inv_ws.title = "Invoices"
    line_ws = wb.create_sheet("Lines")
    inv_ws.append(INVOICE_COLUMNS)
    line_ws.append(LINE_COLUMNS)

    for rec in store.list("approved"):
        inv = rec.invoice
        inv_ws.append((rec.id, inv.vendor_name, inv.vendor_tax_id, inv.invoice_number, inv.issue_date,
                       inv.due_date, inv.currency, inv.subtotal, inv.tax, inv.total, rec.decided_at,
                       rec.decided_by, rec.note, rec.file_name))
        for li in inv.line_items:
            line_ws.append((rec.id, inv.vendor_name, inv.invoice_number, li.description, li.quantity,
                            li.unit_price, li.amount))

    for ws in (inv_ws, line_ws):
        for row in ws.iter_rows(min_row=2):
            for cell in row:  # text read from a document is data: "=HYPERLINK(...)" must never become a formula
                if cell.data_type == "f":
                    cell.data_type = "s"
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for i, column in enumerate(ws.columns, start=1):
            width = max(len(str(c.value or "")) for c in column)
            ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 60)
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
