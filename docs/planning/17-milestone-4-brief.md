# 17 — Milestone 4 Implementation Brief: budgets, KPIs, goals and the CFO dashboard

Status: **IN PROGRESS** (product owner go-ahead 2026-11-04: "Let continue", after the Milestone 3
report). Backlog: [08 §M4](08-implementation-backlog.md). Specification: [10](10-cfo-fpa-specification.md)
§5–§7 and §10 (approved). Acceptance: [12](12-fpa-testing-and-acceptance.md) §4.3–§4.6 (approved).

## 1. Business purpose
Milestone 3 answered "will we have enough cash?". Milestone 4 answers the next questions:
- **"Are we on plan?"** Budgets with an approval trail, and variance against actuals that says
  whether each difference is good or bad.
- **"How healthy are we?"** A documented KPI library whose every value can be explained down to
  the accounts and entries behind it.
- **"Will we reach our goals, and what would it take?"** Goals with a frozen baseline, a likely
  outcome, the gap and the required performance.
- **"Show me on one page."** A CFO dashboard, and a portfolio view for firms.

Everything is built on the Milestone 3 framework: one calendar, a nature on every number,
reproducible calculation runs with lineage, and the sandboxed formula language.

## 2. Rules carried from the approved specification (doc 10 §1)
- **P1:** actuals come from posted ledger entries only, through `reporting`. Budgets, KPIs and goals
  never store their own copy of actuals. Unposted drafts are excluded, and their count is shown as a
  warning.
- **P2/P3:** budget values have nature `BUDGET`, goal targets `TARGET`, and outcomes that combine
  actuals with budget or forecast are explicit blends with a cut-over date.
- **P4/P5:**
  - variance, KPI and goal evaluations are calculation runs (reproducible, hashed, pinned to a
    ledger watermark);
  - approved budget versions and KPI definition versions never change.
- **P6:** every KPI value and goal figure can be explained (lineage).
- **P7:** Decimal throughout. Budget phasing rounds each month to cents once (§3); ratios are stored
  unrounded.
- **P9:** AI is never the calculator.

