# 02 — Software Architecture Document (SAD)

Status: **DRAFT v2 for review** (adds Planning & CFO domain, workspaces) · Related ADRs: [../adr/](../adr/)

## 1. Architectural style

**Modular monolith** (one deployable core API, plus workers) with strictly enforced module
boundaries, and **one separately deployed, network-isolated AI Gateway**. Modules communicate
through explicit service interfaces and domain events (an in-process outbox), never by reaching
into each other's tables. This lets us extract services later without a rewrite (ADR-0001).

```
                        ┌───────────────────────────── EU region ─────────────────────────────┐
  Browser (React SPA) ──► WAF/CDN ─► API (Django)  ──────────► PostgreSQL (RLS, NUMERIC)        │
        │                             │   modules:              ▲      ▲                        │
        │ OIDC                        │   identity, tenancy     │      │ read replica (reports) │
        ▼                             │   ledger, tax, rules    │      │                        │
   IdP (Keycloak / managed)           │   documents, audit      │   Workers (jobs, imports,    │
                                      │   reporting, evidence   │   rule tests, exports,       │
                                      │   registers, PLANNING:  │   calc runs, re-forecasts)   │
                                      │   cashflow, budgeting,  │                              │
                                      │   projections, kpi,     │                              │
                                      │   goals, scenarios,     │                              │
                                      │   mgmt_reporting, dash. │                              │
                                      │                         │                              │
                                      ├──► Object storage (SSE-KMS, versioning, Object Lock)   │
                                      │                                                         │
                                      └──(mTLS, scoped token)──► AI Gateway ──► LLM provider    │
                                                                 (separate VPC/   (EU endpoint,  │
                                                                  no DB creds)     ZDR contract) │
                        └────────────────────────────────────────────────────────────────────────┘
```

## 2. Bounded contexts (modules)

Accounting, taxation, auditing and compliance logic are separated (directive principle 3).

| Module | Responsibility | Owns tables | Depends on |
|---|---|---|---|
| `identity` | Users, MFA status mirror, sessions, service accounts | `user`, `api_client` | IdP |
| `tenancy` | Workspaces (FIRM/BUSINESS/PERSONAL), entities, memberships, roles, dimension-scoped assignments, auditor grants, **firm↔client engagements**, feature entitlements | `tenant`, `legal_entity`, `membership`, `role_assignment`, `access_grant`, `engagement`, `feature_entitlement` | identity |
| `ledger` | CoA, fiscal periods, journals, posting, balances, FX | `account`, `fiscal_year`, `period`, `journal_entry`, `journal_line`, `account_balance`, `fx_rate` | tenancy, rules (read-only for VAT codes) |
| `rules` | Regulatory rule packs, versions, evaluation engine, test suites | `rule_pack`, `rule_version`, `rule_test_case`, `source_reference` | — (pure) |
| `tax` | VAT/corporate tax computations, returns, judgments | `tax_computation`, `tax_return`, `judgment_record` | ledger (read), rules |
| `audit_engagement` (phase 3) | Engagements, working papers, PBC, sampling, sign-offs | `engagement`, `working_paper`, … | ledger (read), documents |
| `documents` | Upload, scanning, hashing, storage, retention, links | `document`, `document_link`, `retention_policy` | storage, AV scanner |
| `banking` | Statement import, matching, reconciliation | `bank_account`, `bank_txn`, `reconciliation` | ledger |
| `workflow` | Generic approvals, SoD policy, sign-offs | `approval_request`, `approval_step`, `signoff` | tenancy |
| `audit_log` | Append-only hash-chained event log, evidence packs | `audit_event`, `audit_chain_anchor` | — |
| `reporting` | TB, GL, actual financial statements, **`reporting.actuals` read model** (the only path through which any other module reads historical figures), exports | `fact_actuals_monthly`, `fact_cash_daily`, `report_snapshot` | ledger (read) |
| `ai` (client side) | Request building, data-class filtering, draft storage, tool dispatch to deterministic services | `ai_request`, `ai_draft` | AI Gateway, FP&A services (read-only) |
| `registers` | Counterparties, open AR/AP items, recurring obligations, debt instruments + schedules, fixed assets, tax payment calendar | `counterparty`, `open_item`, `recurring_obligation`, `debt_instrument`, `fixed_asset`, `tax_payment_calendar` | ledger |
| `calendar` | Fiscal periods, ISO weeks, business days, bucketing | (reference data) | ledger (fiscal years) |
| **Planning & CFO domain** (ADR-0007) | | | |
| `metrics` | **Shared calculation framework**: financial taxonomy, account mapping, expression evaluator (shared with `rules`), unit typing, KPI/metric definitions, calc-run + lineage infrastructure | `taxonomy_*`, `account_taxonomy_map`, `metric_definition*`, `calc_run`, `calc_result`, `calc_lineage` | reporting.actuals (read) |
| `cashflow` | 13-week and rolling cash forecasts, sensitivity | `plan*` (kind CASH) | metrics, registers, reporting.actuals |
| `budgeting` | Budgets, versions, revisions, phasing, variance, explanations | `plan*` (kind BUDGET), `variance_explanation` | metrics, workflow |
| `projections` | Integrated 3-statement model, rolling 12/24-month forecasts | `plan*` (kind PROJECTION), `assumption_set`, `assumption` | metrics, registers |
| `kpi` | KPI evaluation, scorecards, operational metrics | `operational_metric*` | metrics |
| `goals` | Goals, evaluations, goal-seek, contribution analysis | `goal`, `goal_evaluation` | kpi, projections/cashflow |
| `scenarios` | Scenario overrides, scenario runs, comparisons | `scenario`, `scenario_override` | projections, cashflow |
| `mgmt_reporting` | Report pack templates, snapshots, commentary, Excel/PDF export | `report_pack`, `report_section` | all planning modules (read) |
| `dashboards` | Widget configuration, alert rules and alerts | `dashboard`, `widget`, `alert_rule`, `alert` | all planning modules (read) |

