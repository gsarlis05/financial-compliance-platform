# ADR-0009: Shared calculation framework (taxonomy, expression evaluator, calc runs with lineage)
Status: Proposed · Date: 2026-11-03
## Context
KPIs, budgets, forecasts, projections, goals, scenarios, statements and tax rules all need consistent definitions, periods, precision and auditability.
## Decision
A `metrics` module provides: a versioned financial taxonomy with account mappings (one vocabulary for statements, KPIs, plans and AI); one sandboxed Decimal expression evaluator with unit typing and safe division (shared with the regulatory rules engine); a `calendar` service; and `calc_run` infrastructure recording engine version, input refs/hash, ledger watermark, output hash, invariant results and per-value lineage. All engines are deterministic pure functions; line items are rounded once to cents when produced, so totals and statements tie exactly.
## Consequences
+ No duplicated formula logic; every number is explainable and reproducible. − The framework must be built before user-visible FP&A features (Milestone 3 front-loads it).
## Alternatives considered
Per-module ad-hoc calculations (inconsistency); spreadsheet engine embedding (formula opacity, float semantics, licensing).
