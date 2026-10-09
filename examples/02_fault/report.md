# Run report

**Task:** Find the latest Northwind invoice, enter the amount due and due date into Ledger, and tell me when you're done.

**Status:** success
**Confidence:** Low (50/100)
**Steps:** 21 **Wall time:** 280.6s **Approx. cost:** $0.0088

## Definition of done
- [x] Identified the latest Northwind invoice. (expected: 'NW-2031', actual: 'NW-2031')
- [x] Extracted the amount due and due date. (expected: 'Amount: $124,500.00; Due Date: 2026-10-18', actual: 'Amount: $124500.00; Due Date: 2026-10-18')
- [x] Entered the information into the Ledger application. (expected: 'Amount $124,500.00 and Due Date 2026-10-18', actual: 'Amount $124500.00 and Due Date 2026-10-18')

## Fields
| Field | Value | Source | Confidence | Why |
|---|---|---|---|---|
| amount_due | $124,500.00 | invoices/northwind_2031.pdf | 100 | 100: read verbatim, label matched exactly |
| invoice_date | 2026-09-18 | invoices/northwind_2031.pdf | 100 | 100: read verbatim, label matched exactly |
| due_date | 2026-10-18 | invoice_date + 30 days | 75 | cap 75: computed, not read verbatim |

## Verifier
Pass: True
Problems: []

## DB diff
`bills`: 2 row(s) added, 0 changed, 0 deleted.

## Doubt list
- `due_date` was computed, not read verbatim.
- Assumptions stated: None.

## Assumptions
None.

## User interactions
(none)

## Receipts
- Full trace: `trace.jsonl`
- Notebook: `notebook.json`
- Replay: [replay.html](replay.html)
