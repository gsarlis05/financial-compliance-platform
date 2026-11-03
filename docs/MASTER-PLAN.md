# Master Plan — v2 (Accounting · Compliance · FP&A · CFO Intelligence)

Status: **DRAFT for review**. No application code will be written until this plan is approved.
Date: 2026-11-03 · Supersedes the v1 planning scope.

## 1. What changed in v2
| Area | v1 | v2 |
|---|---|---|
| Customers | Firms + SMEs | **Firms, businesses, and individuals**, with secure coexistence for one person in several roles |
| MVP | Ledger + VAT | **Ledger + bank + reporting (Phase 1), then cash forecasting, budgets, KPIs, goals and the CFO dashboard (Phase 2)**. Tax workflows move to Phase 4. |
| Architecture | Accounting/tax/audit modules | Adds a **Planning & CFO domain** (8 modules) on a **shared calculation framework**, plus supporting registers (open items, obligations, debt, fixed assets, tax calendar) |
| Data model | ~35 entities | +35 entities (engagements, dimensions, registers, plans, assumptions, scenarios, calc runs + lineage, KPIs, goals, report packs, dashboards, alerts) |
| Environments | dev/staging/prod | Adds an **owner-only pilot** so you can use the platform with your own data (requires your approval) |

## 2. Product objective
1. **What has happened?** An immutable double-entry ledger, reconciled to the bank and mapped to a financial taxonomy.
2. **What is likely to happen, and what can management do about it?** Deterministic, versioned forecasts, budgets, scenarios, KPIs and goals, built on the ledger and **never confused with it**.

## 3. Architecture in one picture
```
 Shared infrastructure: identity + MFA · workspaces/tenancy (RLS) · authz · audit trail · documents · workflow/approvals · calendar · Money/Decimal
 ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
 "What happened"                      │ Shared calculation framework (metrics)  │ "What next"
 ledger · banking · registers ───────►│ taxonomy · evaluator · calc runs ·      │──► cashflow · budgeting · projections · kpi ·
 reporting.actuals (read model)       │ lineage · nature types                  │    goals · scenarios · mgmt_reporting · dashboards
 tax · rules · audit_engagement       │ (also used by the tax rules engine)     │    AI CFO (read-only tools, Phase 5)
```
Details: [SAD v2](planning/02-software-architecture.md) §2, §10, §11 · ADR-0007/0008/0009.

**Five non-negotiables for FP&A** ([doc 10 §1](planning/10-cfo-fpa-specification.md)):
1. The ledger is the only historical truth.
2. Every number has a nature (actual, committed, expected, hypothetical, budget, forecast or target).
3. Deterministic, reproducible runs pinned to a ledger watermark.
4. Approved artefacts are versioned, never overwritten.
5. AI never calculates; every AI number comes from a deterministic tool.

## 4. How the three customer types coexist securely
Summary of [doc 11](planning/11-account-types-and-coexistence.md):
- **One identity, many workspaces.** Each firm, business and personal book is a **separate tenant**, isolated by PostgreSQL RLS, with its own encryption key, AI policy and retention.
- Each request acts in **exactly one workspace**, chosen by the URL path. Switching is explicit and visually distinct, so it is hard to post into the wrong books.
- Firms access clients as **firm-hosted entities** or via **engagement grants** from client-owned workspaces. Grants are scoped, time-bound, revocable, and audited on both sides. Firms never see personal workspaces without the individual's explicit grant.
- Personal ↔ business: there is **no automatic data flow**. Owner transactions are recorded in each set of books. An optional confirm-only "counterpart hint" is available. The business stake in a personal net-worth view is a user-entered valuation.
- Same engines, different experiences: feature entitlements per kind are enforced server-side.

## 5. Roadmap and MVP priorities
Full backlog: [doc 08 v2](planning/08-implementation-backlog.md).

| Phase | Milestones | Outcome |
|---|---|---|
| 1 Accounting foundation | M0 foundations · M1 tenancy + ledger · M2 registers, banking, reporting | Reconciled books, statements and drill-down. Compliance foundations (MFA, isolation, audit, locking, VAT codes). |
| 2 FP&A MVP | M3 calc framework + 13-week cash · M4 budgets, KPIs, goals, CFO dashboard v1 · M5 personal MVP + pilot readiness | **MVP.** Then **Gate P**: you use it with your own data. |
| 3 Advanced FP&A | M6 3-statement + rolling · M7 scenarios, sensitivity, working capital · M8 management packs, dashboard v2 | Full CFO toolkit. Then **Gate G**: external customers. |
| 4 Compliance | M9 rules + VAT · M10 CIT/SDC + IFRS · M11 audit + regulatory monitoring | Professional firm workflows |
| 5 AI CFO | M12 AI gateway + CFO assistant · M13 regulatory explanations | Explanations, commentary drafts, risk identification |