**Boundary enforcement:** an import-linter contract in CI forbids cross-module imports except
through each module's `api.py`. The DB role per module is out of scope for MVP; the import-linter
plus code review suffice.

## 3. Key cross-cutting designs

### 3.1 Money and arithmetic (ADR-0003)
- Type `Money(amount: Decimal, currency: str)`. It is constructed from `str`/`Decimal` only, and `float` raises `TypeError`.
- DB: `NUMERIC(19,4)` for transaction amounts, `NUMERIC(28,10)` for FX rates and intermediate tax bases. Currency is ISO-4217 `CHAR(3)`.
- Rounding is explicit: every operation that changes scale takes a `RoundingPolicy` (default `ROUND_HALF_UP` to 2 dp for EUR display/posting). Tax rules declare their own rounding (e.g. per line vs per invoice), recorded in the trace.
- The API serialises money as JSON **strings** (`"1234.50"`). The frontend never does arithmetic on money except via a decimal library for previews. The server is authoritative.
- A lint rule forbids `float(` in domain modules, and a property-based test suite (Hypothesis) covers arithmetic invariants.

### 3.2 Tenant isolation (see [04](04-auth-and-tenant-isolation.md))
Defence in depth: request context → ORM query scoping → **PostgreSQL RLS on every tenant table**
→ per-tenant encryption keys for documents → isolation test suite.

### 3.3 Immutability and audit (see [05](05-financial-ledger-spec.md))
Posted ledger rows are protected by DB triggers (UPDATE/DELETE rejected) and an app-level state
machine. All mutations emit `audit_event` rows in the same transaction (a transactional outbox),
hash-chained per tenant. Daily chain anchors are written to WORM storage.

### 3.4 Workflow and human review
A generic `workflow` module provides approval requests with policies (who may approve, thresholds,
SoD). Ledger posting, period unlock, rule-version publish, tax return finalisation and AI-draft
acceptance all use it.

### 3.5 Error handling (principle 15)
- Domain errors are typed (`UnbalancedEntryError`, `PeriodLockedError`, …) and map to RFC 9457 problem+json with a stable `code`, a user-actionable message, and `correlation_id`.
- Nothing is swallowed. Background jobs that fail land in a visible "Failed jobs" view per tenant, with retry and alerting.
- Data-integrity checks run nightly (TB balance, balance snapshot vs line sum, audit chain verify), and any failure pages on-call.

