# 16 — Milestone 3 Implementation Brief: calculation framework and 13-week cash forecast

Status: **IN PROGRESS** (product owner go-ahead 2026-11-04: "Continue", after the Milestone 2
report). Backlog: [08 §M3](08-implementation-backlog.md). Specification: [10](10-cfo-fpa-specification.md)
§1–§3 (approved). Acceptance: [12](12-fpa-testing-and-acceptance.md) §4.1–§4.2 (approved).

## 1. Business purpose
Answer the CFO's first question: **"Will we have enough cash over the next 13 weeks, and what can
we do about it?"** This milestone also builds the **shared calculation framework** that every later
planning feature (budgets, KPIs, goals, projections, scenarios, the AI CFO) uses:
- one calendar;
- every number carries its *nature* (actual, committed, expected, hypothetical, …);
- every calculation is a reproducible, explainable *run* pinned to a ledger watermark.

## 2. Rules carried from the approved specification (doc 10 §1)
- **P1:** the ledger is the only historical truth. Planning reads actuals through
  `reporting.actuals` and the registers' public APIs only (ADR-0007, import contracts).
- **P2/P3:** every planning value has a `nature`, and actuals and plans are never added without an
  explicit `blend()`.
- **P4/P5:** calculations are deterministic (no floats, no wall clock, no randomness in calculation
  code). Published runs are immutable, and re-running a run reproduces its output hash.
- **P6:** lineage for every value.
- **P7:** Decimal throughout, rounding per doc 10 §2.4.
- **P8:** one calendar.
- **P9:** AI is never the calculator (Phase 5).

## 3. Defaults taken (change them any time)
| Question | Default in M3 |
|---|---|
| 13-week horizon start | Bucket 1 runs from the as-of date to the end of its ISO week (Sunday); buckets 2–13 are full ISO weeks. Flows dated before the as-of date are "overdue" and shown in bucket 1, flagged. |
| Business days | Monday–Friday, plus a **holiday list supplied as data** per entity. No public holidays are built in (none are verified yet); obligations can still be adjusted to business days. |
| Tax payment calendar (M3-5) | **Manual entry only.** Templates with Cyprus due dates are added only when a tax professional has verified them (decision #93). Nothing is pre-filled from memory. |
| Golden 13-week workbook (AC-CW5) | An independently computed reference fixture for Demo Trading Ltd is built in M3-7. **Sign-off by a finance professional is an owner item**; until then the fixture is marked "not yet signed off". |
| Minimum cash and facilities | A per-entity setting (amount) and an optional undrawn facility amount; both default to 0. |
| Unreconciled warning (AC-CW1) | A warning when a bank account's last reconciliation is more than 7 days before the as-of date (setting). |
| Event-driven re-runs (M3-8) | Runs are marked stale at once on posting, reconciliation or open-item change. A new run is made on demand or by the scheduled job every 15 minutes (`cashflow_refresh`); there is no background thread in web processes. |

## 4. Order and approach
| # | Item | Issue | Approach |
|---|---|---|---|
| 1 | M3-1 Calendar | #55 | `calendar` module: pure date functions (ISO weeks including week 53, fiscal periods for any start month, months and quarters, business days with data-supplied holidays and FOLLOWING / MODIFIED FOLLOWING / PRECEDING adjustment, 13-week buckets, dated allocation of flows to buckets, never pro-rated). A thin loader reads the entity's fiscal years from the ledger. |
| 2 | M3-2 Metrics core | #56 | Nature enum; `ActualSeries`, `PlanSeries`, `BlendedSeries` (no `+` across natures; `blend()` with a cut-over); `CalcRun` (inputs pinned to ledger watermark and as-of, input and output hashes, engine version, status, stale) and `CalcResult` with `lineage`; immutability triggers; reproducibility harness. |
| 3 | M3-3 Expression evaluator | #57 | Own parser (no `eval`): Decimal arithmetic, typed references, unit typing, safe division (NotMeaningful), size and depth limits, ≥ 10k-case fuzzing. Shared later with the rules engine (M9). |
| 4 | M3-4 Obligations and debt | #58 | `registers`: recurring obligations (schedule rules, business-day adjustment, nature) and debt instruments (annuity, linear, bullet, interest-only; ACT/360, ACT/365, 30/360), with a schedule generator tested against reference tables. |
| 5 | M3-5 Tax payment calendar | #59 | `registers`: manually entered tax payments (kind, due date, amount, nature COMMITTED or EXPECTED, reference); no built-in dates. |
| 6 | M3-6 Payment behaviour | #60 | Observed average days late per customer (trailing 12 months, minimum sample size, otherwise 0 with a note) from allocations; per-customer override. |
| 7 | M3-7 13-week forecast | #61 | `cashflow` engine: opening cash (bank/cash accounts via `reporting`), AR/AP, obligations, debt, tax, manual items, each with its nature; buckets with inflows and outflows by category, closing cash, minimum cash, headroom, liquidity, shortfall flags, first shortfall date; a run per forecast. |
| 8 | M3-8 Re-runs, history, accuracy | #62 | Stale marking on events, scheduled refresh, run history, weekly accuracy (forecast made N weeks earlier vs actual, by category). |
| 9 | M3-9 What-ifs | #63 | Sandbox runs (nature HYPOTHETICAL) with timing shifts, one-offs and % changes, never saved over the base, shown as a delta per bucket. |
| 10 | M3-10 Cash dashboard | #64 | A 13-week chart with nature encoding (doc 10 §10.1, not colour only), a buckets table, drill-down to items, data-quality warnings, what-if panel, English and Greek, axe-clean. |

Every item follows the established patterns:
- tenant-owned models with FORCE row-level security and composite keys;
- a permission on every route;
- an audit event per change;
- problem+json errors and Decimal money;
- OpenAPI regenerated;
- live checks for UI;
- planning modules never import the ledger.

## 5. Acceptance criteria
- **AC-M3-1:**
  - ISO week 53 and leap days are handled;
  - fiscal years starting in any month are handled;
  - business-day adjustment conventions are correct around weekends and listed holidays;
  - 13-week buckets are contiguous and cover the horizon exactly;
  - allocation never pro-rates, and the sum over buckets equals the sum of the flows (property
    tests).
- **AC-M3 framework:** AC-CF1 to AC-CF5 (doc 12 §4.1).
- **AC-M3 cash forecast:** AC-CW1 to AC-CW8 (doc 12 §4.2). AC-CW5 is met against the reference
  fixture, with professional sign-off pending (§3).

## 6. Risks
| Risk | Mitigation |
|---|---|
| Forecast mistaken for actuals | Nature on every value, type-level separation, mandatory visual encoding, labels in every export |
| Unverified tax or holiday dates presented as fact | Manual data only, until verified; no built-in dates |
| Non-reproducible numbers | Pinned watermark and as-of date, no wall clock or floats in calculation code, hash tests in CI |
| Scope (two L items) | One PR per issue in the order above; each PR stands alone |
