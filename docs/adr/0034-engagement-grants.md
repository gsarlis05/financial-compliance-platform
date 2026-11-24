# ADR-0034: Engagement grants give a firm scoped, revocable access inside the client's own workspace
Status: **Proposed** (M5-4; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 11 §3: a business that uses the platform itself can engage a firm. The business owns its
data. Its owner grants the firm a scoped, time-bound set of roles. Firm users act **inside the
client's workspace**, with permissions equal to the intersection of the engagement scope and
their firm role. Grants are revocable at any time with immediate effect, and audited in both
workspaces. The firm portfolio includes granted clients, and there is never a cross-tenant SQL
query. ADR-0008 fixed the model; this ADR records how it is built.

## Decision
- **The grant lives in the client's workspace** (`tenancy_engagement`): the firm (by ID and its
  name when granted), the scope roles, all legal entities or one, and an end date of at most 3
  years. Only the client's own workspace-wide administrators can grant or revoke, with a recent
  sign-in. A grant never changes; it can only be revoked (trigger).
- **Roles that can be granted:** accountant, reviewer and read only. Ownership and
  administration are never granted. A personal workspace can grant read only.
- **The firm staffs the engagement in its own workspace** (`tenancy_engagement_staff`): which of
  its members work on which client. Assignments can only be removed (trigger).
- **Access is worked out on every request.** When a user opens a workspace they are not a member
  of, the server asks for their access through engagements they are staffed on. Then:
  - the request runs in the **client's** row-level security context, like any member's request;
  - the user's roles are **scope ∩ what their workspace-wide firm role covers** (a firm
    accountant can fill accountant and read only; a reviewer, reviewer and read only; a partner
    or administrator, any granted role; read only, read only);
  - a revoked or expired grant, a removed assignment or a lost firm membership means a 404 on the
    next request. Nothing is cached.
- **Audit in both workspaces.** Every action a firm user takes is recorded in the client's audit
  trail under their own name, with the firm and engagement (`via_engagement`). Grants and
  revocations are recorded in the client's trail; staffing in the firm's.
- **The firm portfolio** adds a row per entity of each engaged client. It enters each client's
  context in turn (one workspace at a time, under the engagement's permissions) and returns to
  the firm's. Nothing is stored, so a revoked client is gone on the next request.
- **No application query crosses workspaces.** Four narrow SECURITY DEFINER functions, owned by
  the NOLOGIN `fcp_maintenance` role, answer only what the caller is entitled to know:
  - `app_firm_lookup(slug)`: the ID and name of an active firm, so a client can name it;
  - `app_firm_engagements()`: active grants made to the current firm workspace;
  - `app_engagement_access(slug)`: the current user's own access to one client workspace;
  - `app_engaged_workspaces()`: the client workspaces the current user can reach that way.

## Consequences
- A firm user sees an engaged client in the workspace list, marked "through your firm", and works
  there with the normal screens.
- `app_firm_lookup` tells any signed-in user whether an address belongs to a firm, and its name.
  Addresses carry a random suffix, and firms share theirs on purpose.
- Entity-scoped firm roles do not count towards an engagement; only workspace-wide firm roles do.
- Firm working papers about a client (a later module) will need their own retention rule on
  revocation (doc 11 §3). Today the firm stores nothing about the client except the assignment.
- Transferring a firm-hosted client into its own workspace (doc 11 §3) remains a later feature.
