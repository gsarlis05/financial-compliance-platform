# 11 — Customer Types and Secure Coexistence (Firm, Business, Personal)

Status: **DRAFT for review** · Extends [04](04-auth-and-tenant-isolation.md) · ADR-0008

## 1. Requirement
One person may be, at the same time:
- an employee or partner of an **accounting firm**,
- the owner or finance manager of **one or more businesses**,
- an **individual** managing personal finances,

…and the firm may also serve that same person's business. The data must stay **logically and securely
separated**, while identity, infrastructure and calculation engines are shared.

## 2. Model: one identity, many workspaces

```
                         USER (global identity, one login + MFA)
                ┌──────────────┼──────────────────┬───────────────────────┐
           membership     membership         membership              engagement grant
                │              │                  │                       │ (via firm membership)
                ▼              ▼                  ▼                       ▼
   ┌────────────────┐ ┌──────────────────┐ ┌─────────────────┐   ┌───────────────────────┐
   │ Workspace      │ │ Workspace        │ │ Workspace       │   │ Workspace             │
   │ kind=FIRM      │ │ kind=BUSINESS    │ │ kind=PERSONAL   │   │ kind=BUSINESS         │
   │ "Sarlis & Co"  │ │ "My Company Ltd" │ │ "My finances"   │   │ "Client X Ltd" (owns  │
   │ hosted clients │ │ own books        │ │ net worth, budg.│   │  its own data; firm   │
   │ (entities)     │ │                  │ │                 │   │  has a granted access)│
   └────────────────┘ └──────────────────┘ └─────────────────┘   └───────────────────────┘
        tenant_id A        tenant_id B          tenant_id C              tenant_id D
```

- **Workspace = tenant** (the RLS boundary from doc 04). `tenant.kind ∈ {FIRM, BUSINESS, PERSONAL}`.
- A user's **personal workspace is a separate tenant** from any business workspace they own. There is no shared table rows, no shared entity and no shared ledger.
- Each request runs in **exactly one workspace context** (`app.tenant_id`). Switching workspace is an explicit UI action that changes the URL (`/w/{workspace}/…`), the context and the visual theme/banner (e.g. a "Personal" label and colour). This prevents posting into the wrong books.

## 3. How firms access clients: two supported patterns

| Pattern | When | Data owner | Mechanism |
|---|---|---|---|
| **Firm-hosted client** | The client is not a platform user | Firm workspace (legal entity inside the FIRM tenant) | Entities inside tenant A, with firm roles scoped per entity (as in doc 04) |
| **Client-owned workspace + engagement** | The business uses the platform itself and engages a firm | The business's own tenant (D) | An **Engagement grant**: tenant D's owner grants firm A a scoped, time-bound role set (e.g. bookkeeping, tax prep, audit read-only, CFO advisory read-only). Firm users with an assignment to that engagement act **inside tenant D's context**, with permissions = intersection(engagement scope, their firm role). |

