# ADR-0007: Planning domain separated from the ledger; actuals via read model; nature-tagged values
Status: Proposed · Date: 2026-11-03
## Context
CFO/FP&A features (forecasts, budgets, scenarios, goals) must use the same verified accounting data without duplicating it, and must never be confused with actual financial information.
## Decision
- Planning modules (`cashflow`, `budgeting`, `projections`, `kpi`, `goals`, `scenarios`, `mgmt_reporting`, `dashboards`) read historical data only through `reporting.actuals`, a derived read model that can be rebuilt from the posted ledger and is stamped with a per-tenant posting watermark.
- No write path exists from planning to the ledger (import contracts + DB grants).
- Every planning value carries a `nature` (ACTUAL, COMMITTED, EXPECTED, HYPOTHETICAL, BUDGET, FORECAST, TARGET), enforced in the DB, API schema, Python types (cross-nature arithmetic only via `blend()`) and the UI visual contract.
- Approved/published planning artefacts are immutable and versioned.
## Consequences
+ A single source of truth; reproducible forecasts (watermark + inputs); forecasts can't masquerade as actuals. − A read model to maintain and verify; extra type ceremony in calculation code.
## Alternatives considered
Planning tables storing their own actuals copy (drift, duplication); forecasts stored as "draft" ledger entries (pollutes the ledger, high risk of confusion).
