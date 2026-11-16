# Progress Tracker

> Work is tracked in **GitHub Milestones and Issues** (one issue per backlog item; process:
> `docs/PROCESS.md`). This file is the quick summary and the branch map for resuming work.

The single place to see where implementation stands. It is updated with every PR, so nothing
depends on a chat session. Branches are stacked: each PR targets the previous one and is merged
in order.

## Status (updated 2026-11-10)

**Milestone 1 is complete** (see `docs/milestone-1-report.md`). **Milestone 2 is complete and
awaits review** (see `docs/milestone-2-report.md`; go-ahead 2026-11-03: "continue developing
according to our existing roadmap"). **Milestone 3 is complete and awaits review** (see `docs/milestone-3-report.md`; owner: "Continue",
2026-11-04; brief `docs/planning/16-milestone-3-brief.md`). **Milestone 4 is complete and awaits review** (see `docs/milestone-4-report.md`; owner: "Let continue",
2026-11-04; brief `docs/planning/17-milestone-4-brief.md`). **Milestone 5 is in progress** (owner,
2026-11-10: "continue with what is easier for now for best coding"; brief
`docs/planning/18-milestone-5-brief.md`). Cloud-readiness review:
`docs/reviews/2026-11-03-cloud-readiness.md`; AWS target: `docs/deployment/aws.md`.

