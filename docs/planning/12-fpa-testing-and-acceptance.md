# 12 — FP&A Testing Strategy and Phase 2 (MVP) Acceptance Criteria

Status: **APPROVED (2026-11-03)** · Applies to M3–M5 (Phase 2), and the strategy extends to Phase 3.
Phase 1 criteria: [09](09-milestone-1-acceptance-criteria.md) (M1) + §3 below (M2).

## 1. Test strategy for calculations and forecasting

| Layer | Technique | Examples |
|---|---|---|
| Unit | Example-based tests per function, documented formulas | Each KPI on a hand-computed dataset; amortisation schedules vs reference tables; calendar bucketing |
| **Golden models** | Reference workbooks built independently (Excel) and **signed off by a finance professional**. Engine output must match to the cent. | 13-week forecast for Demo Trading Ltd; budget variance pack; (Phase 3) 5-year 3-statement model |
| **Property-based** (Hypothesis) | Random valid inputs → invariants hold | Budget quarterly = Σ monthly; forecast closing(t) = opening(t+1); (Phase 3) BS balances for any assumption set; scenario with zero overrides = base |
| **Reproducibility** | Re-run with the same inputs → identical `output_hash` | Every published run in CI fixtures; re-run after unrelated new postings (watermark pinned) |
| **Nature separation** | Type tests, API schema tests, UI snapshot tests | `ActualSeries + PlanSeries` raises; every API point has `nature`; chart renders dashed for FORECAST |
| Boundary | Dates and periods | ISO week 53, leap day, fiscal year starting July, month-end weekend due dates, as-of date on a period boundary, forecast crossing the fiscal year end |
| Edge/NM | Degenerate data | Zero revenue (margins NM), negative equity (ROE/D-E NM), no AR history (days late = 0 + note), empty budget lines, KPI with a missing mapping (blocked with task) |
| Staleness | Event-driven | Posting an entry marks dependent runs stale and creates a new run; an approved budget is unchanged |
| Immutability | Direct SQL as the app role | UPDATE on an approved plan version / valid calc run / final pack fails |
| Security | Isolation, coexistence and scope suites | Every planning endpoint × cross-tenant × cross-workspace × dimension scope |
| Export fidelity | Golden comparison | XLSX/PDF values equal API values; nature column present; formula-injection safe |
| Performance | Benchmarks in CI (non-blocking trend) + pre-release gate | 13-week forecast 10k open items < 2 s; dashboard < 1.5 s p95 |
| Accuracy (pilot) | Forecast-vs-actual tracking | Weekly MAPE by category, reported but not gated |

## 2. Synthetic data for FP&A
- **Demo Trading Ltd** (CY, EUR): 3 years of history, seasonal revenue, 40 customers with differing payment behaviour, 25 suppliers, payroll, rent, a term loan, an overdraft facility, VAT, capex, two departments and one project.
- **Synthetic household:** salary, mortgage, savings, card spending categories, irregular bonuses.
- **Generator parameters** (to mimic your own situation without real records): revenue level, growth, margin, seasonality, cost structure, payment delays, debt.
- Fixtures are deterministic (seeded) and versioned with the code.

## 3. Phase 1 completion criteria (M2 additions to doc 09)
- AC-P1-1 Open items: an invoice entry creates an open item; partial and full settlements reconcile; the ageing report equals the AR/AP control account balance (reconciliation test).
- AC-P1-2 Bank reconciliation: imported statement lines match or are flagged; the reconciled balance equals the bank statement closing balance; the last-reconciled date is shown.
- AC-P1-3 Taxonomy mapping: an unmapped account with activity produces a blocking task; statements refuse to finalise while it exists.
- AC-P1-4 Actuals read model: a rebuild from the ledger equals the incremental state (property test); the nightly check detects deliberate corruption.
- AC-P1-5 Statements: the BS balances; P&L net result = movement in retained earnings after close; the indirect cash flow statement's net change = the change in cash accounts.
- AC-P1-6 Dimensions: required-dimension rules enforced at posting; TB filterable by dimension; Σ over dimensions = total.
- AC-P1-7 VAT codes: lines with VAT codes post the correct VAT control amounts per the code catalogue; invalid code/date combinations are rejected.

## 4. Phase 2 (MVP) acceptance criteria

### 4.1 Calculation framework (M3)
- AC-CF1 All planning values carry `nature`. A DB `NOT NULL`, the API schema and a type test enforce it.
- AC-CF2 Arithmetic between actual and plan series without `blend()` fails type checking (mypy) and at runtime.
- AC-CF3 Re-running any published run with the stored inputs reproduces `output_hash` (tested on all fixtures).
- AC-CF4 Every calc result has lineage. The "Explain" API returns contributing actual keys/assumptions/items for any value.
- AC-CF5 The expression evaluator rejects unknown functions, unit mismatches and oversize expressions; fuzzing (≥ 10k cases) never crashes a worker; division by zero yields NM with a reason.

