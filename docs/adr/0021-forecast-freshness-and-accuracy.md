# ADR-0021: Forecast freshness by comparison, scheduled refresh, accuracy reporting
Status: **Proposed** (M3-8; awaiting product owner review in PR) · Date: 2026-11-04
## Context
Doc 10 §3.4 asks that a forecast is marked stale when the books change (postings, bank
reconciliations, open-item changes), and that it is re-run automatically (debounced, about every
15 minutes) as a new run. Earlier runs stay available for forecast-versus-actual tracking. Many
modules can change a forecast's inputs:
- the ledger;
- banking;
- registers (allocations, disputes, obligations, loans, tax);
- cashflow (manual items, settings).

Hooks in each of them would couple the ledger and others to planning, and a missed hook would
leave a forecast wrongly "current".
## Decision
- **Freshness by comparison, not by events.** The latest forecast is out of date when any of
  these holds:
  1. the entity has posted entries after the run's watermark;
  2. the inputs prepared now for the run's as-of date differ, by canonical hash, from the run's
     stored snapshot. This covers every input the forecast uses, with no list of events to keep
     in step;
  3. the run's as-of date is before today.

  `GET …/cash-forecasts/latest` reports this at once, with the reasons. A read-only user can see
  it: the check needs read permissions only. Runs are never edited: refreshing only sets `stale`
  on earlier runs.
- **Refresh.** A refresh makes a new run as of today that supersedes the latest one. It runs:
  - on demand: `POST …/cash-forecasts/refresh` (204 when current);
  - from the scheduled job `cashflow_refresh`, every 15 minutes as an ECS scheduled task.

  The job finds workspaces through `cashflow_forecast_tenant_ids()`, a SECURITY DEFINER function
  that returns IDs only. It then works on each workspace under its normal row-level security
  context, acting as the user who ran the entity's latest forecast with that user's current
  permissions. Entities whose user lost access are skipped and logged. Web processes run no
  background threads.
- **History.** `GET …/cash-forecasts/history` lists runs newest first, with the as-of date, trigger,
  what each supersedes, staleness, opening, week-13 closing and first shortfall.
- **Accuracy.** For each fully elapsed ISO week:
  - **Forecast:** the net cash movement forecast by the latest valid run made 1, 4 and 13 weeks
    earlier.
  - **Actual:** the net movement on the `BS.CASH` accounts.
  - **Measures:** error = forecast − actual; APE = |error| ÷ |actual|, not meaningful when the
    actual is 0; MAPE is their mean, as a percentage.
  - **Reported, not gated.** It is computed on request from stored runs and current actuals.
## Consequences
- **Cost:** checking freshness prepares the inputs again, a few queries, on each `latest` request.
  That is acceptable at current sizes, and can be cached by input hash later.
- **Precision:** a change that does not alter the forecast's inputs (for example an unrelated
  allocation that leaves open amounts unchanged) does not make it stale, which is correct.
- **Accuracy by category** waits until bank movements are categorised; only the total is compared
  for now.
## Alternatives considered
- **Event hooks or signals in each module:** they couple modules, and one missed event gives a
  silently wrong "current" flag.
- **Re-running on every request:** expensive, and it makes history noisy.