| Item | Branch | PR | State |
|---|---|---|---|
| Planning set v2 + decisions | `claude/initial-planning-docs` | #1 | Open, awaiting review |
| M0-1 Repo layout | `claude/m0-1-repo-layout` | #2 | Open |
| M0-2 CI gates | `claude/m0-2-ci` | #3 | Open, CI green |
| M0-3 Local dev services | `claude/m0-3-local-dev` | #4 | Open, CI green |
| M0-4 Money library | `claude/m0-4-money` | #5 | Open, CI green |
| M0-5 Errors and logging | `claude/m0-5-errors-logging` | #6 | Open, CI green |
| M0-6 Synthetic data | `claude/m0-6-synthetic-data` | #7 | Open, CI green |
| M0-7 Terraform skeleton | `claude/m0-7-iac-skeleton` | #8 | Open, CI green |
| M1-1 OIDC sign-in, MFA, sessions | `claude/m1-1-auth` | #9 | Open |
| M1-2 + M1-4 Workspaces, entities, invitations, RLS isolation | `claude/m1-2-tenancy-rls` | #10 | Open |
| M1-3 Roles, permissions, authz | `claude/m1-3-authz` | #11 | Open |
| M1-5 Audit log | `claude/m1-5-audit-log` | #12 | Open |
| M1-6 + M1-7 Chart of accounts, fiscal periods | `claude/m1-6-coa-periods` | #13 | Open |
| M1-8 Journal entries | `claude/m1-8-journal-entries` | #14 | Open |
| M1-9 Reversals, period locks, unlock | `claude/m1-9-corrections` | #15 | Open |
| M1-10 Balances, TB, GL, export | `claude/m1-10-reports` | #16 | Open |
| M1-11 Integrity job | `claude/m1-11-integrity` | #17 | Open |
| M1-12 UI | `claude/m1-12-ui` | #18 | Open |
| M1-13 Docs, sample data, demo | `claude/m1-13-docs` | #19 | Open, CI green |
| M2-0 Cloud packaging (images, prod settings, readiness) + cloud-readiness review | `claude/m2-0-cloud-packaging` | #20 | Open |
| M2-1 Dimensions | `claude/m2-1-dimensions` | #21 | Open |
| M0-8 Work tracking process (issue #31) | `claude/process-tracker` | #22 | Open |
| M2-2 Counterparties + open items (issue #47) | `claude/m2-2-open-items` | #96 | Open |
| M2-3 VAT codes (issue #48) | `claude/m2-3-vat-codes` | #97 | Open |
| M2-6 Taxonomy + account mapping (issue #49) | `claude/m2-6-taxonomy` | #98 | Open |
| M2-7 reporting.actuals read model (issue #50) | `claude/m2-7-actuals` | #100 | Open |
| M2-8 Statements: P&L, balance sheet, cash flow, exports (issue #51) | `claude/m2-8-statements` | #101 | Open |
| M2-9 Year-end close and re-open (issue #52) | `claude/m2-9-year-end` | #102 | Open |
| M2-11 Grouped navigation (issue #99) | `claude/m2-11-nav` | #103 | Open |
| M2-5 Bank import, matching, reconciliation (issue #53) | `claude/m2-5-bank` | #104 | Open |
| M2-4 Document vault (issue #54) | `claude/m2-4-documents` | #105 | Open |
| M2-12 Milestone 2 report (issue #106) | `claude/m2-12-report` | #107 | Open |
| M3-1 Calendar service + M3 brief (issue #55) | `claude/m3-1-calendar` | #108 | Open |
| M3-2 Metrics core: natures, calc runs, lineage, reproducibility (issue #56) | `claude/m3-2-metrics-core` | #109 | Open |
| M3-3 Expression evaluator (issue #57) | `claude/m3-3-expressions` | #110 | Open |
| M3-4 Obligations, loans, facilities and holidays (issue #58) | `claude/m3-4-commitments` | #111 | Open |
| M3-5 Tax payment calendar, manual entry (issue #59) | `claude/m3-5-tax-calendar` | #112 | Open |
| M3-6 Customer payment behaviour (issue #60) | `claude/m3-6-payment-behaviour` | #113 | Open |
| M3-7 13-week cash forecast engine (issue #61) | `claude/m3-7-cash-forecast` | #114 | Open |
| M3-8 Forecast freshness, refresh, history, accuracy (issue #62) | `claude/m3-8-reruns` | #115 | Open |
| M3-9 What-ifs on a forecast (issue #63) | `claude/m3-9-what-ifs` | #116 | Open |
| M3-10 Cash forecast dashboard (issue #64) | `claude/m3-10-cash-dashboard` | #117 | Open |
| M3-11 Milestone 3 report (issue #118) | `claude/m3-11-report` | #119 | Open |
| M4-1 Budgets: versions, lifecycle, SoD, revisions (issue #65) + M4 brief | `claude/m4-1-budgets` | #120 | Open |
| M4-2 Budget grid, phasing, Excel import/export, department owners (issue #66) | `claude/m4-2-budget-grid` | #121 | Open |
| M4-3 Variance, explanations, monthly review (issue #67) | `claude/m4-3-variance` | #122 | Open |
| M4-4 KPI library: versioned definitions, KPI sets as calculation runs (issue #68) | `claude/m4-4-kpis` | #123 | Open |
| M4-5 Custom KPIs (personal, workspace with approval) and operational metrics (issue #69) | `claude/m4-5-custom-kpis` | #124 | Open, CI green |
| M4-6 Goals: frozen baselines, evaluations, goal-seek, contribution analysis (issue #70) | `claude/m4-6-goals` | #125 | Open, CI green |
| M4-7 In-app alerts: goal status and breaches, budget overruns and trends (issue #71) | `claude/m4-7-alerts` | #126 | Open, CI green |
| M4-8 CFO dashboard: widgets, presets and comparisons, layouts, nature contract (issue #72) | `claude/m4-8-dashboard` | #127 | Open, CI green |
| M4-9 Firm portfolio of accessible client entities (issue #73) | `claude/m4-9-portfolio` | #128 | Open |
| M4 report (`docs/milestone-4-report.md`) | `claude/m4-9-portfolio` | #128 | Open, with M4-9 |
| M5-1 Personal workspace: setup, simplified transactions, valuations, net worth, spending (issue #74) | `claude/m5-1-personal` | #129 | Open |
| M5-2 Personal budgets, goals, 12-month projection (issue #75) | `claude/m5-2-personal-plans` | #130 | Open |
| M5-3 Counterpart hint: opt-in, confirm-only (issue #76) | `claude/m5-3-counterpart-hint` | #131 | Open |
| M5-4 Engagement grants (issue #77) | — | — | Next |

## Open questions for the product owner
- Does your business use any currency other than EUR? (needed before M2)
- Bank used and statement export formats (CSV / CAMT.053)? Any current accounting software? (before M2)
- Cyprus tax professional for rule verification (before Phase 4)

## How to resume work in a new session
Say "Resume the Financial Compliance Platform. Follow CLAUDE.md." The full procedure is in
`docs/PROCESS.md` §7. In short:
1. `git fetch origin` and check out the last branch in the table above.
2. `make dev` (if the user model changed since your last run: `make dev-reset && make dev`).
3. Check `needs:owner` issues and open PRs, then continue with the next issue (PROCESS §3).
