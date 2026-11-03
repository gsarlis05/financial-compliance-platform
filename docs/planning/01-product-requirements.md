# 01 — Product Requirements Document (PRD) — v2

Status: **DRAFT v2 for review** (v1 superseded by the scope update adding FP&A/CFO intelligence and personal use)
Related: [MASTER-PLAN](../MASTER-PLAN.md), [10 CFO/FP&A spec](10-cfo-fpa-specification.md), [11 customer types](11-account-types-and-coexistence.md), [08 roadmap](08-implementation-backlog.md)

## 1. Vision
A unified, trustworthy platform for **accounting, tax, audit, compliance, financial planning and
executive financial management**, serving accounting firms, businesses and individuals. It answers
two questions:

1. **What has happened financially?** This comes from an immutable, double-entry ledger that is reconciled to the bank.
2. **What is likely to happen, and what can management do about it?** Deterministic, versioned forecasts, budgets, scenarios, KPIs and goals are built *on* the ledger. They never replace it or blur into it.

Every number is traceable to its source, its nature (actual vs forecast vs hypothetical), the
assumptions or rule version that produced it, and the person who approved it.

## 2. Customer types (see doc 11 for the security model)

| Type | Who | Core value | First available |
|---|---|---|---|
| **A. Accounting & audit firms** | Cyprus firms (ICPAC members), then EU | Manage many clients' books, reports, tax, audit, and CFO advisory | Phase 1 (bookkeeping) → Phase 4 (tax/audit) |
| **B. Individual businesses** | SMEs, startups, holding companies | Own bookkeeping, cash forecasting, budgets, KPIs, goals, management reports | Phase 1 → Phase 2 (FP&A MVP) |
| **C. Individuals** | People managing personal finances | Net worth, personal cash flow, budgets, goals, projections | Phase 2 (personal MVP, for your own use first) |

Personal and business finances are **separate workspaces** (separate tenants) even for the same
person. They share identity, infrastructure and calculation engines, but not data.

## 3. Personas

| Persona | Workspace | Primary jobs |
|---|---|---|
| Firm Partner | Firm | Approve filings and statements; client portfolio oversight; staff access |
| Accountant / Bookkeeper | Firm/Business | Post entries, reconcile banks, close periods, prepare VAT |
| Tax Professional | Firm | Tax computations, judgments, rule applicability |
| Auditor (external) | Firm (granted) | Read-only books, working papers, evidence; never edits the ledger |
| **CFO / Finance Manager** | Business (or firm advisory) | Cash forecasting, budgets, scenarios, KPIs, board/management reporting |
| **Business Owner** | Business | Dashboard, goals, "can I afford this?" scenarios, approvals |
| **Department Budget Owner** | Business | Own department's budget, variance explanations |
| **Individual** | Personal | Track accounts, net worth, budgets, savings/debt goals, projections |
| Tenant Admin | Any | Users, roles, settings, AI policy, integrations |
| Rules Curator (qualified) | Platform | Maintain verified regulatory rule packs |
| Platform Operator | Platform | Ops/support via approved, time-boxed access only |

## 4. Scope by phase (roadmap detail in doc 08)

| Phase | Theme | Highlights |
|---|---|---|
| **1** | Accounting foundation | Workspaces (firm/business/personal-ready), clients and companies, CoA, double-entry journals, GL, TB, dimensions (department/project), counterparties and open AR/AP items, bank import and reconciliation, basic financial reporting, audit trail. **Compliance foundations pulled forward:** period locking, VAT codes on lines, evidence trail, MFA, tenant isolation. |
| **2** | Financial management MVP | Cash flow dashboard, **13-week cash forecast**, recurring obligations, loan schedules (basic), tax payment calendar (manual), monthly budgets, budget vs actual, core KPIs, goal tracking, CFO dashboard v1, **personal workspace MVP** |
| **3** | Advanced FP&A | Integrated three-statement projections, rolling 12/24-month forecasts, scenario modelling, sensitivity, advanced KPIs, working-capital forecasting, management report packs (Excel/PDF), fixed-asset register |
| **4** | Professional compliance | Rules engine + VAT return prep, corporate tax and SDC, IFRS statements and notes, regulatory source library and monitoring, audit engagement module |
| **5** | AI CFO intelligence | Read-only AI assistant using deterministic tools: variance explanations, scenario explanations, forecast commentary drafts, risk identification, source-linked regulatory explanations |

### Explicitly out of scope until separately approved
Automated filing to government portals; payment initiation; PSD2 bank aggregation; payroll and social
insurance submissions; consolidation; personal tax filing; live market data; ML/stochastic forecasting in
the calculation path; AI-generated audit opinions or filings.

## 5. Functional requirements

IDs are referenced by backlog items and tests. FR-T/L/X/E/A from v1 remain, and new ones are added.

