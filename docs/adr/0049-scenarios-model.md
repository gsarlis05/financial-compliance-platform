# ADR-0049: Scenarios as typed overrides on an approved assumption set
Status: **Proposed** (M7-1, #176; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Doc 10 §8 and FR-S1 to FR-S3 ask for scenarios: a base plus an ordered list of typed overrides
(percent and absolute changes, timing shifts, new financing, new hires, capex, one-off cash events,
rate changes) whose outputs are always hypothetical, never change a budget or forecast, and can be
promoted only by an explicit, approved action. Doc 03 sketches `SCENARIO` (base, status `DRAFT`,
`SHARED`, `ARCHIVED`) and `SCENARIO_OVERRIDE` (sequence, type, schema-validated parameters,
rationale). The M7 brief (doc 21 §3, approved 2026-11-16) takes the simplest sound base: an
approved assumption set of the M6 projection model.

## Decision
- **Base:** an approved assumption set of the same legal entity, pinned by id. A newer approved
  version doesn't change the scenario; it reports "a newer version is approved" and can be
  **copied onto the new base** (rebase), which checks every override again against the new
  horizon and loans and names the first one that doesn't fit.
- **Overrides** are one of eight types with typed, validated parameters (`overrides.py`); there is
  no free-form formula or code. Parameters are stored normalised (decimal strings, months as the
  first day of the month), so stored values are canonical for the run hashes of M7-2. Months must
  lie inside the base's horizon. At most 50 overrides per scenario. They apply in their sequence
  order (M7-2).
- **New hires:** the employer cost % is entered by the user with its source. The platform holds no
  social-insurance rate, because none has been verified by a professional (doc 10 §8 asks for a
  verified parameter; brief §7 item 2).
- **Lifecycle and visibility:** a draft is visible only to its author; sharing makes it visible to
  everyone with `planning.read` on the entity and freezes it; archiving keeps it. Copy creates a new
  draft for the person copying. Changes need `planning.run`; archiving someone else's scenario also
  needs `planning.publish`.
- **Database:** FORCE row-level security and composite tenant keys on `scenarios_scenario` and
  `scenarios_override`. Triggers: a scenario starts as a draft on an approved (or since superseded)
  set of the same entity; its entity, base, author and origin never change; only a draft is
  renamed; status moves only `DRAFT → SHARED → ARCHIVED` or `DRAFT → ARCHIVED`; nothing is deleted;
  overrides change only while their scenario is a draft. The (scenario, sequence) key is deferred to
  commit so overrides can be reordered in one transaction.
- `projections` exposes `set_info` (status, horizon, loan codes) and its line lists through its
  public interface; `scenarios` never reads projection tables directly and never imports the ledger.

## Consequences
- Scenario figures will be `HYPOTHETICAL` throughout (M7-2 runs them through the unchanged M6
  engine, which stays `PENDING_PROFESSIONAL_REVIEW`).
- 13-week cash what-ifs (M3-9) remain the tool for the next 13 weeks; budgets and 13-week forecasts
  are not scenario bases (brief §7 item 3).
- Personal-workspace scenarios are left for later (brief §7 item 4).
