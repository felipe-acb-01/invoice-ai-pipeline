# Invoice AI pipeline

Vendor invoices arrive by email as PDFs, some of them scanned. This pipeline reads each one with Claude,
checks it with plain rules (do the lines add up? was it already paid? is it in another currency?), sends
anything doubtful to a person for approval, and writes the rest to a spreadsheet.

> **Status: work in progress.** Done: two test banks (100 documents), extraction from PDFs and photos, the rules,
> the evaluation, the approval queue and the Excel export. Next: Gmail in, Google Sheets out, alerts by email, a live demo.

## How it works

1. `python -m invoice_pipeline process --inbox inbox/` reads every new PDF or photo (a file already seen is skipped),
   checks it, and puts it in the approval queue. Unreadable files go to their own tab and raise an alert.
2. `python -m invoice_pipeline serve` opens the approval screen: every invoice next to its original document, with
   the reason for any alert in one sentence and a link to the earlier invoice it may repeat.
3. Approved invoices export to Excel (one sheet of invoices, one of lines), with who approved them, when, and their note.

Settings: `ANTHROPIC_API_KEY`, `INVOICE_MODEL` (default `claude-opus-5-5`; the evaluation recommends
`claude-haiku-5-5`), `BASE_CURRENCIES` (e.g. `USD,CLP`), `APPROVER_NAME`, `INVOICE_DATA_DIR`.

## How well it reads: measured, not claimed

`samples/` holds 60 synthetic invoices with the right answer for each:

| | |
|---|---|
| Clean PDFs | 40, in three layouts and three date conventions |
| Scanned | 15: skewed, noisy, no text layer |
| Traps | 5: a re-sent invoice, the same charge under a new number, a total off by 100, a line that does not multiply out, an invoice in euros |

`python -m invoice_pipeline.evaluate` scores every field, checks that each trap is caught and that normal
invoices raise nothing, and reports cost and time per document. Every failure is printed in full.

### Results (November 2026)

| Bank | Model | Fields correct | Traps caught | False alarms | Cost per invoice | Time per invoice |
|---|---|---|---|---|---|---|
| Standard (60) | Claude Haiku 5.5 | 660 / 660 | 5 / 5 | 0 / 55 | US$ 0.0005 | 2.2 s |
| Standard (60) | Claude Sonnet 5.5 | 660 / 660 | 5 / 5 | 0 / 55 | US$ 0.0088 | 2.6 s |
| Standard (60) | Claude Opus 5.5 | 660 / 660 | 5 / 5 | 0 / 55 | US$ 0.0177 | 3.0 s |
| Hard (40) | Claude Haiku 5.5 | 440 / 440 | 4 / 4 | 0 / 36 | US$ 0.0007 | 3.5 s |
| Hard (40) | Claude Opus 5.5 | 440 / 440 | 4 / 4 | 0 / 36 | US$ 0.0230 | 4.2 s |

The hard bank (`samples_hard/`, `python -m invoice_pipeline.synth_hard`) adds Chilean electronic invoices
(RUT, folio, IVA 19 %, Spanish dates), phone photos as JPG, two-page invoices, discounts and split taxes,
unlabeled dates such as 08/12/2026 that only the address and payment terms settle, wrapped descriptions,
and four more traps (an invoice photographed twice, the same charge under a new folio, IVA off by $1.000,
a subtotal that skips the last line on page 2).

**Decision: Claude Haiku 5.5.** On these 100 documents it matched Opus field for field at about 1/30 of
the cost, roughly US$ 0.50–0.70 per thousand invoices. Re-run the comparison on a sample of each client's
real invoices before relying on it.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m invoice_pipeline.synth              # rebuild the 60 samples (deterministic)
.venv/bin/python -m invoice_pipeline.evaluate --dry     # $0: checks the plumbing with the right answers
ANTHROPIC_API_KEY=... .venv/bin/python -m invoice_pipeline.evaluate --model claude-haiku-5-5
.venv/bin/python -m pytest
```

## Design choices

- **The model reads, rules judge.** Claude returns the printed values in a fixed schema (structured outputs)
  and is told never to fix the arithmetic. Every check is a plain rule an accountant can read.
- **One call for digital and scanned PDFs.** The PDF goes to the API as a document.
- **Model choice comes from the report.** The same bank runs against each model, so accuracy and cost per
  invoice can be compared directly.

## Limitations

- Tested on invoices in English, Portuguese and Spanish (Chile); US, European and Chilean number formats; up to two pages.
- The samples are synthetic. Real invoices are messier, so the first week with a client's documents
  should re-run the evaluation on a sample of theirs.

All vendors, customers and numbers in `samples/` are invented. Each PDF says so in its footer.