## 3. Defaults taken (change them any time)
| Question | Default in M4 |
|---|---|
| Budget scope | A budget belongs to one entity and one fiscal year, and has a type: annual, departmental or project. Departmental and project budgets name one dimension value (from M2-1). |
| Budget lines | A line is a **taxonomy line** (M2-6, e.g. `REV.SALES`) or a **postable account**, optionally with a dimension value, and holds 12 (or as many as the fiscal year has) monthly amounts. Quarterly and annual values are always sums of months. |
| Sign convention | Lines are entered as **positive amounts in their natural direction** (revenue as income, expenses as cost). Direction comes from the taxonomy line or account type, not from the sign. |
| Lifecycle | `DRAFT → SUBMITTED → APPROVED → LOCKED`. A submitted version can be **returned to draft** with a comment. A **revision** starts from an approved or locked version and is a new draft with a reason. When it is approved, the previous approved version becomes `SUPERSEDED`. |
| Original and current budget | The **original** budget is the first version ever approved; the **current** budget is the latest approved or locked one. Both are kept and reportable. |
| Locking | Locking marks an approved version as the year's fixed baseline. Revisions can still be made after a lock (the locked version stays as it is and is superseded when a revision is approved). |
| Segregation of duties | **On by default:** the person who submitted a version cannot approve it. It can be switched off per entity for one-person businesses; the setting is audited, and each approval records whether SoD applied. Approval also needs the `budget.approve` permission (finance manager, partner, owner). |
| Immutability | Enforced by database triggers, as for posted entries: lines can be changed only while their version is a draft, and a version's content never changes after submission. Only the documented status changes are allowed. |
| Phasing (M4-2) | Methods: even, prior-year seasonal (from posted actuals of the previous fiscal year), custom profile (weights), manual, and driver-based (quantity × rate per month). Each month is rounded to cents (half up) once; the **rounding residual goes to the last month**, so months always sum exactly to the annual input. The method is stored per line. If the prior year has no actuals for a line, seasonal phasing falls back to even, with a note. |
| Excel import (M4-2) | Our own template (`.xlsx`, one sheet, one row per line, one column per month). Validation and preview with a diff before anything is saved. Limits: 5 MB, 5,000 rows. Formulas are **rejected**, and text starting with `=`, `+`, `-` or `@` is rejected with a row-level message; nothing is ever evaluated. Exports neutralise such text with a leading apostrophe. |
| Department-scoped owners (M4-2) | A budget can name an **owner per dimension value** (e.g. the sales manager for the Sales department). A user whose access to a budget comes only from being a department owner sees and edits only that department's lines, in the API, grid, export and dashboard. |
| Variance (M4-3) | Variance = actual − budget (or − forecast, − prior year). Revenue above plan is favourable and expenses above plan are unfavourable, from the line's direction. % = variance ÷ \|comparison\|; "not meaningful" when the comparison is 0. Periods: month, quarter to date, year to date, and a full-year outlook (actuals to date blended with the budget for the remaining months, labelled). |
| Dimension actuals (M4-3) | Department and project actuals are read from posted lines by dimension value through a new `reporting` function, pinned to a watermark. Lines without that dimension are not counted for a departmental budget. |
| Explanation threshold (M4-3) | An explanation is required when **\|variance\| ≥ €1,000 and \|variance %\| ≥ 10%** (both per entity settings). Explanations are versioned and attributed. A period review cannot be marked complete while one is missing. |
| KPI conventions (M4-4) | Average balances are the mean of opening and closing balances for the period. Days are the calendar days in the period. Annualised values are × 365 ÷ days. Cash runway uses the trailing 3 full months of net cash movement. DPO uses COGS by default (purchases as a workspace-approved alternative). Each convention is written in the KPI definition. |
| KPI library (M4-4) | Core set from backlog M4-4: gross, operating, EBITDA and net margin; current, quick and cash ratio; cash runway; DSO, DPO, DIO and cash conversion cycle; revenue, EBITDA and net profit growth; debt-to-equity; interest coverage. Definitions are versioned data with a worked example each. ROA, ROE, net debt/EBITDA and DSCR follow the same pattern and are added where their inputs exist. |
| Custom KPIs (M4-5) | Written in the M3 formula language. **Personal** KPIs are visible only to their creator and need no approval. **Workspace** KPIs need approval by someone with `kpi.definition.approve` other than the author. Historical values reference the definition version used. |
| Operational metrics (M4-5) | Entered manually per month (customers, headcount, units, MRR, …), nature `ACTUAL`, source `MANUAL`, versioned with audit, and labelled "not from the ledger" wherever shown or exported. CSV import comes later. |
| Goal projection (M4-6) | There is no rolling P&L forecast until the projections module (Phase 3). The **likely outcome** of a P&L goal is therefore actuals to date **blended** with the current approved budget for the remaining months; without a budget it is the trailing 3-month run rate. The method is stated. Cash goals use the latest 13-week forecast. |
| Goal-seek (M4-6) | Additive, ratio and balance-threshold goals use the closed-form rules in doc 10 §6.2. The generic case bisects a uniform % change of one chosen taxonomy line on the blended projection, within ±100%, to €0.01 or 0.01 percentage points, in at most 60 iterations; otherwise "not achievable within bounds". |
| Goal status (M4-6) | On track when the projected outcome meets the target (direction-adjusted); at risk when it misses by no more than the materiality threshold (default 5% of the target); off track otherwise. |
| Golden workbook (AC-GO2) | As in M3: an independently computed reference fixture for the six sample goals on Demo Trading. **Sign-off by a finance professional is an owner item**; until then it is marked "not yet signed off". |
| Alerts (M4-7) | In-app only (email later). Each alert has a key (goal, line, threshold), so an alert is raised when a status changes and **not raised again while it stays the same**. Users acknowledge alerts; alerts are kept. Budget overrun and "3 consecutive unfavourable months" alerts use the M4-3 thresholds. |
| Dashboard (M4-8) | Widgets: KPI cards, 13-week cash chart, budget vs actual table, goal progress, alerts and top variances. The layout is saved per user, with a workspace default. Charts stay **SVG drawn in React** (no new dependency), as in M3. Doc 10 names Apache ECharts; this is listed for owner confirmation. |
| Firm portfolio (M4-9) | Engagement grants to client-owned workspaces arrive in M5-4. In M4 the portfolio covers the **client entities in the firm's own workspace that the user can access** (entity-scoped roles), with per-client summary metrics, computed per entity under the user's permissions; no cross-tenant query. Revocation removes the client from the view on the next request. |

