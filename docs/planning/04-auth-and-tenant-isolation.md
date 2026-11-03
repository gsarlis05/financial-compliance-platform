# 04 — Authentication, Authorization and Tenant-Isolation Design

Status: **APPROVED v2 (2026-11-03)**. Customer types, engagements, dimension scoping and personal workspaces are specified in [11](11-account-types-and-coexistence.md) and extend this document.

## 1. Goals
1. Only authenticated, MFA-verified people and scoped service clients can access data.
2. A user sees only the tenants/entities they are granted, with least privilege.
3. **A defect in application code alone must not be able to leak data across tenants.** The database enforces isolation independently.
4. Every privileged action is attributable and auditable.

## 2. Authentication

| Aspect | Design |
|---|---|
| Protocol | OIDC Authorization Code + PKCE via a dedicated IdP (Keycloak or managed EU IdP). The app never stores passwords. |
| MFA | Mandatory for all users. WebAuthn/passkeys preferred, TOTP allowed, SMS not allowed. The app verifies the `amr`/`acr` claim on every login and rejects tokens without MFA. |
| Step-up auth | Re-authentication with MFA (max_age ≤ 5 min) required for: posting above threshold, period unlock, return sign-off, rule publishing, role changes, data export, support-access approval. |
| Enterprise SSO | Tenant-level SAML/OIDC federation through the IdP. A tenant can enforce "SSO only". |
| Sessions | BFF pattern: the SPA talks to the API with a **server-side session cookie** (`HttpOnly; Secure; SameSite=Lax`, `__Host-` prefix). OIDC tokens stay server-side. Idle timeout 30 min, absolute 12 h (tenant-configurable, stricter only). CSRF token on state-changing requests. |
| Service/API clients | OAuth2 client credentials with scoped tokens bound to one tenant (and optionally entities); short-lived (≤ 15 min); keys in the secrets manager; rotation supported. |
| Account protection | IdP brute-force lockout, breached-password check, new-device and new-country notifications, admin-visible session list with revoke. |
| Recovery | MFA reset requires tenant-admin approval + identity verification. Audited, and the user is notified. |

## 3. Authorization model

**RBAC with entity scoping + explicit grants + policy checks** (a hybrid of RBAC and ABAC).

### 3.1 Permissions (examples, fine-grained strings)
`ledger.entry.create`, `ledger.entry.submit`, `ledger.entry.approve`, `ledger.entry.post`,
`ledger.entry.reverse`, `ledger.period.soft_close`, `ledger.period.lock`, `ledger.period.unlock`,
`tax.computation.run`, `tax.return.signoff`, `documents.read`, `documents.upload`, `reports.read`,
`tenant.users.manage`, `tenant.ai.configure`, `audit.evidence.export`, `rules.version.publish` (platform curators only).

### 3.2 System roles (tenants may clone and customise, never escalate beyond their own permissions)
| Role | Summary |
|---|---|
| Tenant Admin | Users, roles, settings. **No financial approval by default** (SoD) |
| Partner | All entity permissions incl. sign-off and unlock (dual control) |
| Accountant | Create/submit entries, run computations, reconcile |
| Reviewer | Approve/post entries, approve computations |
| Client User | Upload documents, view reports for their own entity, approve if configured |
| Auditor (external) | Read-only ledger/docs/reports for the granted entity and period range; create working papers in the audit module only |
| Read-only | Reports only |

### 3.3 Decision procedure (in one place: `tenancy.authz.check(principal, permission, resource)`)
1. Principal has an active `MEMBERSHIP` in `resource.tenant_id` **or** an active `ACCESS_GRANT` on `resource.legal_entity_id`.
2. One of the principal's `ROLE_ASSIGNMENT`s for that tenant (entity-scoped or tenant-wide), still valid, includes `permission`.
3. Policy checks: SoD (`prepared_by ≠ approved_by` when required), amount thresholds, period status, step-up freshness.
4. Deny by default. Every deny is logged (security log). Denies on sensitive permissions are also audited.

All API endpoints declare their required permission. A CI test enumerates routes and fails if any route lacks a declaration.

