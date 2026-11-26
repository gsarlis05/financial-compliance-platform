# ADR-0069: Reading an accountant's trial balance and accounting-package exports
Status: **Accepted** (R-3, #246; brief 26) · Date: 2026-11-26 · Extends ADR-0068

## Context
Existing books often arrive in one of two forms:
- an accountant's year-end trial balance, as delivered;
- report exports from an accounting package: a trial balance, aged receivables and payables, and
  the chart of accounts.

The developer has not seen any package's real export. A layout coded per package would be a
guess presented as fact.

## Decision
- **Same reader and the same check-then-import flow as R-2.** More header names are recognised.
  They are data in `templates.json`, for example:
  - "Debit - Year to date", "Closing balance";
  - "Contact", "Vendor", "Num", "Amount due", "Open balance";
  - "*Code" and "*Type".

  Account types are recognised as packages write them ("Current Asset", "Accounts Receivable",
  "Credit Card", "Revenue", "Overhead", and the Greek names). "Accounts Receivable" and "Accounts
  Payable" also make the account a control account.
- **A trial balance as delivered:**
  - Section headings and accounts with no balance are skipped.
  - Subtotal and total rows (starting with Total, Grand total or Σύνολο) are skipped. The file's
    last total is checked against its lines, and a difference is a problem.
  - Amounts may carry Dr or Cr.
  - The account may be written as "1200 Trade receivables", or by its name alone when one chart
    account has that name.
  - An account that cannot be identified goes to the mapping step, keyed by its code or name.
- **The year's result.** An accountant's year-end trial balance still shows income and expense.
  The import can carry them into a chosen equity account, normally retained earnings, so the
  opening entry holds balance-sheet accounts only. Without that choice they are kept, with a
  warning.
- **Aged receivables and payables reports** stand in for the open-invoices template:
  - Each row names the customer or supplier, by code or by name.
  - The account is the entity's only receivables or payables account, unless the report has an
    account column. If the chart has several and no column says which, the report is refused.
  - Subtotal rows and zero rows are skipped.
  - A row without an invoice number becomes "Opening balance" for that customer or supplier.
  - Customers and suppliers the report names but that are not set up are listed. On request they
    are created with the import, as customers from the receivables report and suppliers from the
    payables report, with codes derived from their names.
- **Date order.** Dates are read day first unless the screen says month first. Year-first dates
  and dates with the month in words read the same either way. A date that only fits the other
  order is refused with a message saying so, never silently swapped.
- **Presets.** Xero (day first) and QuickBooks (month first, as in its US edition) only set the
  date order. Both are `TO_BE_CONFIRMED`, and the screen says so whenever one is chosen.
- The opening-balance logic moves to `onboarding/opening.py`. `services.py` keeps the chart, the
  customers and suppliers, and the shared check-and-run helpers.

## Consequences
- AC-R2 and AC-R3 hold for these inputs: the trial balance equals the source after posting, and
  every refusal names the row and the reason.
- When the owner provides anonymised exports, the header names and presets are checked against
  them, and the presets' status changes.
