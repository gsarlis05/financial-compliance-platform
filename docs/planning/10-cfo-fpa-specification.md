# 10 — CFO & FP&A Specification: Calculation and Forecasting Requirements

Status: **APPROVED (2026-11-03)** · Related: [01 PRD §5](01-product-requirements.md), [02 SAD §10](02-software-architecture.md), [03 ERD §5](03-entity-relationship-model.md), [12 tests](12-fpa-testing-and-acceptance.md), ADR-0007/0009

The CFO module answers the question: **"What is likely to happen, and what can management do about it?"**
The ledger answers: "What has happened?" This document defines how the first is derived from the second
without the two ever being confused.

---

## 1. Foundational rules (apply to every FP&A module)

| # | Rule | How it is enforced |
|---|---|---|
| P1 | **The ledger is the only source of historical truth.** FP&A never stores its own copy of actuals as editable data. | Actuals are read through `reporting.actuals` (read model over posted ledger lines). FP&A has no write access to ledger tables (DB grants + import-linter). |
| P2 | **Every number has a nature.** `ACTUAL`, `COMMITTED`, `EXPECTED`, `HYPOTHETICAL`, `BUDGET`, `FORECAST`, `TARGET`. | A `nature` column on every planning value; distinct Python types (`ActualSeries`, `PlanSeries`); the API schema requires `nature` on every data point; UI encodes nature visually (§10.1). |
| P3 | **Never mix natures silently.** Combining actuals with forecast (e.g. "YTD actual + rest-of-year forecast") produces an explicit `BlendedSeries` with a cut-over date and per-point nature. | No `+` operator between `ActualSeries` and `PlanSeries`; only `blend(actual, plan, cutover)`. Type checks (mypy) + unit tests. |
| P4 | **Deterministic and reproducible.** Same inputs + same engine version → identical outputs (byte-identical result hash). | No randomness, wall-clock reads or floats in calculation code. Inputs pinned (§2). Monte Carlo, if added later, uses a stored seed and is labelled stochastic. |
| P5 | **Versioned, never silently overwritten.** Approved budgets, published forecasts and report packs are immutable. Changes create new versions. | DB triggers like the ledger's; version lineage (`supersedes_id`). |
| P6 | **Explicit assumptions.** Every forecast value is traceable to the assumptions, drivers and actuals that produced it. | Lineage records per computed line (§2.3). |
| P7 | **Decimal precision and documented rounding.** | Shared `Money`/`Decimal` library; rounding policy in §2.4. |
| P8 | **Consistent periods.** All modules use one calendar service (fiscal periods, ISO weeks, days). | `calendar` module; no ad-hoc date arithmetic. |
| P9 | **AI is never the calculator.** | AI calls calculation services as tools; see §12. |

## 2. Shared calculation framework (`metrics` + `calc` modules)

### 2.1 Financial taxonomy (the "metric primitives")
Ledger accounts are mapped to a **standard financial taxonomy** (versioned), e.g. `REV.SALES`,
`COGS`, `OPEX.PAYROLL`, `OPEX.RENT`, `DA.DEPRECIATION`, `DA.AMORTISATION`, `INT.EXPENSE`, `TAX.INCOME`,
`BS.CASH`, `BS.AR`, `BS.INVENTORY`, `BS.AP`, `BS.DEBT.CURRENT`, `BS.DEBT.NONCURRENT`, `BS.EQUITY.*`, `BS.PPE.GROSS`,
`BS.PPE.ACCDEP`, …
- The same taxonomy drives financial statements, KPIs, budgets, projections and the AI's vocabulary. That is how duplication is avoided.
- **Mapping completeness check:** an account with activity but no mapping blocks KPI/statement publication and shows an actionable "map these N accounts" task.
- Personal workspaces use a personal taxonomy (`P.INCOME.SALARY`, `P.EXP.HOUSING`, `P.ASSET.INVESTMENTS`, `P.LIAB.MORTGAGE`, …) on the same mechanism.