### 3.6 Logging and privacy
Structured JSON logs carry IDs only (tenant_id, entity_id, user_id, correlation_id). A redaction
filter drops known sensitive fields (names, TINs, IBANs, amounts, document text), and a CI test
asserts redaction. Application logs are separate from the business audit log.

## 4. Data architecture
- One PostgreSQL cluster, shared schema with a `tenant_id` column on every tenant-owned table and RLS (ADR-0002). Very large or regulated tenants can later be moved to a dedicated database (cell model) using the same schema.
- Read replica for heavy reports.
- `account_balance` per (entity, account, period, currency) is maintained transactionally at posting, for performance. It is verifiable against lines.
- Backups: PITR, encrypted, cross-region within the EU, restore tested quarterly.

## 5. Integration architecture
Integrations (banks, Peppol, government portals, legacy imports) are **adapters** behind ports.
Each is per-tenant opt-in, uses separately stored scoped credentials (in the secrets manager,
referenced by ID), runs in workers, and has its own audit events. Failure of an adapter never blocks
core bookkeeping.

## 6. Deployment
- Environments: `dev` → `staging` (synthetic data only) → `prod`. Production data never leaves prod.
- IaC with Terraform. Container images are signed (cosign) and come with an SBOM. Dependency and secret scanning run in CI.
- Migrations: expand/contract pattern; generated in PRs, reviewed, applied to prod only by an approved release (directive: no unapproved production migrations).

## 7. AI architecture (ADR-0005)

**Purpose:** explain calculations, retrieve sources, flag inconsistencies, draft memos.
**Not authoritative** for any number, posting, filing or opinion.

```
Core API ── builds AIRequest(task, tenant_id, entity_id, allowed_context_refs, data_classes)
   │        • context assembled by core API under the user's permissions (never by the AI)
   │        • data-class filter (e.g. strip personal IDs, IBANs) per tenant policy
   ▼
AI Gateway (separate service, no DB credentials, egress only to LLM endpoint)
   • system prompt + tool schema fixed in code, versioned
   • retrieved documents wrapped as quoted, untrusted data ("<document>…</document>"), never instructions
   • tools exposed to the model: read-only retrieval over the request's allowed refs + verified source index, and read-only
     deterministic FP&A tools (metric series, variance breakdown, goal_seek, sandbox scenario run); NO write tools
   • every number in the output must originate from a tool result (validator enforced)
   • output validator: every citation must resolve to an ID in the supplied context/source index; otherwise stripped and flagged
   • confidence/uncertainty flags required in the output schema
   ▼
Core API stores AIDraft (status=draft, citations, model id, prompt version, hashes) → human review via workflow
```

Controls:
- **Retrieval sources:** (a) tenant documents the user can read, and (b) the **verified regulatory source library** (official texts, versioned, hashed, curated). There is no open web retrieval in-product.
- **Provider controls:** EU processing, zero data retention, no training on customer data, listed as a sub-processor. Tenants can disable AI or restrict it to non-confidential data classes.
- **Numbers:** when the AI explains a computation, it receives the engine's trace. Any figures it states are re-checked against the trace by the validator, and mismatches are flagged.
- **Prompt-injection posture:** assume documents are hostile. The model has no tools that cause side effects, so the worst case is a bad draft, which human review catches. Red-team tests live in CI (see [07](07-security-threat-model.md)).

## 8. Quality attributes → tactics

| Attribute | Tactics |
|---|---|
| Correctness | Decimal type, DB constraints, property tests, golden-file tests for reports, official worked examples for tax |
| Security | RLS, MFA, least privilege, KMS, WAF, SAST/DAST, pen-test before GA |
| Auditability | Hash-chained events, WORM anchors, rule-version trace, evidence packs |
| Modifiability | Module boundaries, rules as data, adapters |
| Availability | Stateless API, managed DB with HA, queue retries, idempotency keys |

