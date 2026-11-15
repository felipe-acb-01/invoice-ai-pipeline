# Extraction report: claude-haiku-5-5

| | |
|---|---|
| Documents | 44 (5 two_page, 4 ambiguous, 5 discount, 4 not_invoice, 8 photo, 5 wrapped, 9 chile, 4 trap) |
| Read without error | 44 / 44 |
| Fields correct | **100.0 %** (484 / 484) |
| Documents with every field correct | 100.0 % |
| Traps caught | **4 / 4** |
| False alarms on normal invoices | 0 / 36 |
| Cost | US$ 0.0317 total, US$ 0.0007 per document |
| Time per document | 3.9 s average, 18.7 s slowest |

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
| total | 100.0 % |
| line_items | 100.0 % |
| is_invoice | 100.0 % |

## By kind of document

| Kind | Documents | Every field correct |
|---|---|---|
| ambiguous | 4 | 100.0 % |
| chile | 9 | 100.0 % |
| discount | 5 | 100.0 % |
| not_invoice | 4 | 100.0 % |
| photo | 8 | 100.0 % |
| two_page | 5 | 100.0 % |
| wrapped | 5 | 100.0 % |
| trap | 4 | 100.0 % |

## Traps

| File | Trap | Expected | Raised |
|---|---|---|---|
| 018.jpg | Chilean invoice photographed again | duplicate | duplicate |
| 023.pdf | same Chilean charge, new folio | possible_duplicate | possible_duplicate |
| 039.pdf | IVA off by $1.000 | iva_mismatch | iva_mismatch |
| 042.pdf | subtotal skips the last line on page 2 | subtotal_mismatch | subtotal_mismatch |

## Failures, in full (0)

None.
