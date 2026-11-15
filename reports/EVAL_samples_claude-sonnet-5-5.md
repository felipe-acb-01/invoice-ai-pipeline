# Extraction report: claude-sonnet-5-5

| | |
|---|---|
| Documents | 60 (40 clean, 15 scanned, 5 traps) |
| Read without error | 60 / 60 |
| Fields correct | **100.0 %** (660 / 660) |
| Documents with every field correct | 100.0 % |
| Traps caught | **5 / 5** |
| False alarms on normal invoices | 0 / 55 |
| Cost | US$ 0.5272 total, US$ 0.0088 per document |
| Time per document | 2.6 s average, 3.0 s slowest |

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

## By kind of document

| Kind | Documents | Every field correct |
|---|---|---|
| clean | 40 | 100.0 % |
| scanned | 15 | 100.0 % |
| trap | 5 | 100.0 % |

## Traps

| File | Trap | Expected | Raised |
|---|---|---|---|
| 007.pdf | line amount wrong | line_math | line_math |
| 011.pdf | billed in EUR | foreign_currency | foreign_currency |
| 016.pdf | same charge, new number | possible_duplicate | possible_duplicate |
| 039.pdf | re-sent as a scan | duplicate | duplicate |
| 044.pdf | total off by 100 | total_mismatch | total_mismatch |

## Failures, in full (0)

None.
