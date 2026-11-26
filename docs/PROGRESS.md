# Progress Tracker

> Work is tracked in **GitHub Milestones and Issues** (one issue per backlog item; process:
> `docs/PROCESS.md`). This file is the quick summary and the branch map for resuming work.

The single place to see where implementation stands. It is updated with every PR, so nothing
depends on a chat session. Until 2026-11-16 branches were stacked (each PR targeted the previous one); since the
consolidation every new PR targets `main`.

## Status (updated 2026-11-26)

**Real books readiness is complete** (2026-11-26, brief 26): bank statements from the four banks
recognised from the file, the chart, customers and suppliers, opening balances and open invoices
imported from templates, an accountant's trial balance or package reports, and the prior year by
month kept as comparatives; see the [real books readiness report](real-books-readiness-report.md)
and the guide [Moving your books in](user-guide/moving-your-books-in.md). The presets stay to be
confirmed against the owner's anonymised exports.

### Status of 2026-11-24

**Version 1 is complete** (2026-11-24). The end-to-end check passes
through the API (20 agreement checks) and in a real browser; see the
[version 1 report](version-1-report.md).

### Status of 2026-11-22

**Milestones 7 and 8 are merged into `main`** (2026-11-22; the owner asked the developer to merge
each PR in order once its checks passed: #183–#189, then #196–#202). Checks on `main` after
the merge: 1,326 backend tests (96.30% coverage), 74 frontend tests, lint, OpenAPI, security
(Semgrep 0 findings, no leaks) and the validation package (six scenarios to EUR 0.01) pass.
**Version 1 in progress**:
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
| V1-1 One-person workspace: a setting in force only while the workspace has exactly one member (database-enforced); preparers may approve their own journal entries, period unlocks (one approval), budget versions, workspace KPIs and report packs, each recorded as self-approved, audited and shown on screen and in exports; ADR-0055 (issue #207) | `claude/v1-1-one-person` | #212 | Merged |
| V1-2a VAT (brief `docs/planning/25-cyprus-vat-return-brief.md`, approved 2026-11-23): periods chosen per company (versioned, changed from the start of a later period); a VAT report per period from the posted ledger (totals, by VAT code, VAT accounts, checks, every line), frozen; sign-off (self-approved in a one-person workspace), filing recorded by hand with the portal's reference (never filed by the platform), versions, settlement entry draft, PDF and Excel (ADR-0056); the 13-box return and the rest of the owner's specification follow in V1-2b to V1-2i (issue #208) | `claude/v1-2-vat-report` | #221 | Merged |
| V1-3 Version 1 on the owner's computer: the production images with local services (PostgreSQL, Keycloak with MFA, documents store, ClamAV, Mailpit), scheduled jobs, `scripts/local/fcp.sh` (install, start, stop, backup, restore, upgrade, verify), guide, ADR-0057; verified by a real browser through install, sign-in, backup, restore and upgrade (issue #209) | `claude/v1-3-local-install` | #222 | Merged |
| V1-2b VAT codes v2 and line VAT details: 32 codes in 14 categories (3% rate; EU acquisition, reverse-charge and import codes); the box rules of the owner's specification as versioned, sourced data, marked unverified, with excluded and unsupported cases explicit; tax point, recoverable % and non-recoverable VAT on lines (hashed, reversed, checked by the database); counterparty country; the entry form and counterparties screen (ADR-0058, issue #213) | `claude/v1-2b-vat-codes` | #223 | Merged |
| V1-2c The 13-box VAT return from line contributions: each line's boxes, rule and version in the report; Box 3 and Box 5 computed; Boxes 6–11B in whole euros with rounding shown; cross-field checks; unsupported lines as exceptions, never guessed; partial recovery in the rate check; party data from the entry's receivable or payable line; tax point, EU party and country checks; the return on screen with lines per box, in PDF and Excel; the specification's acceptance fixtures (ADR-0059, issue #214) | `claude/v1-2c-vat-boxes` | #224 | Merged |
| V1-2d Four steps for a VAT return: Draft → Reviewed → Finalised → Filed, each enforced by the database (reviewer and finaliser never the preparer, except self-approved in a one-person workspace); send back to draft with a note; manual adjustments per box with reason, evidence and approval, shown as from the books, adjustment and final; inclusion of every line in one return; differences from later entries shown, never moved; amendments showing the version corrected and the change per box; filing evidence; reports signed off under V1-2a migrated as finalised (ADR-0060, issue #215) | `claude/v1-2d-vat-workflow` | #225 | Merged |
| V1-2e VAT schedules (sales, purchases, EU trade, reverse charge, imports, adjustments, exceptions) derived from the frozen lines; reconciliation of the VAT accounts (opening, period VAT, settlements, closing) and of the return to the ledger with every reconciling item; Excel with named sheets, numeric cells and filters; PDF with company, period, version and page on every page; CSV of every line's box contributions; coverage matrix `docs/vat/coverage.md` checked against the rules (ADR-0061, issue #216) | `claude/v1-2e-vat-schedules` | #226 | Merged |
| V1-2f Import records: the customs declaration (reference, date, taxable value, import VAT, the document attached to the entry) behind each import VAT claim; one active record per reference and per entry, voided only with a reason and never once in a finalised return (database guard); checks for missing records, VAT and value mismatches; imports schedule with the evidence; Imports panel on the VAT screen (ADR-0062, issue #217) | `claude/v1-2f-vat-imports` | #227 | Merged |
| V1-2g VIES statements recorded as filed (month, kind, filing date, reference, partners with goods, services and triangular amounts; never submitted), voided only with a reason (database guards); reconciliation per partner to the EU supplies in the books, months without a statement, totals against Boxes 8A and 8B, triangular amounts apart; a correction carries the month's full figures and replaces the original (owner's decision, 2026-11-23); VIES panel on the VAT screen (ADR-0063, issue #218) | `claude/v1-2g-vies` | #228 | Merged |
| V1-2h Foreign-currency lines: switched on per entity with the account for exchange differences; each line keeps its currency, amount, rate, the rate's date and time and its source, and its euro amount must equal amount × rate rounded to the cent (service and database); stored rates offered, never imposed; reversals mirror the foreign figures; the VAT report states the conversion policy and keeps each line's original figures (CSV too); Ledger settings screen for approvals, foreign currency and exchange rates; converted at the rate of the purchase's date and time (owner's decision, 2026-11-23) (ADR-0064, issue #219) | `claude/v1-2h-foreign-currency` | #232 | Merged |
| V1-2i Help for data entry (the owner's request of 2026-11-23): a VAT code picker that searches by code, name or rate and lists the user's starred favourites, then the company's most used codes, then all by category; favourites kept per user and company (RLS); the account's usual code offered, never applied; suggestions for descriptions, memos and references from the company's own entries, ranked by match, use and recency; accessible combobox; no AI and no outside service (ADR-0065, issue #231) | `claude/v1-2i-entry-helpers` | #233 | Merged |
| V1-2h2 Exchange differences: positions per monetary account (receivables, payables, foreign-currency accounts), counterparty and currency; unrealised differences at the stored closing rate and realised ones when a foreign balance is settled; one draft entry against the exchange-differences account, refused while an earlier one waits; missing rates shown, never guessed; exchange-difference lines keep the currency with no foreign amount (database constraint); screen (ADR-0066, issue #230) | `claude/v1-2h2-exchange-differences` | #234 | Merged |
| V1-4 End-to-end check: the demo year ends with 20 agreement checks from the ledger through statements, budget variance, KPIs, cash forecast, fixed assets, projection and report pack to the VAT return; `make e2e-walkthrough` walks nine screens in a real browser after MFA sign-in and checks their figures; fixed: packs calculate their KPI set, the fixed-asset register reconciles to the ledger (API and screen), projections open on the published run, the demo books its asset purchase; version 1 report (`docs/version-1-report.md`, issue #210) | `claude/v1-4-walkthrough` | #235 | Merged |
| V1-5 Dependencies: 15 dependency-update PRs, each brought up to date with `main` and merged with every check green, or closed with a reason. Merged: ruff 0.17.5, import-linter 2.16, hypothesis 6.170.15, uv-build <0.14, vite 8.3.8, vitest 5.1 with jsdom 31, typescript-eslint 8.72.2 and @vitejs/plugin-react 6.3 (#170), and every GitHub Action at v7 (checkout, setup-node, setup-python, setup-uv, upload-artifact). Closed: Django 6.1 (#167; the platform stays on Django 5.2 LTS per ADR-0006, the move to 6.2 LTS is #236), and #166, #172, #174 (carried by #170) (issue #211) | Dependabot branches; `claude/v1-5-dependencies` | #163–#175, #203, #204 | Merged |
| R-1 Bank statements recognised from the file: encoding (incl. Windows Greek), separator, header after account details, columns from English and Greek names, decimal separator and date format from the values; open readings asked, never guessed; presets for Bank of Cyprus, Hellenic Bank, Eurobank Cyprus and Revolut Business marked to be confirmed; preview and "save this layout and import" on the Bank screen (ADR-0067, issue #244; brief 26) | `claude/r-1-bank-statements` | #249 | Merged |
| R-2 Spreadsheet import: templates (Excel and CSV, with a "How to fill in" sheet) for the chart of accounts, customers and suppliers, the opening trial balance and the open invoices; columns found by their English or Greek header names; hardened reading (no formulas, no macros, size and row limits), amounts read exactly and ambiguous ones refused; check first (every problem by file, row and column; the real services run and are rolled back), then import; accounts and customers or suppliers created directly, identical ones skipped; the opening balances one balanced draft entry with a line per open invoice on the receivables and payables (they must add up to the balance), accounts the chart lacks mapped; audited with each file's SHA-256; Bring your books in screen (ADR-0068, issue #245; brief 26) | `claude/r-2-spreadsheet-import` | #250 | Merged |
| R-3 Accountant's trial balance and accounting-package exports: headings, zero rows, subtotals and totals skipped and the file's total checked against its lines; Dr and Cr amounts; accounts found by "code name" or by name alone; the year's income and expense carried into a chosen equity account; aged receivables and payables reports for the open invoices (customer or supplier by code or name, the entity's control account, subtotals skipped), with the missing customers and suppliers listed and created on request; date order day or month first, a date fitting only the other order refused with the reason; package account types recognised (Accounts Receivable makes a control account); Xero and QuickBooks presets set the date order, to be confirmed (ADR-0069, issue #246; brief 26) | `claude/r-3-accountant-and-packages` | #251 | Merged |
| R-4 The prior year by month as comparatives: a monthly trial balance of the months before the first fiscal year (income and expense year to date or per month, an optional opening column; month headers in several forms; template with the 12 months) kept as movements per month in `reporting_fact_comparative` (RLS), never entries; read by the gateway's monthly actuals for those months and by balances only up to the books start, so the opening entry is never counted twice; checks: months before the books and consecutive, each month balanced, the last month equal to the opening entry for assets and liabilities, accounts known or mapped; one set per entity, replaced and audited (ADR-0070, issue #247; brief 26) | `claude/r-4-prior-year` | #252 | Merged |
| R-5 Guide and check: guide "Moving your books in" (before you start, the four steps, bank statements, confirming the presets, what each refusal means); synthetic example files for every template, for an accountant's trial balance and package aged reports, for the prior year by month and for each bank preset (`examples/books/`, each bank file a different shape and not the bank's real layout); an end-to-end test importing the full set through the API (trial balance equal to the source to the cent after posting, nothing in the books before; the accountant and package versions give the same opening; each preset's statement imported with no question); real books readiness report (`docs/real-books-readiness-report.md`, issue #248; brief 26) | `claude/r-5-guide-and-check` | #253 | Merged |

## Open questions for the product owner
- Bank used and statement export formats (CSV / CAMT.053)? Any current accounting software? (before M2)
- **Professional review (#93):** go through `docs/review/professional-review-list.md` with a
  Cyprus tax professional; corrections become new versions of the data.

## Reminders (decided to do later)
- **The Tax Department's XML file for the VAT return (#220):** left for later by the owner on
  2026-11-23. Needs the official XSD and its guide. Keep #220 open; raise it again before the
  first return is filed with the platform.

## Owner decisions of 2026-11-23 (VAT)
- A VIES correction carries the month's full figures and replaces the original (ADR-0063).
- Purchases in a foreign currency are converted to euros at the exchange rate of the date and
  time of the purchase (#219, V1-2h, ADR-0064).
- The XML file is deferred (#220, above).

## How to resume work in a new session
Say "Resume the Financial Compliance Platform. Follow CLAUDE.md." The full procedure is in
`docs/PROCESS.md` §7. In short:
1. `git fetch origin` and check out `main` (or the open branch in the table above).
2. `make dev` (if the user model changed since your last run: `make dev-reset && make dev`).
3. Check `needs:owner` issues and open PRs, then continue with the next issue (PROCESS §3).