### 2.2 Expression language
The FP&A formulas (KPIs, driver formulas, goal metrics) reuse the **sandboxed Decimal expression evaluator** from the rules engine ([06 §3](06-regulatory-rules-engine-spec.md)), extended with:
- typed references: `metric("REV.SALES", period)`, `balance("BS.AR", at=period_end)`, `avg_balance("BS.AR", period)`, `driver("headcount")`, `days(period)`;
- **unit/dimension typing**: every expression has a unit (`EUR`, `ratio`, `percent`, `days`, `count`, `times`). Unit mismatches (e.g. EUR + days) are rejected at validation time;
- **safe division**: `a / b` with `b = 0` yields `NotMeaningful(reason="denominator zero")`, never 0 or ∞. Same for negative-denominator cases flagged by formula metadata (e.g. ROE with negative equity).

### 2.3 Calculation runs & lineage
Every forecast, projection, KPI set, scenario or goal evaluation is a **calculation run**:

```
CalcRun {
  id, workspace, kind, engine_version,
  inputs: { actuals_cutoff: (ledger_watermark, as_of_date),
            assumption_set_version_id, plan_version_ids[], taxonomy_version, calendar_id },
  input_hash, output_hash, status, created_by/created_at (system or user), stale: bool
}
```

- `ledger_watermark` = the highest posted-entry sequence included. Because posted entries are immutable and append-only, **"actuals as of watermark W" is exactly reproducible later**. Re-running a run with the same inputs must reproduce `output_hash`.
- Each output value stores `lineage`: contributing assumption IDs, driver IDs, actuals keys (account × period) and formula IDs. The UI "Explain this number" walks this graph.

### 2.4 Rounding policy for projections
- Drivers and intermediate calculations use `Decimal` with 28 significant digits.
- **Each statement line item is rounded to cents (HALF_UP) once, per period, at the point it is produced.** Subtotals, totals and derived balances (e.g. cash, retained earnings) are **sums of already-rounded items**. As a result, statements tie exactly to the cent, with no rounding plugs.
- Percentages/ratios are stored unrounded and rounded only for display (configurable dp).

### 2.5 Calendar & periods
Granularities: day, ISO week (Mon–Sun), month, quarter, fiscal year (any start month). Forecast buckets
align to the entity's fiscal calendar. Weekly buckets crossing month-ends are allocated by date (cash
flows are dated, so this is never pro-rated). Leap years and 53-week ISO years are handled. All forecasting uses
**dates, not datetimes**.

---

## 3. Cash flow forecasting (`cashflow` module)

### 3.1 Horizons and granularity
| Forecast | Granularity | Horizon | Phase |
|---|---|---|---|
| **13-week rolling** | Daily detail → weekly buckets | 13 ISO weeks from as-of date | **2 (MVP)** |
| Monthly cash dashboard | Monthly | Current FY | 2 |
| Rolling 12 / 24 months | Monthly | 12 / 24 months | 3 |
| Quarterly / annual | Aggregated from monthly | Up to 5 years (from 3-statement model) | 3 |
| Daily position | Daily | 30 days | 3 |

### 3.2 Cash flow items and their nature
| Source | Nature | How dated / valued |
|---|---|---|
| Cleared bank transactions (reconciled) | `ACTUAL` | Bank value date |
| Open receivables (customer invoices, from open-items ledger) | `COMMITTED` (contractual) with an `EXPECTED` collection date | Expected date = due date + customer's **observed average days late** (trailing 12 months, deterministic, minimum sample size, otherwise 0), with an overridable per-customer setting |
| Open payables (supplier invoices) | `COMMITTED` | Due date, or the payment-run policy (e.g. pay Fridays, pay on due date − 2 days) |
| Recurring obligations register (rent, payroll, subscriptions, leases, insurance) | `COMMITTED` if contractual, else `EXPECTED` | Schedule rules (monthly on day N, business-day adjustment) |
| Loan schedules (principal + interest) | `COMMITTED` | Amortisation schedule (§3.5) |
| Tax payments (VAT, provisional corporate tax instalments, SDC, social insurance) | `COMMITTED` when assessed or returned; `EXPECTED` when estimated | Phase 2: user-maintained tax payment calendar (pre-filled with **curator-verified** Cyprus due dates). Phase 4: amounts from the tax module. |
| Capex commitments (approved purchase commitments) | `COMMITTED` | Payment milestones |
| Pattern-based expected receipts/payments (e.g. card sales) | `EXPECTED` | Deterministic method: trailing average by weekday/month, explicitly selected by the user with visible parameters |
| Manual adjustments | `EXPECTED` | User-entered with reason |
| Scenario overlays | `HYPOTHETICAL` | Scenario module (§8) |

