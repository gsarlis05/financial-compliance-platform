# ADR-0045: Loans are projected one by one and reconciled every month
Status: **Proposed** (M6F-4, #149; awaiting product owner review in PR) · Date: 2026-11-15

## Context
Owner decision D5 (2026-11-15): interest on the opening debt balance each month is confirmed as
the default simplified convention; projections must support different interest rates, repayment
structures, additional borrowing, early repayments and variable-rate loans, and interest expense,
principal repayments, debt balances and cash flows must reconcile. The M6-3 engine had a single
debt pool with borrowing and repayment drivers.

## Decision
- **Loans of an assumption set** (`projections_assumption_loan`): an *existing* loan with its
  balance at the cut-over, or a *new* loan drawn at the end of a month of the set; repayment
  structure (annuity, equal principal, bullet), repayment months, interest-only months and a
  starting rate. Monthly **rate path**, **early repayments** and **extra drawdowns** are values of
  the set (drivers `loan_rate`, `loan_prepayment`, `loan_drawdown`, with the loan's code as the
  line), so they are versioned and approved with everything else. Loans change only while the
  set is a draft (database trigger) and are copied by a revision.
- **From the debt register:** "add the loans of the debt register" brings every drawn loan of the
  M3 register with its balance after the instalments due up to the cut-over, its remaining
  months, rate and structure (linear becomes equal principal; interest-only-then-annuity keeps
  its remaining interest-only months). The projection is monthly; a register loan paid quarterly
  or half-yearly says so in its note.
- **Conventions** (`projections/debt.py`, pure): interest on the opening balance of the month at
  the month's rate; drawdowns, scheduled repayments and early repayments at the month end; an
  annuity is re-worked each month on the balance and months left (so an early repayment lowers
  later payments and keeps the end date); equal principal likewise; the last month repays the
  rest; an early repayment never exceeds what is owed; the **current portion** (IAS 1.69) is the
  scheduled principal of the next 12 months from the month-end balance.
- **Other debt.** Debt in the books not covered by the set's existing loans stays a separate pool
  with the borrowing, repayment and interest-rate drivers (as in M6-3). Existing loans may not add
  up to more than the debt in the books at the cut-over: such a projection is refused.
- **Statements:** interest = the loans' interest + other debt + the credit facility; borrowing and
  repayment cash flows include every loan; the debt lines are the loans' current and non-current
  parts, other debt and the credit facility. Each loan's month is stored (`DEBT.<code>.*`) with
  lineage to the set.
- **Seventh invariant, `debt_reconciles`:** each loan opens on its previous closing and rolls
  forward exactly (opening + drawdowns − principal − early repayment = closing); its current part
  lies between zero and the balance; the debt lines equal loans + other debt + facility; interest
  equals the sum of its parts. Engine version 2.
- **Rolling forecasts** that start after the set's cut-over roll each loan forward through the
  months in between first.

## Consequences
- Every loan can be explained month by month and is checked on every run; property tests cover
  random structures, rates, early repayments and drawdowns.
- Version-1 runs stay stored as they were; re-running them uses version 2.
- Fees, covenants, capitalised interest and day-count interest are not modelled in projections
  (the M3 register keeps its day-count schedules for the 13-week cash forecast).