**MVP priority order** (build in this order; each step is useful on its own):
1. Ledger you trust (M1)
2. Reconciled bank + open AR/AP (M2), because a cash forecast is only as good as these
3. 13-week cash forecast (M3), the single most valuable CFO tool for SMEs
4. Monthly budget vs actual (M4)
5. Core KPIs + goals (M4)
6. CFO dashboard v1 (M4)
7. Personal workspace (M5)

**Deliberately deferred from the MVP:**
- 3-statement projections, the full scenario engine, management packs (Phase 3)
- Rolling 12/24-month forecasts (Phase 3; a monthly current-FY cash view is in the MVP)
- Tax returns (Phase 4)
- AI (Phase 5)

**Trade-off to decide:** with tax in Phase 4, Cyprus accounting firms get little compliance value
until late. If early firm customers matter, move **M9 (VAT)** before M6. Cost: about 4–6 weeks' delay to advanced FP&A.

## 6. Technical dependencies and implementation risks

### 6.1 Critical dependency chain
```
Money/Decimal ─► ledger (posting_seq watermark) ─► dimensions ─► open items + bank reconciliation ─► taxonomy mapping ─► actuals read model
      └────────────────────────────────────────────► calendar + expression evaluator ─► calc_run/lineage ─► 13-week cash ─► budgets/KPIs ─► goals ─► dashboard
fixed assets + debt schedules + assumption sets ─► 3-statement engine ─► scenarios/sensitivity ─► management packs ─► AI CFO tools
expression evaluator ─► rules engine (Phase 4)
```
Key implications:
- **Open AR/AP items move into Phase 1.** Without them, the 13-week forecast is guesswork.
- **Dimensions must exist in the ledger before budgets.** Departmental budgets need departmental actuals.
- **The calc framework (M3) is built before any user-visible forecast,** so every module shares it.

### 6.2 Risks
| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R1 | Scope breadth vs a small team | High / High | Phase gates; MVP = Phases 1–2; shared engines; no parallel feature fronts |
| R2 | Forecast quality limited by data quality (unreconciled banks, missing due dates, unmapped accounts) | High / High | Data-quality gates and warnings on every forecast; mapping tasks; open-item discipline in the UX |
| R3 | Actual and forecast confusion in UI or exports | Medium / High | Nature types end-to-end, visual contract, provenance footers, snapshot tests |
| R4 | 3-statement model correctness (circularity, rounding, roll-forwards) | Medium / High | No circularity by default, line-level cent rounding, invariant checks per run, golden models signed off by a finance professional |
| R5 | Performance of interactive scenarios and dashboards | Medium / Medium | Precomputed actuals facts, input-hash caching, worker queues, performance budgets in CI |
| R6 | Custom formula DSL abused or too limited | Medium / Medium | Sandboxed evaluator, unit typing, fuzzing; extend functions deliberately |
| R7 | Personal-finance consumer and GDPR controller obligations | Medium / High | Owner-only pilot; counsel review before public personal sign-up (Gate G) |
| R8 | Cyprus tax facts in the cash calendar (e.g. provisional tax dates) are wrong | Medium / Medium | Manual calendar in Phase 2; only curator-verified templates; Phase 4 rules engine |
| R9 | Using your own real data during development leaks into dev or AI | Low / High | ADR-0010: synthetic dev/staging, separate pilot, AI off, no pilot→dev path |
| R10 | Delayed compliance value for firms | Medium / Medium | Optional resequencing (§5 trade-off) |
| R11 | Frontend complexity (premium interactive dashboard) | Medium / Medium | ECharts + a component library; design system early in M4; usability testing with you |

### 6.3 Licensing notes (new components)
Apache ECharts (Apache-2.0), AG Grid Community (MIT; Enterprise features are commercial, so avoid them unless licensed),
TanStack Table (MIT), openpyxl (MIT), WeasyPrint (BSD), Hypothesis (MPL-2.0, test-only). Avoid
AGPL/SSPL BI tools (e.g. Metabase AGPL) embedded in the product unless licensed commercially.

## 7. Testing and acceptance
- Phase 1: [doc 09](planning/09-milestone-1-acceptance-criteria.md) (M1) + [doc 12 §3](planning/12-fpa-testing-and-acceptance.md) (M2).
- Phase 2 MVP: [doc 12 §4](planning/12-fpa-testing-and-acceptance.md) (calc framework, 13-week cash, budgets, KPIs, goals, dashboard, personal and coexistence).
- Strategy: golden models signed off by a finance professional, property-based invariants, reproducibility hashes, nature-separation tests, boundary/NM cases, immutability tests, isolation/coexistence/scope suites, and export fidelity.

