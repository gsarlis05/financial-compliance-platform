# 08 — Phased Implementation Backlog

Status: **DRAFT for review**. Sizes: S ≤ 2 days, M ≤ 1 week, L ≤ 2 weeks (one engineer). Each item ships with the directive's
feature checklist (requirements, design, DB changes, security controls, tests, edge cases, sample data, validation, docs, limitations).

## Milestone 0 — Foundations (no business features)
| ID | Item | Size | Depends |
|---|---|---|---|
| M0-1 | Repo layout (`backend/`, `frontend/`, `infra/`, `docs/`), ADR template, CONTRIBUTING, CODEOWNERS, PR template | S | — |
| M0-2 | CI: lint, type-check (mypy strict for domain), tests, coverage gate, Semgrep, SCA, secret scan, import-linter module contracts, `no-float` rule | M | M0-1 |
| M0-3 | Local dev: docker-compose (Postgres 17, IdP, MinIO, mail catcher); seed scripts | S | M0-1 |
| M0-4 | `Money`/`Decimal` core library + rounding policies + property tests | S | M0-1 |
| M0-5 | Problem+json error framework, correlation IDs, structured logging with redaction + tests | S | M0-1 |
| M0-6 | Terraform skeleton for staging (EU region), no prod yet | M | — |

## Milestone 1 — Secure tenancy + core ledger (see [09](09-milestone-1-acceptance-criteria.md))
| ID | Item | Size | Depends |
|---|---|---|---|
| M1-1 | OIDC login (BFF), MFA enforcement via `amr`, session mgmt, logout, step-up primitive | M | M0 |
| M1-2 | Tenants, legal entities, memberships, invitations | M | M1-1 |
| M1-3 | Roles/permissions, entity-scoped assignments, central authz, route-permission declarations + CI check | M | M1-2 |
| M1-4 | RLS framework: tenant context middleware, `SET LOCAL`, FORCE RLS migrations, schema check in CI, isolation test harness | M | M1-2 |
| M1-5 | Audit log: append-only, hash-chained, transactional outbox, verification job | M | M1-4 |
| M1-6 | Chart of accounts (CRUD, hierarchy, CY/IFRS template import) | M | M1-4 |
| M1-7 | Fiscal years & periods, status transitions | S | M1-6 |
| M1-8 | Journal entries: draft/submit/approve/post state machine, validations, DB constraints/triggers, gapless numbering, idempotency | L | M1-5, M1-7 |
| M1-9 | Reversal & adjustment workflows; period soft-close/lock; unlock with dual approval | M | M1-8 |
| M1-10 | Account balances + trial balance + GL report + CSV export (injection-safe) | M | M1-8 |
| M1-11 | Integrity job (balance, snapshot, sequence, chain) + admin integrity view | S | M1-10 |
| M1-12 | Minimal UI: login, entity switcher, CoA, journal entry form, approval inbox, TB, period management | L | M1-3…M1-10 |
| M1-13 | Sample data fixtures ("Demo Trading Ltd") | S | M1-8 |
| M1-14 | Docs: user guide (ledger), API reference (OpenAPI), runbooks (integrity alert, unlock) | S | all |

## Milestone 2 — Documents, banking, FX
- M2-1 Document vault: upload pipeline (MIME sniff, AV, limits, per-tenant envelope encryption, retention classes, legal hold), links to entries.
- M2-2 Malicious-input test corpus + sandboxed preview worker.
- M2-3 FX rates (ECB import + manual), multi-currency lines, rounding line, revaluation.
- M2-4 Bank accounts, CSV/CAMT.053 import (defusedxml), matching rules, reconciliation report.
- M2-5 Year-end close/open entries, closing checklist.
- M2-6 IFRS report mapping + draft balance sheet/P&L with reconciliation checks.
- M2-7 Evidence pack export (period: entries, docs, approvals, audit-chain proof).

## Milestone 3 — Rules engine + VAT
- M3-1 Rules engine core: DSL parser/evaluator, applicability resolver, trace, determinism tests.
- M3-2 Rule-pack repository + import pipeline, JSON Schema, signing, publish workflow (2-person).
- M3-3 Source library (verified source documents, hashes, locators).
- M3-4 `CY.VAT` pack v1 with official examples (**requires Cyprus tax curator**).
- M3-5 Tax codes on journal lines, VAT computation, VAT return preparation, reconciliation to the control account.
- M3-6 Review/sign-off, freeze, export (PDF + structured). "Filed externally" recording.
- M3-7 Judgment records.

## Milestone 4 — Corporate tax + AI assistant (read-only)
- M4-1 `CY.CIT` (2025 and 2026 versions) and `CY.SDC` packs; boundary and loss tests; IR4 preparation data.
- M4-2 AI Gateway service (separate deploy, network policy, mTLS), data-class policy, redaction, provider adapter, output validator.
- M4-3 AI tasks: explain computation (from trace), inconsistency finder (rules-based pre-checks + AI narrative), memo draft with citations.
- M4-4 Prompt-injection / fabrication red-team suite in CI.
- M4-5 AI admin settings, usage audit, sub-processor disclosures.

## Milestone 5 — Hardening & pilot GA
- DR drill, load tests at deadline-scale, pen-test + remediation, ASVS L2 sign-off, DPA/RoPA, support break-glass tooling, status page, onboarding for pilot firms. Production go-live **only with explicit approval**.

## Later phases
Audit engagement module (working papers, PBC, sampling, sign-offs) · IFRS statements + notes + iXBRL ·
Sales/purchase invoicing (EN 16931) + Peppol adapter · Greece jurisdiction pack · OSS/VIES ·
consolidation · fixed assets · payroll (separate decision).
