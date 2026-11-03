# ADR-0008: Workspace kinds as separate tenants, with firm↔client engagement grants
Status: Proposed · Date: 2026-11-03
## Context
The platform serves firms, businesses and individuals; one person may be all three. Personal and business data must be securely separated, while firms need scoped access to clients.
## Decision
`tenant.kind ∈ {FIRM, BUSINESS, PERSONAL}`; each personal or business book is its own tenant (RLS boundary). A global user identity has memberships in many workspaces; each request acts in exactly one workspace selected by URL path. Firms reach client-owned workspaces through `ENGAGEMENT` grants (scope ceiling, time-bound, client-approved, revocable, audited both sides) and operate *inside* the client's tenant context. Firm-hosted clients (entities inside the firm tenant) remain supported. Feature availability is governed by server-side entitlements per kind/plan.
## Consequences
+ Reuses the existing RLS model unchanged; strong separation for the same owner; clear data ownership. − Firm portfolio views require per-tenant iteration or entitled summary metrics; engagement lifecycle adds workflow.
## Alternatives considered
Personal and business as entities within one tenant (weaker separation, shared keys/policies); cross-tenant RLS policies for firms (complex, error-prone).