**Opening balance:** the sum of bank/cash account balances at the as-of date. Each account shows its
last reconciliation date. **If a bank account is unreconciled for more than N days, the forecast displays a
data-quality warning** and does not hide it.

### 3.3 Outputs
Per bucket: opening cash, inflows by category, outflows by category, net flow, closing cash, minimum
cash requirement, headroom (closing − minimum), undrawn facilities, and **liquidity = closing cash +
undrawn facilities**. Shortfall/surplus flags appear per bucket, and the **first shortfall date** is highlighted.

### 3.4 Actual-to-forecast roll-forward ("actuals automatically update forecasts")
- On `ledger.entry.posted`, `bank.reconciled`, `openitem.changed` events, affected runs are marked **stale**.
- Rolling forecasts are **re-run automatically** (debounced, e.g. every 15 minutes or on demand) as a **new run**. Earlier runs remain available for forecast-vs-actual accuracy tracking.
- Forecast accuracy: for each elapsed week, compare the forecast made N weeks earlier vs actual (by category). Store as forecast-accuracy metrics (MAPE-style, documented).

### 3.5 Debt and interest
Loan instrument register: principal, start date, rate type (fixed / variable = reference rate +
margin), day-count convention (ACT/360, ACT/365, 30/360), repayment type (annuity, linear, bullet,
interest-only period), and payment frequency. The schedule generator is deterministic and tested against
reference amortisation tables. Variable rates use the reference-rate assumption from the active scenario.

### 3.6 Sensitivity analysis
- **One-variable sensitivity:** vary a driver (e.g. collection delay +0..+60 days, revenue ±20%) and show the impact on minimum cash and first shortfall date.
- **Tornado chart:** rank drivers by impact on a chosen output for a ±X% shock.
- Implementation: N deterministic re-runs of the engine with overrides. These are cached, not persisted as official versions.

---

## 4. Integrated three-statement projections (`projections` module, Phase 3)

### 4.1 Structure
- **Opening position:** the actual balance sheet at the cut-over date (from the ledger, mapped to the taxonomy).
- **Drivers/assumptions (per period, per scenario):** revenue growth (% or driver-based: volume × price), gross margin %, opex by line (growth %, % of revenue, fixed amount, headcount × cost), D&A (from the fixed-asset register + capex plan and useful-life policy), capex, working-capital days (DSO, DIO, DPO), tax (effective-rate assumption, or the rules engine for CY CIT from Phase 4), financing (new debt, repayments from schedules, interest rate), dividends (amount or payout %), and equity issuance.
- **Calculation order per period** (no circularity by default):
  1. Income statement down to EBIT.
  2. Interest = rate × **opening** debt balance (default; avoids circularity). An optional average-balance mode uses a fixed-point iteration with tolerance €0.01 and max 50 iterations, failing loudly if it does not converge.
  3. Tax → net income.
  4. Working-capital balances from days assumptions, and fixed assets roll-forward (opening + capex − depreciation − disposals).
  5. Debt roll-forward (opening + drawdowns − repayments).
  6. Equity roll-forward (opening + NI − dividends + issuance).
  7. **Cash flow statement (indirect method)** from NI, non-cash items and balance changes.
  8. Closing cash = opening cash + net cash flow. Optional revolver: if cash < minimum, draw on a facility up to its limit. This rule is deterministic and documented.
  9. Balance sheet assembled from the roll-forwards.

### 4.2 Integrity invariants (checked on every run; a run that fails any invariant is marked `INVALID` and cannot be published)
1. Assets = Liabilities + Equity, **exactly**, every period.
2. CF closing cash = BS cash, every period.
3. Retained earnings(t) = RE(t−1) + NI(t) − dividends(t).
4. Every BS line: opening(t) = closing(t−1). Period 1 opening = the actual BS at cut-over.
5. Debt, fixed assets and working-capital roll-forwards tie to CF statement lines.
6. Sum of monthly periods = quarterly = annual values (aggregation consistency).

### 4.3 Actual + forecast blended statements
"Full-year outlook" = actual months up to cut-over + forecast months, presented with a clear divider
and per-column nature. Actual months always come from the ledger and never from the model.

---

## 5. KPIs (`kpi` module)

### 5.1 Standard KPI library (versioned, documented formulas)
Each KPI definition has: key, name, category, formula (DSL), unit, **direction** (higher-is-better or
lower-is-better), required taxonomy mappings, averaging convention, day-count convention, "not
meaningful" conditions, and a description with a worked example.

