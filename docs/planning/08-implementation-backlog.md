# 08 — Phased Roadmap and Implementation Backlog — v2

Status: **DRAFT v2 for review** (re-sequenced per the FP&A scope update).
Sizes: S ≤ 2 days, M ≤ 1 week, L ≤ 2 weeks (one engineer). Every item ships with the directive's feature
checklist: business requirements, technical design, DB changes, security controls, automated tests, edge cases,
sample data, user-facing validation, docs, and known limitations.

## Overview

```
Phase 1  Accounting foundation      M0 Foundations ─► M1 Tenancy + core ledger ─► M2 Registers, banking, reporting
Phase 2  Financial management MVP   M3 Calc framework + 13-week cash ─► M4 Budgets, KPIs, goals, CFO dashboard v1 ─► M5 Personal MVP + pilot readiness
                                    ══ Gate P: owner-only pilot (your own data) — requires your explicit approval ══
Phase 3  Advanced FP&A              M6 3-statement + rolling forecasts ─► M7 Scenarios + sensitivity + WC ─► M8 Mgmt reporting + dashboard v2
                                    ══ Gate G: external customers — pen-test, DPA, consumer terms, DR drill ══
Phase 4  Professional compliance    M9 Rules engine + VAT ─► M10 CIT/SDC + IFRS statements ─► M11 Audit module + regulatory monitoring
Phase 5  AI CFO intelligence        M12 AI gateway + AI CFO (read-only tools) ─► M13 Source-linked regulatory explanations
```

**Compliance foundations pulled into Phase 1** (needed for correct accounting and secure operation):
MFA, tenant isolation, audit trail, period locking, immutability, VAT codes on lines (for VAT-correct
bookkeeping), document retention basics, and log redaction.

Gate G is placed after Phase 3, so external firms/businesses can use bookkeeping + FP&A before tax
workflows exist. **If you want Cyprus firms as early customers, consider moving M9 (VAT) before M6.** See MASTER-PLAN §5.

---

## Phase 1 — Accounting foundation

### M0 — Foundations (no business features)
| ID | Item | Size |
|---|---|---|
| M0-1 | Repo layout (`backend/`, `frontend/`, `infra/`, `docs/`), ADR template, CONTRIBUTING, CODEOWNERS, PR template | S |
| M0-2 | CI: lint, mypy strict (domain), tests + coverage gates, Semgrep, SCA, secret scan, import-linter module contracts (incl. planning→ledger ban), `no-float` rule | M |
| M0-3 | Local dev: docker-compose (Postgres 17, IdP, MinIO, mail catcher) | S |
| M0-4 | `Money`/`Decimal` library + rounding policies + property tests | S |
| M0-5 | Errors (problem+json), correlation IDs, structured logging + redaction tests | S |
| M0-6 | **Synthetic data generator v1**: "Demo Trading Ltd", a synthetic household, and a parameterised generator to mimic realistic profiles without real data | M |
| M0-7 | Terraform skeleton for staging (EU) | M |

### M1 — Secure tenancy + core ledger (acceptance: [09](09-milestone-1-acceptance-criteria.md))
| ID | Item | Size |
|---|---|---|
| M1-1 | OIDC login (BFF), MFA enforcement, sessions, step-up | M |
| M1-2 | Workspaces with kind FIRM/BUSINESS/PERSONAL, legal entities, memberships, invitations, workspace switcher with visual distinction | M |
| M1-3 | Roles/permissions, entity-scoped assignments, central authz, feature entitlements by kind, route-permission CI check | M |
| M1-4 | RLS framework + schema CI check + isolation harness | M |
| M1-5 | Audit log (hash-chained, outbox), verification job | M |
| M1-6 | CoA + templates (CY business, personal) | M |
| M1-7 | Fiscal years, periods, status transitions | S |
| M1-8 | Journal entries state machine, DB constraints, gapless numbering, idempotency, **per-tenant posting_seq watermark** | L |
| M1-9 | Reversal/adjustment; soft-close/lock; dual-approved unlock | M |
| M1-10 | Account balances, TB, GL, CSV export | M |
| M1-11 | Integrity job + admin integrity view | S |
| M1-12 | Minimal UI (login, workspace/entity switch, CoA, entry form, approvals, TB, periods) | L |
| M1-13 | Docs, runbooks, OpenAPI | S |

### M2 — Registers, banking, basic reporting
| ID | Item | Size |
|---|---|---|
| M2-1 | Dimensions (department, project, cost centre) on lines; required-dimension rules per account | M |
| M2-2 | Counterparties + **open items** (AR/AP invoices with due dates; settlement matching; ageing report) | L |
| M2-3 | VAT codes on lines (code catalogue as data; no return yet), VAT control account rules | M |
| M2-4 | Document vault v1 (upload pipeline, AV scan, MIME sniff, per-tenant encryption, links to entries) | L |
| M2-5 | Bank accounts, CSV/CAMT.053 import (hardened), matching rules, reconciliation, last-reconciled date | L |
| M2-6 | Financial taxonomy v1 + account mapping + mapping-completeness task | M |
| M2-7 | **`reporting.actuals` read model** (`fact_actuals_monthly`, `fact_cash_daily`) + rebuild + nightly verification | M |
| M2-8 | Basic statements: P&L, BS, indirect cash flow statement (actuals), comparatives, drill-down; Excel/PDF basic export | L |
| M2-9 | Year-end close/open entries | M |
| M2-10 | FX rates + multi-currency lines + rounding line (if multi-currency is confirmed for Phase 1; else move to M6) | M |

## Phase 2 — Financial management MVP

