# ADR-0014: Year-end close in a cumulative ledger (no OPENING entry at year end)
Status: **Proposed** (M2-9; awaiting product owner review in PR) · Date: 2026-11-04
## Context
Doc 05 §5 asks for three things: a system `CLOSING` entry that moves income and expense balances to
retained earnings; an `OPENING` entry for the next fiscal year generated from balance-sheet
balances; and the check *opening TB(FY+1) = closing balance sheet(FY)*. In this ledger, balances are
**cumulative**: a trial balance sums every posting up to a date, and balance-sheet accounts are never
reset at year end. Posting an `OPENING` entry with the balance-sheet balances would therefore count
them twice.
## Decision
- **Close.** A `CLOSING` entry (source `SYSTEM`) is dated the year-end, in the adjustment period when
  the year has one. It brings every income and expense balance to zero **per account and per
  dimension tags**, against a retained-earnings account the user chooses (an active, postable equity
  account).
  - It is generated as *submitted* and follows the normal approval workflow, so segregation of
    duties applies.
  - It cannot be edited.
  - At posting it is recomputed from the ledger, and refused (`ledger.close.stale`) if any balance
    changed after it was generated.
  - Generating it needs `ledger.period.lock`.
  - It is blocked while an earlier year is open, while entries dated in the year are unposted, or
    while another closing entry is pending.
- **Closed year.** Posting the closing entry sets the fiscal year to `CLOSED`.
  - The database guard then refuses any posting into the year, except the reversal of its closing
    entry (migration 0015).
  - At most one live closing entry exists per year (a unique index).
  - The nightly integrity job checks that a closed year has no income or expense balance left.
- **Re-open.** The closing entry is reversed on its own date, through the same workflow. Posting the
  reversal re-opens the year. A generic "reverse" of a closing entry is refused. Re-open and close
  again reproduces the same balances (tested).
- **No OPENING entry at year end.** The next year's opening balances *are* the cumulative balances.
  The AC-M2-9 check verifies that income and expense accounts are zero at the year-end, and that the
  next year's opening trial balance equals the closing balance sheet. `OPENING` entries stay
  reserved for cut-over balances when a company moves in from another system.
- **Closing entries in the read model.** Facts carry `is_closing`.
  - Statements show P&L, cash flow and contributions without closing entries, and balance-sheet
    balances with them. After a close, the result appears in retained earnings, and the closed
    year's P&L is unchanged.
  - Planning (`actuals_monthly`, daily cash) reads operating actuals without closing entries.
## Consequences
+ Postings into a closed year are impossible, even with the application bypassed. The close is
  reviewable, reproducible and audited.
+ Statements are correct before and after a close (a property test covers random postings around a
  closed year).
− Audit adjustments to a closed year need a re-open, an adjustment and a new close. This is
  deliberate: it is visible and approved.
− A year with no income or expense balances cannot be closed: there is nothing to post. This is
  rare, and the year stays open.
− The spec's year-end OPENING entry is replaced by a derived check. **This deviates from doc 05 §5
  and needs the product owner's agreement.**
