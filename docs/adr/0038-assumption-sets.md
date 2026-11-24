# ADR-0038: Assumption sets are versioned driver values by month, started from actuals or the budget
Status: **Proposed** (M6-2; awaiting product owner review in PR) · Date: 2026-11-12

## Context
The three-statement engine (M6-3) needs its assumptions as data (doc 10 §4.1): revenue, margins,
costs, working-capital days, capital expenditure, tax, financing and equity, per period. Doc 10 P5
asks that approved plans never change, and P6 that every forecast value be traceable to the
assumption behind it.

## Decision
- **An assumption set** belongs to a legal entity, has a cut-over (the last day of the last actual
  month) and a horizon of 12, 24 or 36 months, and holds **one value per driver per month**
  (`projections_assumption_value`). Every value has nature FORECAST and records its source:
  last year's actuals, the approved budget, a default, or entered by hand.
- **Drivers** (catalogue in `projections/drivers.py`): revenue per revenue line and operating costs
  per cost line as monthly amounts; gross margin %; capital expenditure and the useful life of new
  assets; DSO, DIO, DPO in days; tax rate on profit; new borrowing, repayments and an interest
  rate; dividends and new share capital; minimum cash and a credit facility (limit, rate).
  Payroll is a monthly amount like the other cost lines (headcount × cost per head can follow as
  a helper that fills it).
- **Starting a set:**
  - from **actuals**: each forecast month repeats the same month of the 12 months up to the
    cut-over (revenue optionally grown by a % a year, compounding per year); gross margin, DSO,
    DIO, DPO, the effective tax rate and the interest rate as observed (0 where they cannot be
    worked out, never guessed);
  - from **the budget**: revenue, costs and gross margin from the current approved annual budget
    for the months it covers, actuals as above for the rest;
  - **empty**: zeros, and 60 months for the life of new assets.
  No tax rate is assumed from law: the rate is the one observed in the books, or the user's.
- **Lifecycle:** `DRAFT → APPROVED → SUPERSEDED`. Drafts are edited (values become MANUAL) and can
  be renamed. Approval needs `planning.publish`; approving a later version of the same family
  supersedes the earlier approved one. A revision is a new draft version with the same values.
- **Database guards:** values change only while their set is a draft; a set's horizon, cut-over
  and origin never change; approved sets only move to superseded; nothing is deleted.

## Consequences
- The engine reads one approved set and knows where every input came from.
- Monthly values are explicit, which makes seasonality visible and editable; a "fill right"
  helper in the grid keeps flat assumptions quick to enter.
- Driver formulas such as volume × price or % of revenue for a cost line are not in M6; the user
  enters the resulting amounts.
