# Progress Tracker

> Work is tracked in **GitHub Milestones and Issues** (one issue per backlog item; process:
> `docs/PROCESS.md`). This file is the quick summary and the branch map for resuming work.

The single place to see where implementation stands. It is updated with every PR, so nothing
depends on a chat session. Branches are stacked: each PR targets the previous one and is merged
in order.

## Status (updated 2026-11-03)

**Milestone 1 is complete** (see `docs/milestone-1-report.md`). Milestone 2 is in progress (go-ahead
2026-11-03: "continue developing according to our existing roadmap"). Cloud-readiness review:
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
| M2-5 Bank import and reconciliation (issue #53) | — | — | Next |

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