| Category | KPI | Formula (default convention) |
|---|---|---|
| Profitability | Gross margin | (Revenue − COGS) / Revenue |
| | Operating margin | EBIT / Revenue |
| | EBITDA margin | (EBIT + D&A) / Revenue |
| | Net margin | Net income / Revenue |
| | ROA | Net income (annualised) / average total assets |
| | ROE | Net income (annualised) / average equity; NM if average equity ≤ 0 |
| Liquidity | Current ratio | Current assets / current liabilities |
| | Quick ratio | (Cash + short-term investments + receivables) / current liabilities |
| | Cash ratio | Cash & equivalents / current liabilities |
| | Cash runway (months) | Cash / average monthly net cash burn (trailing 3 months); "Not burning" if net inflow |
| Efficiency | Receivables turnover | Revenue (credit sales if tagged) / average AR |
| | DSO | Average AR / revenue × days in period |
| | DPO | Average AP / COGS (or purchases, configurable) × days |
| | Inventory turnover / DIO | COGS / average inventory; DIO = avg inventory / COGS × days |
| | Cash conversion cycle | DSO + DIO − DPO |
| Growth | Revenue / EBITDA / net profit growth | (Current − comparative) / \|comparative\|; NM if comparative = 0 |
| | Customer growth, recurring revenue growth | From **operational metrics** (non-ledger inputs, §5.3) |
| Stability | Debt-to-equity | Total debt / equity; NM if equity ≤ 0 |
| | Interest coverage | EBIT / interest expense |
| | Net debt / EBITDA | (Debt − cash) / EBITDA (LTM) |
| | DSCR | (EBITDA − cash taxes) / (principal + interest due), period configurable |

### 5.2 Custom KPIs and configuration
- Users can create KPIs in the DSL. Validation covers syntax, unit consistency, references to existing taxonomy keys, and a dry-run on the latest period.
- **Scope & approval:** personal KPIs (only visible to the creator) need no approval. Workspace-wide KPIs and changes to standard-formula conventions (e.g. DPO on purchases vs COGS) need approval by a user with `kpi.definition.approve`. KPI definitions are versioned, and historical KPI values reference the definition version used.
- Every KPI value carries its source-data breakdown (numerator/denominator components with their own drill-down).

### 5.3 Operational (non-financial) metrics
Customers, headcount, units sold, MRR and similar metrics are entered manually or imported (CSV/integration), tagged with
nature `ACTUAL` and source `MANUAL`/`IMPORT`, and versioned with audit. They are **visually marked as
non-ledger data**.

---

## 6. Goals (`goals` module)

### 6.1 Goal definition
`Goal { scope (workspace | entity | department | project | individual), metric (KPI or taxonomy metric),
target_type (absolute | relative change % | maintain ≥ / ≤ threshold), target_value, target_date,
measurement_window (e.g. FY, trailing-12, point-in-time balance), baseline {value, date, calc_run_id},
owner, materiality_threshold, linked_forecast_version (default: latest published rolling forecast) }`

Baseline is captured at creation from a calc run and frozen. Editing the target creates a new goal version.

### 6.2 Evaluations (each one is a calc run, stored)
1. **Starting value:** the frozen baseline.
2. **Target & date:** as defined.
3. **Actual progress:** the metric to date from actuals (e.g. YTD revenue), plus % of the target achieved and % of time elapsed.
4. **Likely outcome:** the projected value at the target date from the linked forecast (a blended actual + forecast series).
5. **Gap:** target − projected outcome, and target − current actual.
6. **Required performance:** a deterministic goal-seek.
   - Additive metrics (e.g. annual revenue): required remaining amount = target − actual to date, so the required run-rate = remaining / remaining periods. This is compared with the forecast run-rate and the historical run-rate.
   - Ratio metrics (e.g. 20% EBITDA margin): the required EBITDA given forecast revenue, **or** the required revenue given forecast cost base (both shown; the assumption held constant is stated).
   - Balance thresholds (e.g. cash ≥ €100k): the first projected breach date and the minimum additional inflow or cost reduction needed.
   - Generic: bisection over a chosen driver on the projection model, with tolerance and max iterations. "Not achievable within driver bounds" is reported explicitly.