### 5.1 Workspaces & access
- FR-T1 A workspace (tenant) has a kind: FIRM, BUSINESS or PERSONAL. Feature availability depends on kind and plan, and is enforced server-side.
- FR-T2 One user identity may belong to many workspaces. Each request acts in exactly one workspace, and the workspace switch is explicit and visually distinct.
- FR-T3 Firms access clients either as firm-hosted entities or through **engagement grants** from client-owned workspaces (scoped, time-bound, revocable, audited on both sides).
- FR-T4 Auditor access is read-only and time-bound.
- FR-T5 MFA is mandatory for all users, and SSO is optional per workspace.
- FR-T6 Budget and variance permissions can be scoped to departments/projects.
- FR-T7 Personal workspaces are never visible to firms or employers without an explicit grant by the individual.

### 5.2 Ledger (doc 05)
- FR-L1 Balanced double entry. FR-L2 Posted entries are immutable, with reversal/adjustment workflows. FR-L3 Soft-close and lock of periods, with a dual-approved unlock. FR-L4 Segregation of duties (SoD). FR-L5 TB always balances. Reports reconcile.
- FR-L6 Dimensions (department, project, cost centre) on journal lines, required by configuration per account.
- FR-L7 Counterparties and **open items** (receivables/payables with due dates), settled by payments. This is a prerequisite for cash forecasting.
- FR-L8 Bank statement import (CSV, CAMT.053) and reconciliation, with the last-reconciled date visible.
- FR-L9 Personal workspaces use the same ledger with a simplified transaction UI (account + category), and double entry happens underneath.

### 5.3 Financial reporting (actuals)
- FR-R1 TB, GL, account activity, P&L, balance sheet, and cash flow statement (indirect, from mapped accounts) for any period, with comparatives.
- FR-R2 Accounts map to a versioned **financial taxonomy**. Unmapped active accounts block KPI/statement publication with an actionable task.
- FR-R3 Drill-down from any reported number to entries and source documents.

### 5.4 Cash flow forecasting (doc 10 §3)
- FR-C1 13-week rolling forecast (Phase 2). Monthly 12/24-month rolling forecasts (Phase 3). Daily, weekly, monthly, quarterly and annual views.
- FR-C2 Inflows/outflows from open AR/AP, recurring obligations, loan schedules, tax payments, capex commitments, pattern-based expectations and manual adjustments.
- FR-C3 Every flow is classified as **actual, committed, expected or hypothetical**, and the classification is visible everywhere.
- FR-C4 Minimum cash requirement, with shortfall/surplus per bucket and the first-shortfall date.
- FR-C5 New actuals automatically mark forecasts stale and trigger a re-run as a new version. History is kept for forecast-accuracy tracking.
- FR-C6 Sensitivity analysis and multiple scenarios.

### 5.5 Three-statement projections (Phase 3)
- FR-P1 Linked forecast P&L, balance sheet and cash flow statement, starting from the actual balance sheet at the cut-over date.
- FR-P2 Assumptions cover revenue growth, gross margin, opex, D&A, capex, working capital, tax, financing, interest, repayments and dividends.
- FR-P3 Integrity invariants (BS balances exactly; CF cash = BS cash; roll-forwards tie) are checked on every run. Invalid runs cannot be published.

### 5.6 KPIs
- FR-K1 Standard KPI library (profitability, liquidity, efficiency, growth, stability) with documented formulas and conventions.
- FR-K2 Users select, customise and create KPIs in a validated formula language with unit checking. Workspace-wide definitions require approval and are versioned.
- FR-K3 Each KPI value shows its components and source data, and "not meaningful" cases are explicit.
- FR-K4 Operational (non-ledger) metrics such as customers, headcount and MRR can be entered or imported, labelled as non-ledger.

### 5.7 Goals
- FR-G1 Goals at workspace, entity, department, project or individual level, on any KPI/metric, with a target value and date.
- FR-G2 For each goal: frozen baseline, actual progress, projected outcome, gap, required performance (goal-seek), trends, alerts on material deviation, scenario testing, and deterministic driver contribution analysis.

### 5.8 Budgeting & variance
- FR-B1 Annual, monthly/quarterly, departmental and project budgets. Rolling forecasts.
- FR-B2 Versioned revisions with approval. Approved versions are immutable, and original and current budgets are both reportable.
- FR-B3 Budget vs actual, forecast vs actual, and prior-year comparisons. Favourable/unfavourable is direction-aware.
- FR-B4 Required variance explanations above thresholds, plus performance alerts.
- FR-B5 Excel import/export of budgets with validation and a preview.

### 5.9 Scenarios (Phase 3; simple what-ifs in Phase 2 for cash)
- FR-S1 Scenarios = base + ordered, typed overrides (percent/absolute change, timing shift, new loan, new hire, capex, one-off cash event, rate change).
- FR-S2 Effects shown on cash, P&L, BS, liquidity, ratios, KPI targets, debt obligations and stability. Every change is traceable to its override.
- FR-S3 Scenarios are always hypothetical. Promoting one to a budget/forecast is an explicit, approved action.

