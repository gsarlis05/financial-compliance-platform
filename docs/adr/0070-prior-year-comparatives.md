# ADR-0070: The prior year by month, kept as comparatives
Status: **Accepted** (R-4, #247; brief 26) · Date: 2026-11-26

## Context
Several features compare against the prior year:
- budget variance against the prior year;
- KPIs and their trends;
- statements with comparatives;
- forecasts that start from history.

When the books move here, that year exists only in the old books, usually as a monthly trial
balance. The brief requires it to be usable "without creating entries in a closed year".

## Decision
- **Comparatives, not entries.** A new table in `reporting`, `reporting_fact_comparative`, holds
  each account's movement per month for the months before the books start. The books start is
  the start of the entity's first fiscal year.
  - The table has FORCE RLS, composite tenant keys, and accounts kept inside the same entity.
  - Debits and credits must not be negative.
  - No journal entry is created, and no fiscal year is opened or closed.
- **Where they are read.** The reporting gateway, the only path planning modules use to read
  history (ADR-0007), now merges them in:
  - `actuals_monthly` includes them for months before the books start. No fiscal year covers
    those months, so no posting can fall in them, and the two sources never overlap.
  - `opening_net` and `balances_before` include them only for cut-off dates up to the books start.
    From that date the opening entry carries the balances, so nothing is counted twice.
  - Daily cash facts and dimension actuals do not include them, because a monthly trial balance
    has neither days nor dimensions.
- **The file** is a monthly trial balance: one row per account, one column per month. Each cell
  is the balance at the end of that month, with debits positive.
  - Income and expense are read year to date by default, resetting in the fiscal year's first
    month, or as each month's own amount.
  - An optional Opening column gives the balance-sheet balances at the start of the first month.
    It is kept as the month before, so the first month shows its own movement.
  - Month headers are read in any of these forms: 2025-01, 01/2025, Jan 2025, January 2025,
    Jan-25, or a date.
  - The template lists the 12 months before the books start.
- **Checks** (each refusal names the row and column):
  - every month is before the books start;
  - the months follow one another;
  - each month balances, with the difference shown;
  - accounts are known, or mapped as in R-2;
  - the last month's asset and liability balances equal the opening entry's.

  Equity is not compared, because it differs by the year's result carried into it. Without an
  opening entry the check is skipped, with a warning.
- **One set per entity.** Importing again replaces the set. Each replacement is audited with the
  file's SHA-256, the months and the number of accounts.
- **Permission:** `ledger.entry.create`, as for the opening balances: preparing the figures the
  books start from.

## Consequences
- Budget variance against the prior year, KPIs over the prior year, and statements for its months
  read the comparatives with no change to those modules.
- Replacing comparatives changes what a recalculation of a prior-year period reads. Calculation
  runs keep their stored results, and a reproducibility check would report the difference.
- A cash forecast's daily history does not come from comparatives; it starts with the books.
