# Milestone 4 report: budgets, KPIs, goals and the CFO dashboard

Status: **complete, awaiting product owner review** (PRs #120–#128, stacked after Milestone 3;
each is reviewable on its own). No environment exists beyond local development and CI, and no
migration has been applied anywhere else. Brief:
[planning doc 17](planning/17-milestone-4-brief.md); specification: planning docs 10 and 12, on the
planning branch (PR #1), which is not yet merged.

## What you can do now
On top of Milestones 1 to 3, you can:
- **Budget.** Create annual, departmental or project budgets for a fiscal year.
  - Enter them in a grid, phase annual amounts (even, last year's pattern, a profile, or
    quantity × rate), or import them from our Excel template, with a preview before saving.
  - Submit and approve them with segregation of duties, lock them, and revise them with a reason.
    The original and the current budget are both kept.
  - Name department owners who see and edit only their department.
- **Compare with plan.** See budget vs actual, actual vs last year, and the current vs the original
  budget, for the month, quarter to date, year to date or the full-year outlook.
  - Every difference says whether it is favourable.
  - Large ones need an explanation before the month's review can be completed.
- **Track KPIs.**
  - A documented library of 19 KPIs: margins, liquidity, DSO/DPO/DIO, growth, leverage, coverage.
  - Each value can be explained down to the accounts and entries behind it, and says in plain words
    when it is not meaningful.
  - Write your own KPIs: personal ones, or workspace ones that someone else approves.
  - Enter operational figures such as headcount, labelled as not from the ledger.
- **Set goals.**
  - Targets such as revenue 500,000, an EBITDA margin of 20%, cash that stays above 100,000,
    net profit +15% or operating costs −10%.
  - The baseline is frozen when the goal is created.
  - Each evaluation shows the actual to date, the likely outcome (actuals, then the budget or the
    run rate; cash from the 13-week forecast), the gap and the status.
  - It also shows what it would take: the run rate, or the numerator, or the % change of a line,
    or "not achievable".
  - A contribution analysis explains the difference line by line.
- **Get alerts.** In-app alerts when a goal falls behind or a threshold is breached, and when a
  budget line is unfavourable beyond the thresholds or for 3 months in a row. The same alert is
  never raised twice in a row. Acknowledge it with a note.
- **See it on one page.**
  - The **CFO dashboard** shows KPI cards, 13-week cash, budget vs actual, top variances, goals and
    alerts, for one period and comparison.
  - You choose your own layout; finance managers set the workspace default.
  - In a firm workspace, the **firm portfolio** lists every client you can access, with its key
    figures.

Try it with `make demo` ([demo script](demo.md)). Its 23 steps now include Budget 2027, the six
sample goals, the alert they raise and the dashboard. The last step shows that the portfolio is
refused in a business workspace, because it exists in firm workspaces only. User guides:
[budgets](user-guide/budgets.md), [KPIs](user-guide/kpis.md), [goals](user-guide/goals.md),
[alerts](user-guide/alerts.md) and [dashboard and portfolio](user-guide/dashboard.md).

## Items
| Item | PR | What |
|---|---|---|
| M4-1 Budgets | #120 | budgets, versions (lifecycle, SoD, returned to draft, revisions with reasons, superseded), monthly lines; immutability triggers; original and current (ADR-0022) |
| M4-2 Grid, phasing, Excel | #121 | grid with quarter and year totals; phasing methods with the residual on the last month; hardened `.xlsx` import (no formulas, no dangerous prefixes, limits) with preview and diff; export; department owners (ADR-0023) |
| M4-3 Variance | #122 | budget vs actual, actual vs prior year, current vs original; month, QTD, YTD, full-year outlook; direction-aware; thresholds; versioned explanations; period review (ADR-0024) |
| M4-4 KPI library | #123 | CORE@1.0, 19 KPIs as versioned reference data; KPI sets as calculation runs with account lineage and drill-down (ADR-0025) |
| M4-5 Custom KPIs, operational metrics | #124 | personal and workspace KPIs (approval by someone else), checks and dry run; operational metrics labelled not from the ledger (ADR-0026) |
| M4-6 Goals | #125 | versioned goals with frozen baselines; evaluations as runs (actual, likely outcome, gap, status, goal-seek, trend, contribution analysis); golden fixture (ADR-0027) |
| M4-7 Alerts | #126 | in-app alerts keyed by condition, raised only on a change of state; goal status and breach, budget overrun and 3-month trend; acknowledgement (ADR-0028) |
| M4-8 CFO dashboard | #127 | widgets for one period and comparison from the reports; layouts per user with a workspace default; SVG charts with the nature contract and table alternatives (ADR-0029) |
| M4-9 Firm portfolio | #128 | per-client summary for the entities the user can access, computed per request (ADR-0030) |

## Acceptance criteria (brief §5; doc 12 §4.3–4.6)
| AC | Evidence |
|---|---|
| AC-BU1 lifecycle, SoD, DB immutability, revision with reason, original reportable | `tests/budgeting/test_budgets.py` (lifecycle with revision; SoD configurable and refused by a DB constraint; DB refuses changes to submitted and approved versions) |
| AC-BU2 phasing sums exactly to the annual input, residual on the last month | `tests/budgeting/test_phasing.py` (property tests for every method, including tiny amounts and sign flips) |
| AC-BU3 Excel import validates and previews; row-level messages; `=`, `+`, `-`, `@` never evaluated | `tests/budgeting/test_grid.py` (unknown lines, non-numeric, out of year, formulas, macros, archive checks, size and row limits); export neutralises dangerous text |
| AC-BU4 posted entries only (draft count as a warning); direction-aware sign | `tests/budgeting/test_variance.py` (revenue and expense, unposted warning) |
| AC-BU5 explanation required above the threshold before the review completes; versioned, attributed | `tests/budgeting/test_variance.py` (review refused, then completed; explanation history) |
| AC-BU6 department owners see and edit only their department (API, grid, export, dashboard) | `tests/budgeting/test_grid.py` (API, grid, export); department owners have no dashboard access in M4 (no `planning.read`), so nothing beyond their department is shown |
| AC-KP1 each core KPI matches a hand-computed value | `tests/kpi/test_kpis.py`: all 19 on a hand-worked fixture |
| AC-KP2 not-meaningful cases with plain reasons | the same file: zero denominators, negative equity, zero comparatives, no cash burn |
| AC-KP3 numerator/denominator components and drill-down to accounts and entries | lineage per account; the KPI page drills to accounts and entries (live check) |
| AC-KP4 workspace KPIs need approval, are versioned, values reference the version | `tests/kpi/test_custom.py` (approval by another user, DB refuses self-approval, versions in KPI sets) |
| AC-KP5 operational metrics are versioned, audited and labelled non-ledger | `tests/kpi/test_custom.py`; NON_LEDGER dimension and MANUAL lineage; label in the UI |
| AC-GO1 baseline frozen; a new target is a new version | `tests/goals/test_goals.py` (baseline copied unchanged; DB refuses changing a version or deleting it) |
| AC-GO2 the six sample goals match the reference fixture | **Met against the fixture, sign-off pending.** `test_golden_six_sample_goals` checks every figure against values worked out by hand in its docstring; the demo sets the six goals on Demo Trading |
| AC-GO3 goal-seek reports "not achievable within bounds"; the held assumption is stated | `test_goal_seek_reports_not_achievable_within_bounds`; lineage notes state what is held |
| AC-GO4 alert when the status crosses into at risk / off track or a breach is forecast; not re-raised while unchanged | `tests/dashboards/test_alerts.py` (off track → unchanged → on track → at risk; breach) |
| AC-GO5 contribution components sum to the total, residual explicit | goal runs carry an invariant; the golden test checks a ratio's residual |
| AC-DB1 nature visual contract in charts and tables, light and dark | non-colour encodings and table alternatives, tested structurally in `dashboard.test.tsx`; light and dark screenshots in the live check (pixel snapshots in CI: owner decision, below) |
| AC-DB2 cut-over marker on time charts; KPI cards state their nature | the dashboard cash chart marks the forecast's as-of date; KPI cards show their nature (`dashboard.test.tsx`) |
| AC-DB3 drill-down within permissions; clear denials | widgets report `denied`; drill-down uses the existing pages and their permissions (live check: KPI → accounts → entries) |
| AC-DB4 presets and comparisons update every widget; values equal the reports | `tests/dashboards/test_dashboard.py` (budget rows equal the variance report line for line; KPI cards equal the KPI set; one period for all widgets) |
| AC-DB5 p95 < 1.5 s on a 3-year fixture; axe; non-colour encodings; table alternatives | `test_response_time_on_a_three_year_fixture` in CI; axe on every new screen; about 0.7 s in the browser on the demo |
| AC-DB6 firm portfolio shows only granted clients; revocation removes them and their metrics | `tests/dashboards/test_portfolio.py` (entity-scoped access, grant, revoke, gone on the next request; nothing stored; refused outside firm workspaces) |

## Database changes (Milestone 4)
| Module | Migrations | Content |
|---|---|---|
| budgeting | 0001–0006 | budgets, versions, lines, amounts, events, settings, owners, explanations, reviews; lifecycle and content triggers; SoD constraint |
| ledger | 0016 | dimension value key per entity (for same-entity budget lines) |
| kpi | 0001–0004 | KPI library (read-only reference data, seeded); custom KPIs, operational metrics and values with guards |
| metrics | 0005 | (entity, run) key on calculation runs |
| goals | 0001–0002 | goals, versions (frozen baseline), evaluations (append-only); guards |
| dashboards | 0001–0004 | alerts and alert states (guards), dashboard layouts |

Every new tenant table has FORCE row-level security and composite tenant keys. Migrations were
applied locally only.

## Security controls added
- **Plans never change silently.**
  - Database triggers keep submitted and approved budget versions, KPI versions, goal versions
    (with their baselines) and alerts as they are; only the documented status changes are allowed.
  - Segregation of duties is enforced in the service and by a database constraint, for budgets and
    for workspace KPIs.
- **Spreadsheets are data.** The import never evaluates formulas and rejects dangerous prefixes,
  macros and oversized files. The export neutralises dangerous text.
- **Formulas cannot run code.** Custom KPIs use the sandboxed M3 language.
- **Least privilege.**
  - New permissions: `budget.*`, `kpi.definition.*`, `kpi.operational.manage`, `goal.manage`,
    `alert.acknowledge`, `dashboard.manage_default`.
  - Department owners see only their department.
  - Widgets and alerts follow the permission of their source.
  - The portfolio is computed per entity under the user's own permissions, with no cross-tenant
    query and nothing stored.
- **Planning code never imports the ledger** (import contract). Actuals come only from `reporting`.

## Quality
Measured on 2026-11-10 on the M4 branches (`make test`, fresh database):
- Backend: **1,153 tests pass**; **97.0%** line coverage overall.
- Frontend: **52 tests**, including axe on every new screen; ESLint strict, `tsc`, build.
- Every PR's CI is green on its head: lint, mypy strict, import contracts, migrations, OpenAPI
  drift, Semgrep, gitleaks, pip-audit, IaC, prove-gates, container smoke.
- **Live checks** with MFA sign-in on the local stack for every screen, on the demo data. They and
  the tests found and fixed, among others:
  - phasing that left the last month with the opposite sign for tiny amounts;
  - read-only users getting 404 instead of 403 on budgets;
  - duplicate React keys that left stale editors on screen;
  - a KPI engine sign error on expense lines;
  - KPI sets never showing as out of date;
  - a goal's prior-year comparison that left out months after the cut-over;
  - ratio gaps in alerts shown as raw fractions;
  - links squeezed by a global card style;
  - and, while writing this report, a missing as-of marker and nature label on the dashboard
    (AC-DB2), and a portfolio that was not yet limited to firm workspaces (doc 11 §5).

## Known limitations
- **Golden figures need sign-off** by a finance professional (AC-GO2), as in M3 (AC-CW5).
- **Goal projections are simple until M6.** Outcomes use the approved budget or a 3-month run rate,
  and balances after the cut-over are held at their latest value. The method is shown with every
  outcome. Scenario testing of goals is in M7.
- **Budget alerts are checked on request** (Alerts page, dashboard refresh). A scheduled check and
  email delivery are planned for M8.
- **Department owners** do not see alerts, the dashboard or the portfolio in M4.
- **Comparisons with a forecast** (P&L) wait for rolling forecasts in M6.
- **The portfolio** covers entities in the firm's own workspace; engagement grants to client
  workspaces come in M5-4.
- **Greek wording** needs a native speaker's review.

## Decisions and approvals needed from you
1. **Review and merge**, in order:
   - PR #1 (planning documents, including docs 10 and 12);
   - the earlier stacks;
   - #120–#128 and this report.
2. **ADRs to accept or change:** 0022 (budget lifecycle), 0023 (phasing and spreadsheet import),
   0024 (variance), 0025 (KPI library), 0026 (custom KPIs and operational metrics), 0027 (goals),
   0028 (alerts), 0029 (dashboard), 0030 (firm portfolio).
3. **Defaults to confirm** (brief §3):
   - the explanation thresholds (€1,000 and 10%);
   - DPO on cost of sales;
   - the goal materiality of 5%;
   - year-to-date budget overruns for alerts;
   - the default KPI cards on the dashboard.
4. **Sign-offs:**
   - the golden goal figures (AC-GO2) and the golden 13-week forecast (AC-CW5);
   - Greek wording.
5. **Charts and snapshots:**
   - confirm SVG drawn in React instead of Apache ECharts (no new dependency);
   - decide whether pixel snapshot tests should run in CI (they need a pinned browser image).
6. **No AWS changes and no new dependencies** in Milestone 4.

Milestone 5 (personal MVP and pilot readiness, Gate P) waits for your review of this milestone.
