# Progress Tracker

> Work is tracked in **GitHub Milestones and Issues** (one issue per backlog item; process:
> `docs/PROCESS.md`). This file is the quick summary and the branch map for resuming work.

The single place to see where implementation stands. It is updated with every PR, so nothing
depends on a chat session. Until 2026-11-16 branches were stacked (each PR targeted the previous one); since the
consolidation every new PR targets `main`.

## Status (updated 2026-11-22)

**Milestones 7 and 8 are merged into `main`** (2026-11-22; the owner asked the developer to merge
each PR in order once its checks passed: #183–#189, then #196–#202). **Version 1 in progress**:
a complete platform for the owner's own use, on the owner's computer, with one-person approvals
and Cyprus VAT return preparation (brief `docs/planning/24-version-1-brief.md`, approved
2026-11-22). Gate G is not needed for version 1 and is deferred (brief 23). Nothing is created on
AWS.

### Earlier status (2026-11-16)

**Repository consolidated (2026-11-16, owner approval).** The 72 pull requests from #1 to #162
were merged into `main` in dependency order, with merge commits only (no squash, rebase or force
push). `main` contains the 27 planning documents of #1 unchanged and Milestones 0 to 6 with the
Milestone 6 follow-up. Checks on `main`: CI green; 1,238 backend tests (96.02% coverage) and 64
frontend tests pass; lint, OpenAPI, security (Semgrep 0 findings, gitleaks no leaks) and
`fcp.devtools.validation --check` (6 scenarios) pass. Issues #78 (Gate P) and #153 (professional
review) stay open by owner decision. **Milestone 7 in progress** (brief `docs/planning/21-milestone-7-brief.md`; owner,
2026-11-16: "Continue as you think it's better", so the brief's defaults are taken).


**Milestone 1 is complete** (see `docs/milestone-1-report.md`). **Milestone 2 is complete and
awaits review** (see `docs/milestone-2-report.md`; go-ahead 2026-11-03: "continue developing
according to our existing roadmap"). **Milestone 3 is complete and awaits review** (see `docs/milestone-3-report.md`; owner: "Continue",
2026-11-04; brief `docs/planning/16-milestone-3-brief.md`). **Milestone 4 is complete and awaits review** (see `docs/milestone-4-report.md`; owner: "Let continue",
2026-11-04; brief `docs/planning/17-milestone-4-brief.md`). **Milestone 5 is complete and awaits review** (see
`docs/milestone-5-report.md`; owner, 2026-11-10: "continue with what is easier for now for best
coding"; brief `docs/planning/18-milestone-5-brief.md`). **Nothing was created on AWS; the pilot
environment waits for the owner's approval (Gate P).** **Milestone 6 is complete and awaits review** (see `docs/milestone-6-report.md`; owner,
2026-11-12 and 2026-11-15: "Continue"; brief `docs/planning/19-milestone-6-brief.md`). **Milestone 6 follow-up in progress** (owner decisions
2026-11-15: accounting correctness before speed; the projection engine is not production-ready
until validated and signed by a qualified professional; brief
`docs/planning/20-milestone-6-follow-up-brief.md`). Cloud-readiness review:
`docs/reviews/2026-11-03-cloud-readiness.md`; AWS target: `docs/deployment/aws.md`.

| Item | Branch | PR | State |
|---|---|---|---|
| Planning set v2 + decisions | `claude/initial-planning-docs` | #1 | Merged 2026-11-16 |
| M0-1 Repo layout | `claude/m0-1-repo-layout` | #2 | Merged 2026-11-16 |
| M0-2 CI gates | `claude/m0-2-ci` | #3 | Merged 2026-11-16 |
| M0-3 Local dev services | `claude/m0-3-local-dev` | #4 | Merged 2026-11-16 |
| M0-4 Money library | `claude/m0-4-money` | #5 | Merged 2026-11-16 |
| M0-5 Errors and logging | `claude/m0-5-errors-logging` | #6 | Merged 2026-11-16 |
| M0-6 Synthetic data | `claude/m0-6-synthetic-data` | #7 | Merged 2026-11-16 |
| M0-7 Terraform skeleton | `claude/m0-7-iac-skeleton` | #8 | Merged 2026-11-16 |
| M1-1 OIDC sign-in, MFA, sessions | `claude/m1-1-auth` | #9 | Merged 2026-11-16 |
| M1-2 + M1-4 Workspaces, entities, invitations, RLS isolation | `claude/m1-2-tenancy-rls` | #10 | Merged 2026-11-16 |
| M1-3 Roles, permissions, authz | `claude/m1-3-authz` | #11 | Merged 2026-11-16 |
| M1-5 Audit log | `claude/m1-5-audit-log` | #12 | Merged 2026-11-16 |
| M1-6 + M1-7 Chart of accounts, fiscal periods | `claude/m1-6-coa-periods` | #13 | Merged 2026-11-16 |
| M1-8 Journal entries | `claude/m1-8-journal-entries` | #14 | Merged 2026-11-16 |
| M1-9 Reversals, period locks, unlock | `claude/m1-9-corrections` | #15 | Merged 2026-11-16 |
| M1-10 Balances, TB, GL, export | `claude/m1-10-reports` | #16 | Merged 2026-11-16 |
| M1-11 Integrity job | `claude/m1-11-integrity` | #17 | Merged 2026-11-16 |
| M1-12 UI | `claude/m1-12-ui` | #18 | Merged 2026-11-16 |
| M1-13 Docs, sample data, demo | `claude/m1-13-docs` | #19 | Merged 2026-11-16 |
| M2-0 Cloud packaging (images, prod settings, readiness) + cloud-readiness review | `claude/m2-0-cloud-packaging` | #20 | Merged 2026-11-16 |
| M2-1 Dimensions | `claude/m2-1-dimensions` | #21 | Merged 2026-11-16 |
| M0-8 Work tracking process (issue #31) | `claude/process-tracker` | #22 | Merged 2026-11-16 |
| M2-2 Counterparties + open items (issue #47) | `claude/m2-2-open-items` | #96 | Merged 2026-11-16 |
| M2-3 VAT codes (issue #48) | `claude/m2-3-vat-codes` | #97 | Merged 2026-11-16 |
| M2-6 Taxonomy + account mapping (issue #49) | `claude/m2-6-taxonomy` | #98 | Merged 2026-11-16 |
| M2-7 reporting.actuals read model (issue #50) | `claude/m2-7-actuals` | #100 | Merged 2026-11-16 |
| M2-8 Statements: P&L, balance sheet, cash flow, exports (issue #51) | `claude/m2-8-statements` | #101 | Merged 2026-11-16 |
| M2-9 Year-end close and re-open (issue #52) | `claude/m2-9-year-end` | #102 | Merged 2026-11-16 |
| M2-11 Grouped navigation (issue #99) | `claude/m2-11-nav` | #103 | Merged 2026-11-16 |
| M2-5 Bank import, matching, reconciliation (issue #53) | `claude/m2-5-bank` | #104 | Merged 2026-11-16 |
| M2-4 Document vault (issue #54) | `claude/m2-4-documents` | #105 | Merged 2026-11-16 |
| M2-12 Milestone 2 report (issue #106) | `claude/m2-12-report` | #107 | Merged 2026-11-16 |
| M3-1 Calendar service + M3 brief (issue #55) | `claude/m3-1-calendar` | #108 | Merged 2026-11-16 |
| M3-2 Metrics core: natures, calc runs, lineage, reproducibility (issue #56) | `claude/m3-2-metrics-core` | #109 | Merged 2026-11-16 |
| M3-3 Expression evaluator (issue #57) | `claude/m3-3-expressions` | #110 | Merged 2026-11-16 |
| M3-4 Obligations, loans, facilities and holidays (issue #58) | `claude/m3-4-commitments` | #111 | Merged 2026-11-16 |
| M3-5 Tax payment calendar, manual entry (issue #59) | `claude/m3-5-tax-calendar` | #112 | Merged 2026-11-16 |
| M3-6 Customer payment behaviour (issue #60) | `claude/m3-6-payment-behaviour` | #113 | Merged 2026-11-16 |
| M3-7 13-week cash forecast engine (issue #61) | `claude/m3-7-cash-forecast` | #114 | Merged 2026-11-16 |
| M3-8 Forecast freshness, refresh, history, accuracy (issue #62) | `claude/m3-8-reruns` | #115 | Merged 2026-11-16 |
| M3-9 What-ifs on a forecast (issue #63) | `claude/m3-9-what-ifs` | #116 | Merged 2026-11-16 |
| M3-10 Cash forecast dashboard (issue #64) | `claude/m3-10-cash-dashboard` | #117 | Merged 2026-11-16 |
| M3-11 Milestone 3 report (issue #118) | `claude/m3-11-report` | #119 | Merged 2026-11-16 |
| M4-1 Budgets: versions, lifecycle, SoD, revisions (issue #65) + M4 brief | `claude/m4-1-budgets` | #120 | Merged 2026-11-16 |
| M4-2 Budget grid, phasing, Excel import/export, department owners (issue #66) | `claude/m4-2-budget-grid` | #121 | Merged 2026-11-16 |
| M4-3 Variance, explanations, monthly review (issue #67) | `claude/m4-3-variance` | #122 | Merged 2026-11-16 |
| M4-4 KPI library: versioned definitions, KPI sets as calculation runs (issue #68) | `claude/m4-4-kpis` | #123 | Merged 2026-11-16 |
| M4-5 Custom KPIs (personal, workspace with approval) and operational metrics (issue #69) | `claude/m4-5-custom-kpis` | #124 | Merged 2026-11-16 |
| M4-6 Goals: frozen baselines, evaluations, goal-seek, contribution analysis (issue #70) | `claude/m4-6-goals` | #125 | Merged 2026-11-16 |
| M4-7 In-app alerts: goal status and breaches, budget overruns and trends (issue #71) | `claude/m4-7-alerts` | #126 | Merged 2026-11-16 |
| M4-8 CFO dashboard: widgets, presets and comparisons, layouts, nature contract (issue #72) | `claude/m4-8-dashboard` | #127 | Merged 2026-11-16 |
| M4-9 Firm portfolio of accessible client entities (issue #73) | `claude/m4-9-portfolio` | #128 | Merged 2026-11-16 |
| M4 report (`docs/milestone-4-report.md`) | `claude/m4-9-portfolio` | #128 | Merged 2026-11-16 |
| M5-1 Personal workspace: setup, simplified transactions, valuations, net worth, spending (issue #74) | `claude/m5-1-personal` | #129 | Merged 2026-11-16 |
| M5-2 Personal budgets, goals, 12-month projection (issue #75) | `claude/m5-2-personal-plans` | #130 | Merged 2026-11-16 |
| M5-3 Counterpart hint: opt-in, confirm-only (issue #76) | `claude/m5-3-counterpart-hint` | #131 | Merged 2026-11-16 |
| M5-4 Engagement grants: scope ∩ firm role, revocation, audit, portfolio (issue #77) | `claude/m5-4-engagements` | #132 | Merged 2026-11-16 |
| M5-5 Pilot environment as code (never applied), monitoring, backup and restore drill (issue #78) | `claude/m5-5-pilot-iac` | #133 | Merged 2026-11-16 |
| M5-6 Workspace export and deletion with a grace period (issue #79) | `claude/m5-6-export-deletion` | #134 | Merged 2026-11-16 |
| M5 report (`docs/milestone-5-report.md`) | `claude/m5-6-export-deletion` | #134 | Merged 2026-11-16 |
| M6-1 Fixed-asset register, depreciation, prepared entries (issue #135) | `claude/m6-1-fixed-assets` | #141 | Merged 2026-11-16 |
| M6-2 Assumption sets: drivers by month, start from actuals or budget, approval (issue #136) | `claude/m6-2-assumptions` | #142 | Merged 2026-11-16 |
| M6-3 Three-statement projection engine, six invariants, golden model (issue #137) | `claude/m6-3-projection-engine` | #143 | Merged 2026-11-16 |
| M6-4 Rolling forecasts: staleness, hourly re-runs, history, accuracy (issue #138) | `claude/m6-4-rolling-forecasts` | #144 | Merged 2026-11-16 |
| M6-5 Full-year outlook (actual + forecast with natures), goals use the projection (issue #139) | `claude/m6-5-outlook` | #145 | Merged 2026-11-16 |
| M6-6 Projection screens: statements with natures, checks, explain, chart, Excel export, rolling forecast and outlook (issue #140) | `claude/m6-6-projection-screens` | #146 | Merged 2026-11-16 |
| M6 report (`docs/milestone-6-report.md`) | `claude/m6-6-projection-screens` | #146 | Merged 2026-11-16 |
| **Milestone 6 follow-up** (owner decisions 2026-11-15; brief `docs/planning/20-milestone-6-follow-up-brief.md`) | | | |
| M6F-1 Currency foundation: ISO 4217, transaction/functional/reporting currencies, FX rates; multi-currency disabled (issue #80) | `claude/m6f-1-currency-foundation` | #155 | Merged 2026-11-16 |
| M6F-2 Tax rule sets: sourced, versioned, per jurisdiction; Cyprus seeded pending verification (issue #147) | `claude/m6f-2-tax-rules` | #156 | Merged 2026-11-16 |
| M6F-3 Depreciation from available for use (IAS 16); separate tax capital allowances; capex commencement and method in projections (issue #148) | `claude/m6f-3-depreciation-allowances` | #157 | Merged 2026-11-16 |
| M6F-4 Loans in projections: structures, rate paths, early repayment, drawdowns, register loans, debt reconciliation (issue #149) | `claude/m6f-4-debt` | #158 | Merged 2026-11-16 |
| M6F-5 Corporate tax in projections: current and deferred tax, losses by year, provisional and final payments from the versioned rules; income tax separate from VAT (issue #150) | `claude/m6f-5-tax` | #159 | Merged 2026-11-16 |
| M6F-6 Rolling forecasts on material changes (15-minute pass, materiality, regular interval); published runs stay the reference; any past projection against actuals (issue #151) | `claude/m6f-6-rolling-material` | #160 | Merged 2026-11-16 |
| M6F-7 Goals: the published projection as forward reference, the approved budget as a separate benchmark; actual vs budget, actual vs forecast, projected vs goal; goals never change by themselves (issue #152) | `claude/m6f-7-goals-benchmarks` | #161 | Merged 2026-11-16 |
| M6F-8 Validation package: independent 24-month model, six scenarios (losses, negative cash, early repayments, changing revenues, unexpected expenses), line-by-line comparison at EUR 0.01, reconciliation, discrepancy report, acceptance checklist, reviewer sign-off form; engine stays PENDING_PROFESSIONAL_REVIEW (issue #153) | `claude/m6f-8-validation` | #162 | Merged 2026-11-16 |
| Owner items: professional review of the validation package (U1), Cyprus tax rules verification (#154) | — | — | Waiting for the owner |
| **Milestone 7** (epic #82) | | | |
| M7-1 Scenario model and typed overrides (eight types, lifecycle, isolation), with the M7 brief (`docs/planning/21-milestone-7-brief.md`, approved 2026-11-16) (issue #176) | `claude/m7-1-scenarios` | #183 | Merged 2026-11-22 |
| M7-2 Scenario runs: comparison with the base, lineage by override, what changed and why, saved runs (never published), promotion to a draft set (issue #177) | `claude/m7-2-scenario-runs` | #184 | Merged 2026-11-22 |
| M7-3 Sensitivity (one variable) and tornado: cached by input hash, quotas and time limit (issue #178) | `claude/m7-3-sensitivity` | #185 | Merged 2026-11-22 |
| M7-4 Working-capital view (receivables, stock, payables, days, cash conversion cycle against observed days) and what N days are worth (issue #179) | `claude/m7-4-working-capital` | #186 | Merged 2026-11-22 |
| M7-5 Goals against up to three shared scenarios, side by side with the base, in memory (goal engine v3: method SCENARIO, nature HYPOTHETICAL) (issue #180) | `claude/m7-5-goals-scenarios` | #187 | Merged 2026-11-22 |
| M7-6 KPI library CORE@1.1 (net debt / EBITDA, DSCR, receivables and inventory turnover; `ltm_flow`) and KPIs on projected and scenario figures (issue #181) | `claude/m7-6-advanced-kpis` | #188 | Merged 2026-11-22 |
| M7-7 Screens: Scenarios (builder, comparison, cash chart with dotted scenario line, what changed, liquidity, KPIs), Sensitivity (tornado and one variable), Working capital, goals against scenarios; Excel export of a comparison; demo step; M7 report (`docs/milestone-7-report.md`) (issue #182) | `claude/m7-7-screens` | #189 | Merged 2026-11-22 |
| Owner items for M7: review and merge #183–#189; ADRs 0049–0052; defaults in the M7 report | — | — | Merged 2026-11-22 (owner asked the developer to merge) |
| **Milestone 8** (epic #83) | | | |
| M8 brief (`docs/planning/22-milestone-8-brief.md`): report packs, dashboard v2, email alerts; issues #190–#195; approved 2026-11-17 ("Continue"), defaults taken | `claude/m8-0-brief` | #196 | Merged 2026-11-22 |
| M8-1 Report packs: frozen snapshot of statements, budget variance (with explanations), KPIs, cash, published projection and goals under the preparer's permissions; DRAFT → IN_REVIEW → FINAL with a reviewer who is not the preparer; finalising blocked by missing explanations or changed figures; new versions supersede (issue #190) | `claude/m8-1-packs` | #197 | Merged 2026-11-22 |
| M8-2 Pack sections from the snapshot (ten, chosen and ordered), comparison columns (actual, budget, original budget, prior year, variance, full-year outlook), human commentary and risks (append-only, draft-only), golden budget variance pack (issue #191) | `claude/m8-2-sections` | #198 | Merged 2026-11-22 |
| M8-3 Report pack exports: Excel (cover with scope, provenance and legend; a sheet per section with a Nature row; formula-safe) and PDF (A4 landscape, provenance footer and page numbers, DRAFT watermark until final), both from the same sections as the API; audited (issue #192) | `claude/m8-3-exports` | #199 | Merged 2026-11-22 |
| M8-4 Dashboard v2: widget widths (full or half), waterfall (budget to actual) and scenario comparison widgets, only the shown widgets built, last-twelve-months preset, personal saved views (issue #193) | `claude/m8-4-dashboard` | #200 | Merged 2026-11-22 |
| M8-5 Alert emails: per-user preference (immediate, daily digest, off by default), titles and links only, outbox with one email per alert and user, retries, hourly limit, one-click unsubscribe, scheduled sender (issue #194) | `claude/m8-5-email` | #201 | Merged 2026-11-22 |
| M8-6 Screens: report packs (generate, sections with natures, commentary, risks, review, finalise, versions, Excel/PDF), dashboard v2 controls (widths, waterfall, scenario, saved views, LTM), alert email preference; demo step; Milestone 8 report (`docs/milestone-8-report.md`) (issue #195) | `claude/m8-6-screens` | #202 | Merged 2026-11-22 |
| Owner items for M8: review and merge #196–#202; ADRs 0053–0054; Gate G before any external customer | — | — | Merged 2026-11-22 (owner asked the developer to merge) |
| **Version 1** (owner's own use; brief `docs/planning/24-version-1-brief.md`, approved 2026-11-22) | | | |
| Version 1 brief: one-person workspace, Cyprus VAT return preparation, local install, end-to-end check, dependencies (issues #207–#211); Gate G brief (`docs/planning/23-gate-g-brief.md`, first proposed in #205) kept as deferred | `claude/v1-0-brief` | #206 | Open |

## Open questions for the product owner
- Does your business use any currency other than EUR? (needed before M2)
- Bank used and statement export formats (CSV / CAMT.053)? Any current accounting software? (before M2)
- Cyprus tax professional for rule verification (before Phase 4)

## How to resume work in a new session
Say "Resume the Financial Compliance Platform. Follow CLAUDE.md." The full procedure is in
`docs/PROCESS.md` §7. In short:
1. `git fetch origin` and check out `main` (or the open branch in the table above).
2. `make dev` (if the user model changed since your last run: `make dev-reset && make dev`).
3. Check `needs:owner` issues and open PRs, then continue with the next issue (PROCESS §3).
