# ADR-0047: Rolling forecasts re-run on material changes; published projections stay the reference
Status: **Proposed** (M6F-6, #151; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Owner decision D6 (2026-11-15): forecasts are recalculated hourly by default, and also after
material changes to financial data or assumptions; manual recalculation is possible; published
forecasts stay unchanged until a newly approved version is published; historical versions are
kept for comparison with actuals. M6-4 (ADR-0040) re-ran a stale rolling forecast at an hourly
pass, whatever made it stale, and compared only revenue, EBITDA and cash with actuals.

## Decision
- **One scheduled pass every 15 minutes** (`projections_refresh`; EventBridge Scheduler
  `rate(15 minutes)`, not applied). For each active rolling forecast it re-runs a stale one when:
  - the change is **material**: another approved version of the assumption family, a closed
    month, a changed horizon, or postings since the latest run whose **debits total at least
    the entity's materiality threshold**; or
  - the forecast's **regular interval** (15, 30 or 60 minutes, or 2, 4, 8 or 24 hours; default
    60) has passed since its latest run, for any other postings.
  **Refresh now** re-runs a stale forecast at once. Without a threshold (the default) postings
  are never material and wait for the regular interval; this keeps the hourly default of D6.
  The threshold and interval are part of the setting, audited, and checked by the database.
- **Published runs stay the reference.** The pass never publishes; the outlook and goals keep
  using the latest published projection until someone with publish permission publishes a newer
  valid run (published runs are immutable in the database, M6-3). Every run is kept.
- **Any past projection against actuals** (`GET …/projections/{id}/actuals`): for the
  projection's months that have closed (before today's month), each income statement line and
  the month-end cash as forecast and actual (from the posted books as they are now), with the
  difference (actual − forecast) per month and over the closed months (sums; cash: the last
  month), worked out with decimals on the server.

## Consequences
- A material change is reflected within about 15 minutes; routine postings at most one interval
  later; nothing is re-run without a change.
- The volume of postings is measured as total debits of posted entries after the run's
  watermark (one indexed query).
- The comparison uses today's books, so later corrections to a closed month show in it; the run
  itself never changes.