### 4.2 13-week cash forecast (M3)
- AC-CW1 Opening cash equals the sum of bank/cash balances at the as-of date. Accounts unreconciled for more than N days show a warning on the forecast.
- AC-CW2 Open AR expected dates = due date + the customer's observed average days late (or the override). Open AP follows the payment policy. Recurring obligations, debt schedules, the tax calendar and manual items appear with the correct nature.
- AC-CW3 Weekly buckets follow ISO weeks. Flows are dated, never pro-rated. Σ buckets = Σ flows.
- AC-CW4 For every bucket, closing(t) = opening(t) + inflows − outflows, and opening(t+1) = closing(t). The minimum cash rule flags shortfalls, and the first shortfall date is correct.
- AC-CW5 Matches the signed-off golden workbook to the cent.
- AC-CW6 Posting a receipt or reconciling the bank marks the forecast stale and produces a new run within the debounce window. Earlier runs remain retrievable, and accuracy metrics are computed for elapsed weeks.
- AC-CW7 A what-if (customer X pays +60 days) is labelled HYPOTHETICAL, is never saved over the base, and shows the delta per bucket.
- AC-CW8 Debt schedules match reference amortisation tables for annuity, linear and bullet loans under ACT/360, ACT/365 and 30/360.

### 4.3 Budgets and variance (M4)
- AC-BU1 Lifecycle DRAFT→SUBMITTED→APPROVED→LOCKED. SoD is enforced when configured. Approved versions are immutable at the DB level. A revision creates a new version with a reason, and the original remains reportable.
- AC-BU2 Phasing methods produce monthly values that sum exactly to the annual input (rounding residual allocated to the last period, documented).
- AC-BU3 Excel import validates and previews; it rejects unknown accounts, non-numeric values and out-of-FY periods with row-level messages; cells beginning with `=`, `+`, `-` or `@` are treated as text or rejected per policy, never evaluated.
- AC-BU4 Budget vs actual uses posted entries only (draft count shown as a warning). Variance sign and favourable/unfavourable follow the line direction (tests for revenue and expense).
- AC-BU5 Variances above the threshold require an explanation before a report/period review is marked complete. Explanations are versioned and attributed.
- AC-BU6 Department-scoped owners can view and edit only their department (API, grid, export and dashboard).

### 4.4 KPIs (M4)
- AC-KP1 Each core KPI matches a hand-computed value on fixtures, with conventions (average balances, day counts) as documented.
- AC-KP2 NM cases (zero denominator, negative equity, zero comparative) display "Not meaningful" with a reason, never 0 or ∞.
- AC-KP3 KPI values link to numerator/denominator components and drill down to accounts and entries.
- AC-KP4 Workspace-wide custom KPIs require approval and are versioned. Historical values reference the definition version used.
- AC-KP5 Operational metrics are labelled as non-ledger data in every display and export.

### 4.5 Goals (M4)
- AC-GO1 The baseline is frozen at creation. Changing the target creates a new goal version.
- AC-GO2 For the sample goals (€500k revenue, 20% EBITDA margin, ≥ €100k cash, DSO 30 days, +15% net profit, −10% opex), the evaluation returns actual-to-date, projected outcome, gap, required performance, status and contribution analysis, each matching the golden workbook.
- AC-GO3 Goal-seek reports "not achievable within bounds" correctly, and the held-constant assumption is stated.
- AC-GO4 An alert is raised when the status crosses into AT_RISK/OFF_TRACK or a threshold breach is forecast, and it is not re-raised while unchanged.
- AC-GO5 Contribution analysis components sum to the total variance (any residual shown explicitly).

### 4.6 CFO dashboard v1 (M4)
- AC-DB1 Actual, committed, expected/forecast and hypothetical series render with the visual contract (doc 10 §10.1) in charts, tables, tooltips and exports. Automated visual snapshot tests run in light and dark themes.
- AC-DB2 A "today/cut-over" marker appears on all time charts. KPI cards state Actual/Forecast/Blended.
- AC-DB3 Drill-down KPI → line → account → entry → document works within permissions. Denied steps give a clear message.
- AC-DB4 Period presets and comparisons (budget, forecast, PY) update all widgets consistently. Widget values equal the corresponding report values.
- AC-DB5 Initial load p95 < 1.5 s on the 3-year fixture. axe (WCAG 2.2 AA) passes, and charts have non-colour encodings and table alternatives.
- AC-DB6 Firm portfolio shows only granted clients. After revocation, the client disappears and its derived metrics are purged.

### 4.7 Personal MVP and coexistence (M5)
- AC-PE1 A user with personal and business workspaces passes the full coexistence suite (doc 11 §9).
- AC-PE2 The personal net worth = Σ assets − Σ liabilities, reconciled to the underlying ledger. Category budgets and goals work with the personal taxonomy.
- AC-PE3 The counterpart hint never posts without confirmation in the target workspace.
- AC-PE4 Full workspace export (JSON + CSV + documents) and deletion flows work and are audited. Deletion respects legal hold/retention where applicable.
- AC-PE5 Pilot readiness (Gate P, for the owner's personal **and** business workspaces): the coexistence suite passes for exactly this pair; AI is disabled for the business workspace; backup restore tested; AI disabled; no pilot→dev data path (infra policy test); security review completed; **your approval recorded**.

### 4.8 Quality gates (all milestones)
Domain coverage ≥ 90% line / 85% branch; calc engines 100% branch; CI green (lint, mypy strict,
Semgrep, SCA, secrets, import contracts); docs and known limitations updated; no unapproved
deployments or migrations.