### M3 — Calculation framework + 13-week cash forecast
| ID | Item | Size |
|---|---|---|
| M3-1 | `calendar` service (fiscal periods, ISO weeks, business days, bucketing) + tests | S |
| M3-2 | `metrics` core: nature types (`ActualSeries`/`PlanSeries`/`BlendedSeries`), calc_run/result/lineage, input hashing, reproducibility harness | L |
| M3-3 | Expression evaluator (sandboxed, Decimal, unit typing, safe division); shared with the future rules engine | M |
| M3-4 | Recurring obligations register; simple debt instruments + schedule generator (annuity/linear/bullet; day counts) | M |
| M3-5 | Tax payment calendar (manual entry; templates pre-filled only with curator-verified dates) | S |
| M3-6 | Customer payment behaviour (observed days late) + overrides | S |
| M3-7 | **13-week cash forecast engine**: opening cash, AR/AP, obligations, debt, tax, capex commitments, manual items; natures; minimum cash; shortfall | L |
| M3-8 | Staleness/event-driven re-runs; forecast history + accuracy metrics | M |
| M3-9 | Simple cash what-ifs (timing shift, one-off, % change) as sandbox runs | M |
| M3-10 | Cash dashboard UI (13-week chart with nature encoding, buckets table, drill-down, data-quality warnings) | L |

### M4 — Budgets, KPIs, goals, CFO dashboard v1
| ID | Item | Size |
|---|---|---|
| M4-1 | Budgets: plans, versions, lifecycle, approvals, immutability, revisions | M |
| M4-2 | Budget entry grid, phasing methods, Excel import (hardened) / export | L |
| M4-3 | Budget vs actual, forecast vs actual, prior year; direction-aware variance; thresholds; explanation workflow | M |
| M4-4 | KPI standard library (core set: margins, current/quick/cash ratio, runway, DSO, DPO, CCC, growth, D/E, interest coverage), definitions versioned, NM handling | M |
| M4-5 | Custom KPIs (private) + workspace KPIs with approval; operational metrics entry | M |
| M4-6 | Goals: definition, baseline, evaluations, goal-seek (additive, ratio, threshold), status, alerts, contribution analysis | L |
| M4-7 | Alerts framework (in-app) | S |
| M4-8 | CFO dashboard v1: widget grid, KPI cards, cash chart, BvA table, goal progress, alerts, period controls, drill-down; nature visual contract | L |
| M4-9 | Firm portfolio dashboard v1 (per-client summary metrics over granted clients) | M |

### M5 — Personal MVP + pilot readiness
| ID | Item | Size |
|---|---|---|
| M5-1 | Personal workspace UX: accounts, simplified transactions + categories, net-worth statement | L |
| M5-2 | Personal budgets, goals (savings, emergency fund, debt payoff), 12-month personal cash projection | M |
| M5-3 | Business ↔ personal counterpart hint (opt-in, confirm-only) | S |
| M5-4 | Engagement grants (client-owned workspaces ↔ firms), revocation | M |
| M5-5 | Pilot environment IaC (separate account, prod-grade controls), backup/restore drill, monitoring. **Created/deployed only after your approval (Gate P)** | M |
| M5-6 | Data export (full workspace export, so you always own your data) + workspace deletion flow | M |

**Gate P (owner-only pilot):** isolation and coexistence suites green, backup/restore tested, MFA
enforced, AI disabled, a security review of Phases 1–2, and your written approval.

## Phase 3 — Advanced FP&A
- **M6** Fixed-asset register + depreciation; driver/assumption sets; **integrated three-statement projection engine** with invariants; rolling 12/24-month forecasts; blended full-year outlook; quarterly/annual views.
- **M7** Scenario modelling (all override types, lineage, comparisons); sensitivity + tornado; working-capital forecasting (DSO/DIO/DPO driven); goal evaluation against scenarios; advanced KPIs (ROA/ROE, DSCR, net debt/EBITDA, inventory metrics).
- **M8** Management report packs (templates, snapshots, commentary, review/final, Excel/PDF with provenance); dashboard v2 (customisable layouts, scenario comparison widgets, saved views); performance alerts by email.
- **Gate G (external customers):** independent pen-test + remediation, ASVS L2 sign-off, DPA/RoPA/sub-processors, consumer terms for personal accounts (counsel), DR drill, load test, support break-glass tooling, status page.

## Phase 4 — Professional compliance integration
- **M9** Rules engine (packs, versions, curation workflow, source library), `CY.VAT` pack with official examples, VAT return preparation + sign-off + export, judgment records. Tax payment calendar fed from computations.
- **M10** `CY.CIT` (2025/2026 boundary), `CY.SDC`, IR4 preparation data; projections use the CIT pack for tax expense; IFRS statements with notes scaffolding; iXBRL if required.
- **M11** Audit engagement module (materiality, working papers, PBC, sampling, sign-offs); regulatory change monitoring workflow; evidence pack v2.

## Phase 5 — AI CFO intelligence
- **M12** AI Gateway (separate deploy, mTLS, network policy, EU/ZDR provider), data-class policy, read-only FP&A tools, numeric-provenance validator, AI panel UI, red-team suite; tasks: variance explanation, cash driver analysis, goal-seek explanation, scenario proposals, commentary drafts, deteriorating-KPI scan.
- **M13** Source-linked regulatory explanations over the verified source library; uncertainty flagging; professional-review routing.

## Later (unscheduled)
Consolidation and intercompany · invoicing with EN 16931 / Peppol · Greece pack · OSS/VIES · payroll ·
PSD2 bank feeds · personal tax estimation · Monte Carlo (seeded, labelled) · mobile app.
