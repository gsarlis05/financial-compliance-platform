# ADR-0031: Personal finances are plain-words screens over the ledger; valuations stay outside it
Status: **Proposed** (M5-1; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 11 §5 asks for personal workspaces with simplified transactions and categories, with double
entry underneath and the journals and approvals hidden. It also asks for a net-worth view that can
include user-entered valuations (nature EXPECTED, doc 11 §4.3), and no automatic flow from
business workspaces.

## Decision
- **A `personal` module over the ledger**, available in personal workspaces only (a new
  `personal_finances` feature, checked on the server). It never writes journal lines itself: it
  calls two new ledger functions, `create_and_post` and `reverse_and_post`. So every ledger rule
  applies: balance, open period, gapless numbering, immutability and the audit trail.
  - **Money accounts** are the postable asset and liability accounts.
  - **Categories** are the postable income and expense accounts.
  - Both come from the existing `personal` chart of accounts, and more can be added.
- **Three plain transactions**, each one two-line entry posted at once (a household has no
  approval step, which was already its default):
  - **spent:** spending category debit, money account credit;
  - **received:** money account debit, income category credit;
  - **moved:** destination debit, source credit.

  Opening balances go against "Opening net worth". **Undo** is a reversal dated today, with a
  reason; the original is kept and marked undone.
- **Years** are calendar years, opened automatically when a transaction first falls in one.
- **Valuations** (property, investments, a business stake) are stored separately
  (`personal_valuation`). They have nature EXPECTED, are versioned (a new value for the same date
  supersedes the old one; a trigger refuses edits and deletes) and are **never posted**.
- **Net worth** uses the latest valuation on or before the date, otherwise the ledger balance, and
  labels each line. It includes the month ends of the last 12 months.
- **Spending by category** is the period's trial balance for the income and expense accounts.

## Consequences
- The books stay true: a valuation changes net worth but never the ledger. Reports and exports
  show what happened.
- Business features (journals, customers and suppliers) are hidden in personal workspaces. The
  server still enforces permissions on every route.
- Splitting one payment over several categories, and recurring transactions, can follow. Each would
  still be one balanced entry.
