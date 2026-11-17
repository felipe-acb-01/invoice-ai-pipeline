# Extraction report: claude-haiku-5-5

| | |
|---|---|
| Documents | 4 (3 chile_tax, 1 trap) |
| Read without error | 4 / 4 |
| Fields correct | **100.0 %** (56 / 56) |
| Documents with every field correct | 100.0 % |
| Traps caught | **1 / 1** |
| False alarms on normal invoices | 0 / 3 |
| Cost | US$ 0.0029 total, US$ 0.0007 per document |
| Time per document | 4.0 s average, 6.1 s slowest |

## By field

| Field | Correct |
|---|---|
| invoice_number | 100.0 % |
| vendor_name | 100.0 % |
| vendor_tax_id | 100.0 % |
| customer_name | 100.0 % |
| issue_date | 100.0 % |
| due_date | 100.0 % |
| currency | 100.0 % |
| subtotal | 100.0 % |
| tax | 100.0 % |
| exempt_amount | 100.0 % |
| other_taxes | 100.0 % |
| total | 100.0 % |
| line_items | 100.0 % |
| is_invoice | 100.0 % |

## By kind of document

| Kind | Documents | Every field correct |
|---|---|---|
| chile_tax | 3 | 100.0 % |
| trap | 1 | 100.0 % |

## Traps

| File | Trap | Expected | Raised |
|---|---|---|---|
| 004.pdf | IVA taken over net + ILA | iva_mismatch | iva_mismatch |

## Failures, in full (0)

None.