- Engagement grants are approved by the client's owner/admin, and revocable at any time with immediate effect (sessions re-check on each request).
- Grants are audited in **both** tenants (the client sees every action by firm users, attributed to person + firm).
- **The firm portfolio dashboard** ("all my clients") is built by iterating per-tenant queries under each granted context, or by reading **per-client summary metrics** that the firm is entitled to. There is never a cross-tenant SQL query. Firm-level aggregates exist only inside the firm's own tenant as derived, non-transactional data, which is removed when a grant is revoked (configurable retention of firm working papers per professional obligations).
- Migration path: a firm-hosted client can be **transferred** into a client-owned workspace (a documented, audited export/import with both parties' consent).

## 4. Personal ↔ business: separation rules
1. **No automatic data flow** between a personal and a business workspace, even with the same owner.
2. Transactions between them (owner salary, dividends, director loans, drawings) are recorded **in each set of books independently**, as they would be in reality. An optional "counterpart hint" can **suggest** the matching personal entry when a business payment to the owner is posted, but this requires explicit user confirmation in the personal workspace and is never posted automatically.
3. A **personal net-worth view may include an ownership stake** in the business, as a user-entered valuation (nature `EXPECTED`/valuation-dated). Live business data is not pulled. A later, optional feature is an explicit **read-only "summary share"** from the business workspace to the owner's personal workspace (e.g. equity book value, cash balance), granted by the business admin and revocable. It is off by default.
4. **Firms never see personal workspaces** unless the individual creates an explicit engagement grant (e.g. for an advisor). It is off by default, and the personal UI states it plainly.
5. AI settings, retention policies, encryption keys and exports are **per workspace**. A personal workspace has its own data key.

## 5. Feature availability by workspace kind

| Capability | FIRM | BUSINESS | PERSONAL |
|---|---|---|---|
| Multiple legal entities | ✔ (clients) | ✔ (group companies) | ✖ (one household book) |
| Full double-entry UI, journals, approvals, period lock | ✔ | ✔ | Hidden (simplified transactions; double entry underneath; locking optional) |
| Bank reconciliation | ✔ | ✔ | Simplified (match imported statement) |
| Budgets, cash forecasting, goals, scenarios, KPIs | ✔ (per client) | ✔ | ✔ (personal taxonomy, personal KPI set) |
| Three-statement projections | ✔ | ✔ | Personal projection (net worth + cash) |
| Tax/VAT workflows, audit module | ✔ | ✔ (if no firm) | ✖ (in current roadmap) |
| Management report packs | ✔ | ✔ | Personal summary report |
| Engagement grants to firms | Receives | Grants | Grants (advisor, optional) |
| Portfolio dashboard across clients | ✔ | ✖ | ✖ |

Feature availability is enforced by **feature flags per workspace kind and plan**, checked
server-side by the authz layer. Hiding features in the UI alone is not enough.

## 6. Roles by kind (additions to doc 04 §3.2)
- **PERSONAL:** `Owner` (all), optional `Partner/Household member` (shared household finances, explicit invite), optional `Advisor (read-only)` via a grant.
- **BUSINESS:** `Owner`, `Finance Manager/CFO`, `Department Budget Owner` (edit own department's budget, view own department's variance), `Viewer`, plus engagement-derived firm roles.
- **FIRM:** as doc 04, plus `CFO Advisory` (FP&A on clients, no posting).
- **Department/project scoping:** budget and variance permissions can be scoped to dimension values (e.g. only department "Sales"). This is enforced in authz and in query filters for FP&A endpoints.

## 7. Privacy and legal implications
- Personal workspaces make the platform a **consumer service**, so it needs consumer terms, GDPR as **controller** (vs processor for firm/business customer data), and clear AI consent. **Counsel review is required** before personal accounts are opened to the public.
- Personal financial data can reveal special-category information indirectly (e.g. health expenses, union fees, religious donations). These are treated as high sensitivity: AI is off by default, and category names are excluded from analytics telemetry.

## 8. Using the platform yourself during development
The directive allows your own use with realistic data but forbids real confidential client data in
unapproved environments. Proposed rules:

| Environment | Data allowed | AI |
|---|---|---|
| `dev` (local/CI) | **Synthetic only** (generated fixtures, including a realistic synthetic "household" and "Demo Trading Ltd") | Mock provider or approved provider with synthetic data only |
| `staging` | Synthetic only | Same as dev |
| **`pilot`** (new): production-grade controls (EU region, MFA, encryption, backups, audit, monitoring), separate account/project, invite-only | **Your own personal and own-business data**. **No third-party client data** until the GA security gate (pen-test, DPA) is passed | Disabled by default. You may enable it for **your personal workspace only**, with an approved provider configuration (EU, zero data retention) |
| `prod` | Customer data | Per tenant policy |

- `pilot` deployments follow the same approval rule as production. **I will not create or deploy it without your explicit approval** (directive: no unapproved production deployments).
- Data never flows pilot → dev/staging. Bug reproduction uses synthetic data or field-level anonymised extracts produced by an approved, audited tool.
- Your own business data may still contain **third-party personal data** (customers' and employees' names, IBANs). It is treated as confidential, so the same AI and logging rules apply.
- Before the pilot exists, you can test usefulness locally with a **synthetic-but-realistic data generator** that is parameterised to resemble your situation (income levels, cost structure) without real records.

## 9. Isolation tests specific to coexistence
- The same user with personal (C) and business (B) workspaces: no API route returns C data in a B context or vice versa, including dashboards, search, exports, AI context and notifications.
- A firm user with engagement on D: access is limited to the engagement scope. Revoking the grant makes the next request return 404, and the firm portfolio no longer shows D metrics after the revocation job.
- Engagement scope intersection: a firm "Partner" with an engagement scope of "audit read-only" cannot post.
- A department-scoped budget owner cannot read other departments' budget lines or variances (API + export).
- The workspace switch changes the context. Replaying a request with a stale workspace in the body (not the path) is ignored.
- A personal workspace is invisible to firm admins, including in user-management lists (only the user's name/email appears, via firm membership).
