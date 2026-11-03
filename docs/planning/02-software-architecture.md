# 02 — Software Architecture Document (SAD)

Status: **DRAFT for review** · Related ADRs: [../adr/](../adr/)

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
                                      │   reporting, evidence   │   rule tests, exports)       │
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
| `tenancy` | Tenants, entities, memberships, roles, grants, auditor engagements | `tenant`, `legal_entity`, `membership`, `role_assignment`, `access_grant` | identity |
| `ledger` | CoA, fiscal periods, journals, posting, balances, FX | `account`, `fiscal_year`, `period`, `journal_entry`, `journal_line`, `account_balance`, `fx_rate` | tenancy, rules (read-only for VAT codes) |
| `rules` | Regulatory rule packs, versions, evaluation engine, test suites | `rule_pack`, `rule_version`, `rule_test_case`, `source_reference` | — (pure) |
| `tax` | VAT/corporate tax computations, returns, judgments | `tax_computation`, `tax_return`, `judgment_record` | ledger (read), rules |
| `audit_engagement` (phase 3) | Engagements, working papers, PBC, sampling, sign-offs | `engagement`, `working_paper`, … | ledger (read), documents |
| `documents` | Upload, scanning, hashing, storage, retention, links | `document`, `document_link`, `retention_policy` | storage, AV scanner |
| `banking` | Statement import, matching, reconciliation | `bank_account`, `bank_txn`, `reconciliation` | ledger |
| `workflow` | Generic approvals, SoD policy, sign-offs | `approval_request`, `approval_step`, `signoff` | tenancy |
| `audit_log` | Append-only hash-chained event log, evidence packs | `audit_event`, `audit_chain_anchor` | — |
| `reporting` | TB, GL, statements, IFRS mapping, exports | `report_mapping`, `report_snapshot` | ledger (read) |
| `ai` (client side) | Request building, data-class filtering, draft storage | `ai_request`, `ai_draft` | AI Gateway |

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
   • tools exposed to the model: read-only retrieval over the request's allowed refs + verified source index; NO write tools
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