## 8. Decisions I need from you (one consolidated list; answer by number)
Defaults are in *italics*. "Accept all defaults except …" is a valid answer. This replaces the earlier 26-question list.

**Inputs & people**
1. Research/legal documents: share them, or say "none". *Default: none; the drafts are the baseline.*
2. A Cyprus-qualified **tax professional** to verify rule packs and the tax-payment calendar (needed by Phase 4; calendar templates are needed earlier).
3. A **finance professional** to sign off the golden FP&A models: you, or someone else? *Default: you, if you have finance training.*
4. Counsel for GDPR (processor and controller roles), consumer terms, retention and liability. *Default: required before Gate G.*

**Scope & priorities**
5. Approve the five-phase roadmap and **MVP = Phases 1–2**. *Default: approve.*
6. VAT resequencing: keep tax in Phase 4, or move M9 before M6 for early firm customers? *Default: keep, because you are the first user.*
7. What will you dogfood: personal only, or also a real business you own? (This affects whether Gate P includes business data.)
8. Multi-currency in Phase 1, or in Phase 3? *Default: Phase 1 if your own or target businesses trade in USD/GBP; otherwise Phase 3.*
9. Import sources for Phase 1: bank CSV, CAMT.053 XML, Excel, or which legacy accounting software?
10. Filing stays prepare-and-export only (no automatic submission). *Default: yes.*
11. Languages: English + Greek. *Default: yes; English first in the MVP, Greek by Gate G.*

**Architecture (ADRs 0001–0010)**
12. Stack: Python/Django, PostgreSQL 17 and React/TypeScript. *Default: approve.*
13. Modular monolith + isolated AI gateway. *Default: approve.*
14. Shared schema + RLS, with **workspace kinds as separate tenants** + engagements. *Default: approve.*
15. Planning domain separated from the ledger, read model, nature tagging, shared calc framework. *Default: approve.*
16. Tax rules as versioned data, with the expression evaluator shared with FP&A. *Default: approve.*
17. AI is read-only and tool-sourced, off by default. *Default: approve.*
18. Charting/grid: ECharts + TanStack Table (or AG Grid Community). *Default: approve.*

**FP&A conventions** (changeable later, but fixed defaults make testing possible)
19. KPI conventions: average balances = (opening + closing)/2; days = actual days in period; DPO based on COGS. *Default: approve.*
20. AR collection forecast: due date + trailing-12-month average days late per customer (minimum 5 invoices, else 0). *Default: approve.*
21. Interest in projections: on the opening balance, with no circularity. *Default: approve.*
22. Goal status thresholds: on track / at risk within materiality / off track. Default materiality is 5% of target. *Default: approve.*

**Environments & operations**
23. Cloud and region. *Default: AWS eu-central-1, with DR in another EU region.*
24. Identity provider. *Default: Keycloak.*
25. **Gate P:** approve in principle an owner-only pilot environment (created only after Phase 2 acceptance and your final go-ahead). *Default: approve in principle.*
26. Uptime and recovery: 99.5% uptime, RPO 15 minutes, RTO 4 hours. *Default: accept for pilot.*
27. Team size and languages, which affects item 12 and the timeline.
28. Working method: one PR per backlog item, reviewed by you before merge. *Default: yes.* Should I open a PR now for this planning branch? *Default: yes.*

## 9. Document map
| Doc | Status |
|---|---|
| [00 Review & assumptions](planning/00-review-and-assumptions.md) | v1 + v2 note |
| [01 PRD v2](planning/01-product-requirements.md) | **Rewritten** |
| [02 SAD v2](planning/02-software-architecture.md) | **Updated** (§2 modules, §10 planning, §11 workspaces) |
| [03 ERD](planning/03-entity-relationship-model.md) | **Extended** (§6 workspaces, §7 registers, §8 planning) |
| [04 Auth & isolation](planning/04-auth-and-tenant-isolation.md) | v1 + pointer to 11 |
| [05 Ledger spec](planning/05-financial-ledger-spec.md) | v1 (still valid) |
| [06 Rules engine spec](planning/06-regulatory-rules-engine-spec.md) | v1 (evaluator now shared) |
| [07 Threat model](planning/07-security-threat-model.md) | **Extended** (T23–T34) |
| [08 Roadmap & backlog v2](planning/08-implementation-backlog.md) | **Rewritten** |
| [09 M1 acceptance](planning/09-milestone-1-acceptance-criteria.md) | **Updated** (workspace kinds, watermark) |
| [10 CFO & FP&A spec](planning/10-cfo-fpa-specification.md) | **New** |
| [11 Customer types & coexistence](planning/11-account-types-and-coexistence.md) | **New** |
| [12 FP&A testing & Phase 2 acceptance](planning/12-fpa-testing-and-acceptance.md) | **New** |
| [ADRs 0001–0010](adr/) | 0007–0010 **new**; all Proposed |