### 5.10 Management reporting & dashboard
- FR-M1 Report packs (executive overview, profitability, cash, working capital, budget performance, KPI scorecard, forecast statements, risks, goals, commentary) frozen as reproducible snapshots, with review → final.
- FR-M2 Comparison columns: actual, budget (original/current), forecast and prior year, for user-selected periods.
- FR-M3 Excel and PDF export with provenance footers. Exported values equal on-screen values.
- FR-D1 CFO dashboard with configurable widgets, interactive charts, KPI cards, forecast graphs, goal progress, scenario comparison, alerts, and drill-down to transactions.
- FR-D2 **Actual vs forecast vs hypothetical is always visually distinct** (doc 10 §10.1), including in exports.
- FR-D3 Firm portfolio dashboard across granted clients.

### 5.11 Tax, audit & compliance (Phase 4; foundations earlier)
- FR-X1–X3 (from v1): rules engine-only tax computations with trace, human sign-off before export, judgment records.
- FR-X4 VAT codes on journal lines from Phase 1, so bookkeeping is VAT-correct before return preparation exists.

### 5.12 Evidence (all phases)
- FR-E1 Hash-chained audit events for all financial, planning-approval and professional actions.
- FR-E2 Evidence pack export per period. FR-E3 Approved budgets, published forecasts and final report packs are reproducible from stored inputs.

### 5.13 AI (Phase 5; constraints apply to the design now)
- FR-A1 Off by default per workspace. Explicit admin enablement and data-class policy.
- FR-A2 The AI uses only deterministic, read-only tools for figures. Every number in an AI answer must come from a tool result, and unmatched numbers are removed and flagged.
- FR-A3 AI output is visually distinct from verified calculations, labelled as a draft, and states uncertainty when evidence is incomplete.
- FR-A4 No write access to the ledger, budgets, filings or rules. Proposed scenarios and commentary require a user to accept them.
- FR-A5 Supported question types: variance causes, cash problem drivers, goal-seek ("how much more revenue…"), timing what-ifs, cost-vs-revenue growth, deteriorating KPIs, and assumptions needed to hit targets.

## 6. Non-functional requirements

| Area | Requirement |
|---|---|
| Correctness | Decimal only. Documented rounding. Zero tolerance for unbalanced entries or non-reconciling projections. Deterministic, reproducible calc runs (identical output hash). |
| Data integrity | Actual and forecast data are never stored in the same field without a nature tag. The actuals read model can be rebuilt from the ledger and is verified nightly. |
| Security | OWASP ASVS L2 (L3 for auth/tenancy/ledger). MFA. Per-workspace keys. DB-enforced isolation. |
| Privacy | GDPR as processor (firm/business data) and as **controller** (personal workspaces). EU residency. Consumer terms for individuals. |
| Performance | TB for 1M lines < 3 s p95. Dashboard first load < 1.5 s p95. 13-week forecast for 10k open items < 2 s. 3-statement 60-month projection < 3 s. Scenario re-run < 3 s. |
| Availability | 99.5% initial, RPO ≤ 15 min, RTO ≤ 4 h (to confirm). |
| Accessibility | WCAG 2.2 AA. Charts do not rely on colour alone. |
| UX | Premium, clean and modern, built for decisions rather than decoration. Every chart answers a named question. EN/EL. |
| Operability | No unapproved production or pilot deployments or migrations. |

## 7. MVP definition and success metrics

**MVP = Phase 1 + Phase 2.** A business (and you personally) can keep reconciled books and see a
trustworthy 13-week cash forecast, monthly budget vs actual, core KPIs and goal progress.

| Metric | Target |
|---|---|
| Unbalanced posted entries / cross-tenant incidents | 0 (hard invariant) |
| Forecast reproducibility | 100% of published runs reproduce their output hash |
| 13-week forecast accuracy (pilot) | Tracked from week 1. Target to be set after 8 weeks of baseline. |
| Time to monthly management view after period close | < 1 hour (pilot measurement) |
| Your own weekly active use during pilot | Qualitative usefulness log maintained |

## 8. Risks (product level; technical risks are in MASTER-PLAN §6)
| Risk | Mitigation |
|---|---|
| Scope breadth (accounting + tax + audit + FP&A + personal) overwhelms a small team | Strict phase gates. MVP = Phases 1–2. Shared engines (ledger, taxonomy, calc framework) built once. |
| Forecasts mistaken for facts | Nature tagging end-to-end, visual contract, provenance footers, tests |
| Incorrect tax rules / regulatory change | Curator workflow, official examples, human sign-off (Phase 4) |
| Personal-finance consumer obligations | Counsel review before public personal sign-up. Pilot limited to you. |
| Over-reliance on AI | Read-only, tool-sourced numbers, drafts only, uncertainty flags |
| Garbage-in forecasts (unreconciled banks, unmapped accounts) | Data-quality gates and warnings shown on every forecast |