## 9. Architecture decision log
| ADR | Title | Status |
|---|---|---|
| 0001 | Modular monolith with isolated AI gateway | Proposed |
| 0002 | Shared-schema multi-tenancy with PostgreSQL RLS | Proposed |
| 0003 | Decimal money type and explicit rounding | Proposed |
| 0004 | Regulatory rules as versioned, declarative data evaluated by deterministic code | Proposed |
| 0005 | AI as a non-authoritative, read-only, isolated service | Proposed |
| 0006 | Python/Django + PostgreSQL + React stack | Proposed |
| 0007 | Planning domain separated from ledger; actuals via a read model; nature-tagged values | Proposed |
| 0008 | Workspace kinds (firm/business/personal) as separate tenants + engagement grants | Proposed |
| 0009 | Shared calculation framework (taxonomy, expression evaluator, calc runs with lineage) | Proposed |
| 0010 | Environment and data policy (synthetic dev/staging, owner-only pilot) | Proposed |

## 10. Planning & CFO domain architecture (ADR-0007, ADR-0009)

```
 ┌──────────────────────── "What happened" ────────────────────────┐   ┌──────────── "What is likely / what to do" ────────────┐
 │ ledger (immutable, posted) ──► reporting.actuals (read model,   │   │ metrics: taxonomy · evaluator · calc_run · lineage     │
 │ registers (open items,        │  rebuildable, watermark-stamped)│──►│   ├─ cashflow (13w, rolling)   ├─ kpi                  │
 │  obligations, debt, assets)   │                                 │   │   ├─ budgeting + variance      ├─ goals (goal-seek)    │
 │ banking (reconciled cash)     │                                 │   │   ├─ projections (3-statement) ├─ scenarios            │
 └───────────────────────────────┴─────────────────────────────────┘   │   └─ mgmt_reporting · dashboards (read-only consumers) │
                    ▲  NO write path from planning to ledger              └────────────────────────────────────────────────────────┘
                    └──── only via explicit, approved user actions (e.g. "post accrual") in the ledger module itself
```

Key mechanisms:
- **One-way dependency:** planning modules depend on `reporting.actuals` and `registers` through their `api.py`. Import-linter forbids any import of `ledger` internals, and the DB role used by planning code paths has `SELECT` only on the actuals read model.
- **Watermarks:** each posted entry has a monotonically increasing per-tenant `posting_seq`. A calc run records the watermark, and "actuals as of watermark W" is exactly reproducible because posted data is append-only.
- **Event-driven staleness:** `ledger.entry.posted`, `bank.reconciled`, `openitem.changed`, `assumption.changed` → a dependency index marks affected runs stale → a debounced re-run for rolling forecasts, goals and alerts creates **new** runs. Approved budgets and final packs are never recomputed in place.
- **Calc engine execution:** pure functions over in-memory, typed data frames of `Decimal`s (no float dataframes). Runs execute in workers with time/memory limits. Results are persisted in `calc_result` with lineage. Sensitivity/scenario sandbox runs are cached (keyed by input hash) and not persisted unless saved.
- **Type-level separation of natures:** `ActualSeries`, `PlanSeries`, `HypotheticalSeries`, `BlendedSeries` (with a cut-over). Arithmetic across natures is a type error, except through `blend()`. The API's JSON schema requires `nature` on every point.
- **Frontend:** the dashboard is built from widget components bound to declarative queries. ECharts is used for charts, with a shared "nature style" theme implementing doc 10 §10.1. Drill-down routes reuse ledger report pages, and money stays string/decimal on the client.
- **Exports:** server-side XLSX (openpyxl) and PDF (WeasyPrint) from the same snapshot data used by the UI. A golden test asserts the values are equal.
- **Scaling note:** FP&A reads hit the read replica and the precomputed `fact_*` tables. Heavy runs are queued, with interactive priority for the user's own sandbox scenario runs.

## 11. Workspaces & engagements (ADR-0008)
See [11-account-types-and-coexistence.md](11-account-types-and-coexistence.md). Architecturally:
`tenant.kind` drives feature entitlements. Engagements let firm users operate **inside** a client's
tenant context (never cross-tenant queries). The URL path selects the workspace, and the RLS boundary
is unchanged from §3.2.
