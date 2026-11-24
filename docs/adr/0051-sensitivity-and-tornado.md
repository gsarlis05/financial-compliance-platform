# ADR-0051: Sensitivity and tornado as cached, quota-limited re-runs of the projection engine
Status: **Proposed** (M7-3, #178; awaiting product owner review in PR) · Date: 2026-11-16

## Context
Doc 10 §3.6 asks for one-variable sensitivity (vary a driver over a range and show the impact on
minimum cash and the first shortfall) and a tornado chart (rank drivers by their impact on a chosen
output for a ±X% shock), implemented as N deterministic re-runs of the engine, cached and not
persisted as official versions (doc 02). Threat T34 asks for per-user and per-tenant quotas,
input-hash caching and run timeouts, since such runs can be expensive.

## Decision
- **Pure core** (`scenarios/sensitivity.py`): a shock changes one driver of the base's engine input
  for every month of the horizon (amounts and ratios relatively by %; DSO, DIO and DPO also by days
  in one-variable mode, not below 0; interest rates relatively on other debt, the credit facility
  and every loan), then the unchanged projection engine runs. Outputs: lowest month-end cash, closing
  cash, months before the first shortfall (the horizon if none), EBITDA or net income for a year.
- **One variable:** 2 to 11 evenly spaced values between a low and a high. **Tornado:** each driver
  at −X% and +X% on its own (default 10%, at most 25 drivers, by default every driver the base
  uses); ranked by the absolute swing, ties by the driver's name.
- **Base:** an approved assumption set, or a **shared** scenario with its overrides applied (a draft
  could change under the analysis).
- **Cache by input hash:** the hash covers the tenant, the base's pinned inputs, the ledger
  watermark and the request. A repeated request is answered from the cache (`cached: true`) for 10
  minutes and costs no quota. Nothing is written to the database; results are `HYPOTHETICAL`.
- **Quotas:** every engine run counts against the user (300 a minute) and the workspace (1,200 a
  minute); beyond them the request is refused with HTTP 429 and a plain message. **Time limit:** 30
  s per request (HTTP 409, "choose fewer drivers or steps"). All four numbers are settings.
- Requests need `planning.run`.

## Consequences
- The cache and quota counters use Django's cache. With one process (development, tests) they are
  exact; with several server processes production needs a shared cache (for example the pilot's
  cache service) for them to be exact. Until then each process counts on its own. Listed as a known
  limitation.
- Results inherit the projection engine's status, `PENDING_PROFESSIONAL_REVIEW`; the response says so.
- Screens (tornado bars with a table alternative) come with M7-7.
