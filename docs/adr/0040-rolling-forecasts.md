# ADR-0040: Rolling forecasts re-run the projection as the books move, and keep every run
Status: **Proposed** (M6-4; awaiting product owner review in PR) · Date: 2026-11-12

## Context
Doc 10 and the M6 brief ask for a forecast of the next 12 or 24 months that stays current as the
books change, keeps earlier forecasts, and reports how good they were. The projection engine
(ADR-0039) and the calculation-run framework already give pinned, reproducible, immutable runs.

## Decision
- **A setting per legal entity** (`projections_rolling_forecast`): an assumption-set family (its
  approved version is used, so approving a revision moves the forecast onto it), a horizon of 12
  or 24 months, and an active flag. Changes are audited.
- **A run** is an ordinary projection run (kind PROJECTION) tagged with the setting's ID in its
  inputs. Its cut-over is the end of the last full month before today; its months are the next 12
  or 24. Months the set does not cover take the set's value for the same calendar month, the
  nearest year first (no growth assumed); the rule is in the engine's loader, so runs stay
  reproducible from their inputs.
- **Stale** when: postings exist after the run's watermark; a later month has closed; another
  version of the family was approved; or the horizon changed. A stale run is marked, never changed.
- **Refresh:** on demand or by the scheduled `projections_refresh` job (hourly, runtime role, as
  M3-8): it lists only the workspaces with an active rolling forecast through the
  `projections_rolling_tenant_ids()` SECURITY DEFINER function, then acts in each workspace as the
  user who last changed the setting, with that user's current permissions; a refusal skips the
  entity and is logged. A new run supersedes the latest; earlier runs are kept.
- **Accuracy:** for each of the last 12 closed months, the latest valid rolling run made to the end
  of the month 1, 3 and 6 months before, against the actual revenue, EBITDA and closing cash from
  the ledger. Error = forecast − actual; % error = |error| / |actual|, not meaningful when the
  actual is 0. Reported, not gated (doc 12).

## Consequences
- Rolling forecasts reuse the engine, its invariants and the publish rule; nothing new can post.
- Repeating the same month of the set is a simple, visible rule; growth beyond the set's horizon
  needs a revised set with a longer horizon.
- The job runs hourly; a forecast can be up to an hour behind a posting, and says so (stale).
