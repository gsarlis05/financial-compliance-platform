# ADR-0024: Budget variance, explanations and the monthly review
Status: **Proposed** (M4-3; awaiting product owner review in PR) · Date: 2026-11-04
## Context
AC-BU4 asks that budget-vs-actual uses posted entries only (draft count as a warning), with
variance signs and favourable/unfavourable following the line's direction. AC-BU5 asks that
variances above a threshold need an explanation before a period review is complete; explanations
are versioned and attributed. Doc 10 §7 also lists forecast vs actual and budget vs forecast.
## Decision
- **Computed on request, pinned to one watermark.** Each response reads the actuals once, at one
  ledger watermark, and returns it. A response is therefore reproducible from its watermark, but it
  is not stored as a calculation run. Storing reports as frozen packs is the management-reporting
  module's job (Phase 3).
- **Actuals:**
  - posted entries only, closing entries excluded, through `reporting`;
  - per account and month, in the natural direction (credit-normal accounts negated);
  - a taxonomy line sums the accounts currently mapped to it;
  - a line with a dimension value uses only entries tagged with that value. The ledger has a new
    read, `posted_dimension_totals`, exposed as `reporting.dimension_actuals`.
- **Direction:**
  - a taxonomy line uses its own direction;
  - an account line: income is higher-better and expense is lower-better; otherwise the direction
    of its mapped taxonomy line.
- **Figures:**
  - variance = subject − comparison;
  - % = variance ÷ |comparison|, or not meaningful when the comparison is 0;
  - favourable when the variance points in the line's better direction.
- **Threshold:** |variance| ≥ amount **and** |%| ≥ percent. A not-meaningful percentage counts as
  reached. The defaults, 1,000 and 10%, are per-entity settings.
- **Explanations** are append-only rows per line, month, view and comparison; the latest is shown.
  They can be written only against an approved or locked version.
- **Review:** a month's review needs every actual-vs-budget variance above the thresholds
  explained, for the month and the year to date (only the month in the first month of the year).
  It records the watermark it was checked at, and is append-only.
- **Department owners** see their departments' rows and actuals through `budget.department`,
  without `reports.read`. The draft-entry count is not shown to them, because it would reveal
  other activity.
- **No forecast comparisons yet.** There is no monthly rolling P&L forecast until the projections
  module (Phase 3), so forecast vs actual and budget vs forecast wait for it. Current vs original
  budget is offered instead.
## Consequences
- The review rule applies to actual vs budget. Prior-year variances can be explained, but they are
  not required for a review.
- Budget overrun and trend alerts use these figures in M4-7.
