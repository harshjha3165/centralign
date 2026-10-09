# Run report

**Task:** Find the latest Northwind invoice, enter the amount due and due date into Ledger, and tell me when you're done.

**Status:** success
**Confidence:** Medium (75/100)
**Steps:** 14 **Wall time:** 169.4s **Approx. cost:** $0.0043

## Definition of done
- [ ] Identify the latest Northwind invoice. (not checked by the verifier)
- [ ] Extract the amount due and due date from that invoice. (not checked by the verifier)
- [ ] Enter the amount and date into the Ledger system. (not checked by the verifier)

## Fields
| Field | Value | Source | Confidence | Why |
|---|---|---|---|---|
| latest_northwind_invoice_amount_due | 124500.00 | invoices/northwind_2031.pdf | 100 | 100: read verbatim, label matched exactly |
| latest_northwind_invoice_due_date | 2026-10-18 | invoices/northwind_2031.pdf | 75 | cap 75: computed, not read verbatim |

## Verifier
Pass: True
Problems: []

## DB diff
`bills`: 1 row(s) added, 0 changed, 0 deleted.

## Doubt list
- `latest_northwind_invoice_due_date` was computed, not read verbatim.
- Assumptions stated: The latest Northwind invoice was identified as northwind_2031.pdf, with an amount due of $124,500.00 and a due date of 2026-10-18 (30 days after the 2026-09-18 invoice date). These details were successfully entered into the Ledger system.

## Assumptions
The latest Northwind invoice was identified as northwind_2031.pdf, with an amount due of $124,500.00 and a due date of 2026-10-18 (30 days after the 2026-09-18 invoice date). These details were successfully entered into the Ledger system.

## User interactions
(none)

## Receipts
- Full trace: `trace.jsonl`
- Notebook: `notebook.json`
- Replay: [replay.html](replay.html)
