# ADR-0002: Shared-schema multi-tenancy with PostgreSQL Row-Level Security
Status: **Accepted** · Date: 2026-11-03 (accepted by product owner 2026-11-03)
## Context
Many small tenants (firms, SMEs). Isolation must not depend solely on application code.
## Decision
A `tenant_id` column on all tenant-owned tables; `FORCE ROW LEVEL SECURITY` with policies on `current_setting('app.tenant_id')`; app role `NOBYPASSRLS`; `SET LOCAL` per transaction; composite `(tenant_id, id)` FKs; CI schema checks and a cross-tenant test suite.
## Consequences
+ DB-enforced isolation; one schema to migrate. − Care is needed with connection pooling (transaction mode + SET LOCAL), and RLS adds a small query overhead. A dedicated-DB "cell" can be offered later for large tenants.
## Alternatives considered
Schema-per-tenant (migration fan-out, catalog bloat); DB-per-tenant (cost/ops at SME scale).
