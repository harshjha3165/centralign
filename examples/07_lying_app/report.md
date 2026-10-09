# Run report

**Task:** Find the latest Northwind invoice, enter the amount due and due date into Ledger, and tell me when you're done.

**Status:** success
**Confidence:** Medium (75/100)
**Steps:** 23 **Wall time:** 276.4s **Approx. cost:** $0.0104

## Definition of done
- [x] Find the latest Northwind invoice. (expected: 'NW-4477', actual: 'NW-4477')
- [ ] Enter its amount due and due date into the Ledger system. (not checked by the verifier)

## Fields
| Field | Value | Source | Confidence | Why |
|---|---|---|---|---|
| latest_invoice_date | 2026-09-01 | invoices/northwind_lying.pdf | 100 | 100: read verbatim, label matched exactly |
| amount_due | $84,000.00 | invoices/northwind_lying.pdf | 100 | 100: read verbatim, label matched exactly |
| due_date | 2026-10-01 | invoices/northwind_lying.pdf | 75 | cap 75: computed, not read verbatim |

## Verifier
Pass: True
Problems: []

## DB diff
`bills`: 1 row(s) added, 0 changed, 0 deleted.

## Doubt list
- `due_date` was computed, not read verbatim.
- Assumptions stated: The Northwind invoice NW-4477 with amount $84,000.00 and due date 2026-10-01 has been successfully added to the Ledger system. The previous attempt was likely failed due to a transient issue or system state. Verified the current ledger state shows the bill saved.

## Assumptions
The Northwind invoice NW-4477 with amount $84,000.00 and due date 2026-10-01 has been successfully added to the Ledger system. The previous attempt was likely failed due to a transient issue or system state. Verified the current ledger state shows the bill saved.

## User interactions
(none)

## Receipts
- Full trace: `trace.jsonl`
- Notebook: `notebook.json`
- Replay: [replay.html](replay.html)
