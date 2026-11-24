# ADR-0041: The full-year outlook blends actual and forecast months; goals use the projection
Status: **Proposed** (M6-5; awaiting product owner review in PR) · Date: 2026-11-12

## Context
Doc 10 P2/P3 ask that every column carry its nature and that actuals and plans be combined only by
an explicit blend with a cut-over. The M6 brief asks for a full-year outlook (actual months, then
forecast months) by month, quarter and year, and for goals (M4-6) to use it as their likely outcome
when a published projection exists.

## Decision
- **The outlook** of a fiscal year (`projections/outlook.py`): the latest valid, published
  projection whose months reach the year defines the cut-over. Months up to it are read from the
  posted books through `reporting` (never from the projection, P1); later months come from that
  projection's stored FORECAST results. Each row is `metrics.blend(actual, forecast, cut-over)`.
- **Lines:** the projection's income statement lines and subtotals, and month-end cash. Actual net
  finance costs are interest expense plus exchange differences less interest income; depreciation
  includes amortisation, so actual and forecast rows mean the same thing.
- **Buckets:** fiscal quarters and the year are exact sums of their months (cash: the last month),
  and only when every month is known; a bucket spanning the divider is labelled ACTUAL+FORECAST.
- **Goals:** when a published projection covers any of a goal's remaining months, its line amounts
  are snapshotted into the evaluation's inputs in the same shape as a budget and used for those
  months (method PROJECTION, or PROJECTION_RUN_RATE where it does not cover every month), with
  lineage "published projection". Otherwise goals keep the budget or the run rate. Stored
  evaluations are unaffected (their inputs are pinned).

## Consequences
- The outlook needs a published projection; publishing stays a deliberate step (planning.publish).
- A projection published later changes new goal evaluations only.
- Screens and Excel export follow in M6-6.