7. **Trends:** the metric series (actual + forecast, nature-encoded) and the trend of the gap.
8. **Alerts:** when the projected gap exceeds the materiality threshold, the status changes (on track → at risk → off track), or a threshold breach is forecast. Delivered in-app (and by email later).
9. **Scenario testing:** evaluate the goal against any scenario. Results are shown side by side.
10. **Driver explanation:** a deterministic **contribution analysis**. For additive metrics, each taxonomy line's variance vs plan/prior is decomposed. For ratios, a documented decomposition is used (e.g. Δmargin into a revenue effect and a cost effect, with the residual shown explicitly). The AI can narrate this analysis in Phase 5 but does not produce it.

Status rules (default, configurable): on track if projected ≥ target (direction-adjusted); at risk if
within the materiality threshold; off track otherwise.

---

## 7. Budgeting & variance (`budgeting` module)

- **Budget** (FY, entity, type: annual / departmental / project), **budget version** (lifecycle `DRAFT → SUBMITTED → APPROVED → LOCKED`, `SUPERSEDED`), and **revisions** as new versions with reasons. The "original budget" and the "current approved budget" are both kept and reportable.
- **Lines:** taxonomy line or account × dimension (department/project/cost centre) × period (month). Quarterly/annual values are always aggregates of monthly values.
- **Phasing methods:** even, prior-year seasonal profile (from actuals), custom profile, manual entry, driver-based (headcount × salary). The method used is stored per line.
- **Inputs:** a grid UI and an Excel template import with validation (unknown accounts, non-numeric values, periods outside the FY, formula-injection-safe parsing), plus an import preview with diff before saving.
- **Approval:** via the workflow module, with SoD configurable. Approved versions are immutable (DB trigger).
- **Variance analysis:**
  - Budget vs actual, forecast vs actual, budget vs forecast, actual vs prior year. Absolute and %.
  - Favourable/unfavourable determined by the line's direction (revenue up = favourable, expense up = unfavourable).
  - Periods: month, QTD, YTD, full-year outlook (blended).
  - **Variance explanations:** variances above a threshold (absolute and %) require a comment from the line owner before the management pack can be finalised. Explanations are versioned and attributed.
  - Actuals always come from posted ledger entries (P1). Unposted drafts are excluded and shown as a count warning.
- **Performance alerts:** budget overrun thresholds per line/department, and trend alerts (3 consecutive unfavourable months).

---

## 8. Scenario modelling (`scenarios` module)

- **Scenario** = a base (budget version, forecast version, or the current projection model) + an **ordered list of assumption overrides**. Scenario outputs are always `HYPOTHETICAL`.
- **Override types** (each a typed, validated object, so free-form code is not allowed):
  | Type | Example | Parameters |
  |---|---|---|
  | Driver % change | Revenue +20% / −15% | target line(s), %, start/end period |
  | Driver absolute change | Payroll +€8k/month | line, amount, periods |
  | Timing shift | Major customer pays 60 days late | counterparty or line, shift days, period |
  | New financing | New loan €200k | instrument terms → generates schedule |
  | New hire | 1 FTE from March | department, gross salary, employer social-insurance % (verified parameter), start date |
  | Investment / capex | €150k equipment | amount, date, useful life, funding source |
  | One-off cash event | Unexpected tax payment €40k | amount, date, P&L treatment (expense / liability settlement) |
  | Rate change | Interest rate +2pp | instrument(s), from date |
- **Outputs compared with the base:** cash flow (13-week and monthly), P&L, BS, liquidity (minimum cash, first shortfall), ratios/KPIs, goal statuses, debt metrics (DSCR, covenants if entered), and a stability summary.
- **Traceability:** every changed output value lists the override IDs that affected it (lineage). A "what changed and why" table is available per scenario.
- Scenarios never modify budgets or forecasts. Promoting one requires an **explicit "create budget/forecast draft from scenario"** action, which enters the normal approval workflow.

---

## 9. Management reporting (`mgmt_reporting` module)

- **Report pack templates:** executive overview, revenue & profitability, cash flow & projections, working capital, budget performance, KPI scorecard, forecast statements, risks, goal progress, and commentary.
- **Generation creates a frozen snapshot** (all figures + references to the calc runs, plan versions and ledger watermark used). Packs are reproducible and immutable once finalised. Draft → review → final workflow.
- **Comparison columns:** actual, budget (original/current), forecast, prior year, and variances, for user-selected periods.
- **Commentary:** human-authored. In Phase 5, AI drafts are inserted as **labelled AI drafts** that need human acceptance and editing.
- **Exports:**
  - XLSX (values with number formats; optionally a formulas sheet; injection-safe; a nature column and legend)
  - PDF (branded, with page numbering, a provenance footer of "Actuals as of {date}, ledger watermark {n}; Budget v{n}; Forecast run {id}", and a draft watermark until final)

  Export values must equal on-screen values exactly (tested).