## 4. Order and approach
| # | Item | Issue | Approach |
|---|---|---|---|
| 1 | M4-1 Budgets | #65 | `budgeting` module: budgets, versions (lifecycle, SoD, returned-to-draft, revisions with reasons, supersedes), monthly lines (taxonomy line or account × dimension value × month); immutability triggers; original and current budget; API, UI and audit. |
| 2 | M4-2 Grid, phasing, Excel | #66 | Budget grid (keyboard friendly, totals by quarter and year), phasing methods (§3), hardened Excel import with preview and diff, Excel export, department-scoped owners (AC-BU6). |
| 3 | M4-3 Variance | #67 | Budget vs actual, forecast vs actual, budget vs forecast, actual vs prior year; direction-aware; month, QTD, YTD, full-year outlook; thresholds; explanation workflow; draft-entry warning; dimension actuals in `reporting`. |
| 4 | M4-4 KPI library | #68 | `kpi` module: versioned definitions in the formula language, conventions, NM handling, a KPI set as a calc run with numerator and denominator lineage and drill-down. |
| 5 | M4-5 Custom KPIs, operational metrics | #69 | Personal and workspace KPIs (approval), validation and dry-run; operational metrics entry, labelled as non-ledger data. |
| 6 | M4-6 Goals | #70 | `goals` module: versioned goals with frozen baselines, evaluations as calc runs (actual to date, likely outcome, gap, required performance, status, trend, contribution analysis), goal-seek, golden fixture. |
| 7 | M4-7 Alerts | #71 | In-app alerts with de-duplication and acknowledgement, raised by goals and budget thresholds. |
| 8 | M4-8 CFO dashboard | #72 | Widget grid per user, period presets and comparisons, nature visual contract in light and dark themes, drill-down within permissions, table alternatives, performance check on a 3-year fixture. |
| 9 | M4-9 Firm portfolio | #73 | Per-client summary across the entities the user can access (§3). |
| 10 | M4 report | — | Milestone report with evidence per acceptance criterion and the owner items. |

Every item follows the established patterns:
- tenant-owned models with FORCE row-level security and composite keys;
- a permission on every route;
- an audit event per change;
- problem+json errors and Decimal money;
- OpenAPI regenerated;
- live checks for UI;
- English and Greek;
- planning modules never import the ledger.

## 5. Acceptance criteria
- **Budgets and variance:** AC-BU1 to AC-BU6 (doc 12 §4.3).
- **KPIs:** AC-KP1 to AC-KP5 (doc 12 §4.4).
- **Goals:** AC-GO1 to AC-GO5 (doc 12 §4.5). AC-GO2 is met against the reference fixture, with
  professional sign-off pending (§3).
- **CFO dashboard:** AC-DB1 to AC-DB6 (doc 12 §4.6). AC-DB6 covers firm-workspace client entities
  in M4, and engagement grants once they exist (M5-4).

## 6. Risks
| Risk | Mitigation |
|---|---|
| Budget treated as actuals, or actuals edited in a budget | Nature `BUDGET` on every value; actuals read only through `reporting`; no write path to the ledger (import contract) |
| An approved budget quietly changed | Database triggers; revisions only as new versions with reasons; original kept |
| Spreadsheet injection through import or export | No formula evaluation; reject formulas and dangerous leading characters; neutralise on export; size limits; fuzz tests |
| A KPI shown as 0 or ∞ when it is not meaningful | Safe division in the formula language (M3-3); "Not meaningful" with a reason in every display |
| Goal outcomes read as predictions | The method is stated (blended with budget, or run rate), the nature is shown, and the cut-over date is marked |
| Scope (three L items) | One PR per issue in the order above; each PR stands alone |
