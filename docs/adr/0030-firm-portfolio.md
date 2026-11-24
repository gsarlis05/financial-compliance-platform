# ADR-0030: The firm portfolio is computed per request, per entity, under the user's permissions
Status: **Proposed** (M4-9; awaiting product owner review in PR) · Date: 2026-11-10

## Context
Doc 10 §10 and AC-DB6: a firm sees a portfolio of its clients with summary metrics. It shows
only granted clients, and after a revocation the client disappears and its derived metrics are
purged. Engagement grants to client-owned workspaces arrive in M5-4. The M4 brief limits the
portfolio to the client entities in the firm's own workspace that the user can access.

## Decision
- `GET /w/{slug}/portfolio?month=` is a workspace route that needs `planning.read`; an
  entity-scoped grant is enough. It exists in **firm workspaces only** (doc 11 §5, the
  `client_portfolio` feature). Business and personal workspaces get a 403 from the server, and
  the menu hides the page there.
- It lists the active entities for which the user holds `planning.read`, read from the role
  assignments on every request. It then builds each row with that entity's own services and the
  user's own permissions:
  - the latest cash forecast (opening, first shortfall, freshness);
  - gross margin, current ratio and DSO from the latest year-to-date KPI set;
  - goal counts by status;
  - open alert counts.
- A part the user may not see, or one without data, says so (as on the dashboard).
- **Nothing is stored.** There is no portfolio table or cache, and no query spans workspaces. A
  revoked client therefore disappears on the next request, with nothing derived left to purge.

## Consequences
- The cost grows with the number of clients (a few queries each). That is fine for M4 firm sizes.
  A materialised summary, with purge on revocation, can be added if a firm grows large, and
  would then need its own purge test.
- In M5-4, engagement grants add rows for clients in their own workspaces, through the grant and
  never by a cross-tenant query. Done in ADR-0034.