## 10. Dashboard (`dashboards` module + frontend)

- **Workspace-specific dashboards** (firm portfolio, business CFO, personal). Each is a grid of **configurable widgets** (KPI card, trend chart, 13-week cash chart, waterfall, budget vs actual table, goal progress, scenario comparison, alerts list, and a top-variances list).
- Widget configuration is stored per user, and workspace defaults can be set by an admin. Each widget has a declared data query (metric, period, comparison, scenario).
- **Drill-down path:** KPI → statement line → taxonomy line → account → journal entries → source document. Permissions are checked at every step.
- **Period controls:** a preset (MTD, QTD, YTD, LTM, custom) and comparisons (budget, forecast, PY).
- **Performance targets:** dashboard initial load p95 < 1.5 s for an entity with 3 years of history, using precomputed actuals aggregates and cached calc runs.
- **Charting:** Apache ECharts (Apache-2.0) for interactive charts, and a data grid (AG Grid Community, MIT, or TanStack Table) for tables.

### 10.1 Visual separation of actual vs forecast (mandatory UI contract)
| Nature | Encoding |
|---|---|
| ACTUAL | Solid line or filled bar, primary colour |
| COMMITTED | Solid outline bar, secondary tone |
| EXPECTED / FORECAST | Dashed line or hatched bar |
| HYPOTHETICAL (scenario) | Dotted line, distinct hue, scenario name in the legend |
| BUDGET / TARGET | Thin reference line or marker |

Additional rules:
- A vertical "today / cut-over" marker appears on every time chart. Tooltips always state the nature and source run.
- Colour is never the only encoding (accessibility).
- KPI cards state "Actual", "Forecast" or "Blended" explicitly.

## 11. Personal finance features (customer type C)
These reuse the same engines with a simplified UX and a personal taxonomy:
- Accounts (bank, cash, card, savings, investments, property, loans/mortgage), with transactions categorised into income/expense categories. Double entry runs underneath but is hidden by default.
- Net-worth statement (assets − liabilities), personal cash flow, budgets by category, goals (emergency fund, savings target, debt payoff date), and a 12/24-month personal cash projection with scenarios (salary change, new loan, large purchase).
- **No tax-filing features for individuals in the current roadmap.** Personal tax estimation is a later, separate decision.
- Investment valuations are user-entered (`EXPECTED` or valuation-dated `ACTUAL`). There are no market-data feeds in scope.

## 12. AI CFO assistant (Phase 5, design constraints fixed now)
- The AI answers through **tool calls into deterministic services**: `get_metric_series`, `get_variance_breakdown`, `get_contribution_analysis`, `run_scenario_sandbox` (unsaved, HYPOTHETICAL), `goal_seek`, `get_kpi_trends`, `get_cash_forecast`, and `search_verified_sources`. All tools are read-only and scoped to the user's permissions.
- **Every number in AI output must come from a tool result.** The output validator matches numbers in the text against tool outputs (with tolerance only for displayed rounding), and unmatched numbers are removed and flagged.
- The UI renders AI output in a distinct **"AI analysis (draft)"** panel. Verified figures appear as clickable chips linking to their calc run, and uncertainty statements are required when data is incomplete (e.g. unreconciled bank, unmapped accounts, stale forecast).
- Example: "How much more revenue for a 20% EBITDA target?" → `goal_seek(metric=EBITDA_margin, target=0.20, driver=revenue, hold=cost_base)` → the AI explains the deterministic result and its assumptions.
- The AI can propose scenarios. Saving a proposed scenario requires a user click.

## 13. Known limitations (planned)
No stochastic/Monte Carlo forecasting in early phases (possible later, seeded and labelled). No ML-based
predictions in the calculation path (an optional suggestion layer may come later, always labelled). No
consolidation of multiple entities in projections until consolidation exists. No live market data. No
automatic bank feeds (PSD2 aggregation is a separate later decision with regulatory implications).