## 4. Tenant isolation — defence in depth

| Layer | Control |
|---|---|
| L1 Request context | Middleware resolves `tenant_id` from the **URL path** (`/t/{tenant_slug}/…`), never from the request body. Membership is verified. Context is held in a request-scoped contextvar. A request with no context gets **no** tenant data. |
| L2 ORM scoping | Tenant-owned models use a manager that requires the context and injects `tenant_id`. Unscoped querysets raise. Writes set `tenant_id` from context, and client-supplied values are ignored. |
| L3 **PostgreSQL RLS** | Every tenant-owned table: `ENABLE` + `FORCE ROW LEVEL SECURITY`; policy `USING (tenant_id = current_setting('app.tenant_id')::uuid)` and the same `WITH CHECK`. The API connects as `app_rw` (not owner, `NOBYPASSRLS`). Each transaction runs `SET LOCAL app.tenant_id = …` (safe with pooling in transaction mode). Missing setting → zero rows. |
| L4 Entity scoping | Entity-level permission checks in the authz layer; plus an optional RLS predicate on `app.entity_ids` for auditor/client sessions (array setting). |
| L5 Composite FKs | `(tenant_id, x_id)` FKs make cross-tenant references structurally impossible. |
| L6 Storage | Object keys are prefixed `tenant/{tenant_id}/entity/{entity_id}/…`. Documents are envelope-encrypted with a **per-tenant data key** (KMS). Downloads use short-lived pre-signed URLs issued only after an authz check. Bucket policy denies public access. |
| L7 Caches/search/queues | Cache keys and vector-index rows include `tenant_id`. Job payloads carry `tenant_id`, and workers set the RLS context before any query. |
| L8 AI | The AI Gateway receives only content the core assembled under the user's permissions, plus `tenant_id` for logging. It has no DB access. The retrieval index is filtered by tenant **and** by the request's allowed refs. |
| L9 Operations | Platform staff have no standing data access. **Break-glass/support access** requires a ticket, tenant-admin approval (except a legally compelled or security emergency with two-person approval), is time-boxed (≤ 4 h) and read-only by default, and is audited and visible to the tenant. Migrations/maintenance run as a separate role (`app_migrate`), never from the request path. |

Cross-tenant platform functions (billing, metrics) use **aggregated, non-content** data through
dedicated views owned by a separate role.

## 5. Isolation verification (mandatory test suite)
- Fixture with tenants A and B, each with entities, entries and documents.
- For **every** API route, an automated test authenticates as A and attempts access to B's resource IDs (read, list, update, delete, export). Expect 404 (not 403, to avoid existence disclosure) and no B data in the body.
- DB-level tests: as `app_rw` without `app.tenant_id`, `SELECT` on each tenant table returns 0 rows. With A's context, inserting a row with B's `tenant_id` fails the `WITH CHECK`.
- A schema check fails CI if any table with a `tenant_id` column lacks `FORCE RLS` + policy, or if any new table lacks a tenant classification (`tenant_owned` / `global` allow-list).
- Worker tests: a job for tenant A cannot read B even when given B's IDs.
- Storage tests: a pre-signed URL for A's object is unusable after expiry, and keys are not guessable.
- Periodic production canary: synthetic tenants attempt cross-access, and an alert fires on success.

## 6. Secrets & cryptography
- TLS 1.2+ (1.3 preferred) everywhere, HSTS; internal mTLS between the API and the AI Gateway.
- At rest: managed DB encryption plus **application-level encryption** for high-sensitivity fields (TIN, VAT no., IBAN, ID numbers), using AES-256-GCM via KMS data keys. Blind index (HMAC) where lookup is needed.
- Secrets live only in the secrets manager, injected at runtime. Pre-commit + CI secret scanning.
- Key rotation: KMS automatic annual rotation for root keys; data keys rotated on schedule and re-wrapped. A tenant offboarding process includes crypto-shredding once retention obligations end.

## 7. Logging of auth events
Login success/failure, MFA challenges, step-ups, role changes, grant changes, support access and
token issuance are written to the security log (SIEM) **and** as audit events. These logs never
include tokens, passwords, or document content.
