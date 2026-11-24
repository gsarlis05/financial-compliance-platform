# 14 — Milestone 1 Implementation Brief: Secure Tenancy + Core Ledger

Status: **APPROVED for implementation** (product owner go-ahead 2026-11-03). Acceptance criteria: [09](09-milestone-1-acceptance-criteria.md).

## 1. Business purpose
Give a firm, a business or an individual a secure workspace in which balanced journal entries are
recorded through an approval workflow, corrected only by reversal, protected by period locks, and
summarised in a trial balance they can trust. Every later feature (bank reconciliation, VAT,
forecasting, the CFO dashboard) reads from this ledger, so its correctness and isolation come first.

## 2. Dependencies and regulatory requirements
- Builds on Milestone 0 (Money, errors, logging, CI gates, local services).
- Relevant obligations: integrity and immutability of books (the Companies Law requires proper books
  of account); evidence trail (directive principle 10); GDPR security of processing (Art. 32); and
  segregation of duties as good practice for professional firms.
- No external services beyond the OIDC identity provider (Keycloak locally).

## 3. Technical approach (ADR-0011 records the library choices)
| Area | Approach |
|---|---|
| API | **Django Ninja** (typed, Pydantic v2, generated OpenAPI). Money is serialised as strings. Every operation declares a permission via `@requires(...)`, and a CI test fails on any undeclared route. |
| Login | OIDC Authorization Code + PKCE with **Authlib**, in the backend-for-frontend pattern: tokens stay server-side, and the browser holds only a `__Host-` session cookie. The `amr`/`acr` claims must prove MFA, otherwise login is refused. Step-up is based on `auth_time`. |
| IDs | UUIDv7 (time-ordered) generated in `fcp.core.ids`. |
| Tenancy | `tenancy` module: workspaces (FIRM, BUSINESS, PERSONAL), legal entities, memberships, invitations, entity-scoped role assignments. System roles and permissions are defined in code. |
| Isolation | Workspace from the URL path (`/api/w/{slug}/…`) → membership check → `SET LOCAL app.tenant_id` in the request transaction → **PostgreSQL RLS (`FORCE`) on every tenant table**, plus composite `(tenant_id, id)` foreign keys. The app connects as a non-owner role without `BYPASSRLS`. |
| Audit | Append-only, per-tenant hash-chained `audit_event`, written in the same transaction as the change. UPDATE/DELETE are blocked by trigger and grants. Includes a verification command. |
| Ledger | Accounts, fiscal years and periods, journals, entries with the DRAFT→SUBMITTED→APPROVED→POSTED workflow, SoD, a `content_hash`-bound approval, gapless numbering, a per-tenant `posting_seq` watermark, and idempotency keys. The **database enforces** balance (deferred constraint trigger), line validity, immutability of posted rows and period status. |
| Corrections | Reversal (once only, enforced by a unique index), adjustment entries, soft-close and lock, and unlock with two distinct approvers plus step-up. The unlock is time-boxed and postings during it are tagged. |
| Reports | Account balances maintained at posting; trial balance (period or date); general ledger; CSV export with formula-injection escaping. |
| Integrity | A `ledger_integrity_check` command (balance, snapshots versus lines, gapless numbers, audit chain) with stored results and an admin endpoint. |
| UI | React + React Router + TanStack Query. Login, workspace and entity switcher (distinct per kind), chart of accounts, entry form with live decimal totals (decimal.js), approval inbox, trial balance, periods. |

**Grouping:** each backlog item is one PR, except M1-6 (chart of accounts) and M1-7 (periods), which ship together because the posting rules need both.

## 4. Acceptance criteria and tests
Doc 09 sections A–G, unchanged. The headline tests:
- A cross-tenant test sweeps **every route**.
- Direct-SQL tamper tests run as the app role.
- Property-based tests check that the trial balance always balances.
- 50 concurrent posts must produce gapless numbers.
- Unlock requires two distinct approvers with step-up.

## 5. Risks and licensing
| Risk | Mitigation |
|---|---|
| RLS misconfiguration silently exposes data | A schema check fails CI on any tenant table without FORCE RLS and a policy; tests run as a non-superuser without BYPASSRLS. |
| MFA claim formats differ between IdPs | Accepted `amr`/`acr` values are configurable; tests cover the claim check. A live Keycloak end-to-end login is a manual check (TOTP enrolment can't be automated headlessly in CI). |
| Concurrency (numbering, balances) | Row locks on sequence and balance rows; a concurrency test with 50 parallel posts. |
| Scope size | Items ship in order; each PR stands alone and is reviewable. |

Licences: Django Ninja (MIT), Authlib (BSD-3-Clause), requests (Apache-2.0), responses (Apache-2.0, test only), decimal.js (MIT), React Router (MIT), TanStack Query (MIT). All permissive.

## 6. Out of scope (per doc 09)
Documents, bank import, multi-currency posting, VAT, tax, AI, financial statements, engagements between firms and clients (M5-4), and custom roles.
