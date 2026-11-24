-- Database roles (docs/planning/04 §4 L3, ADR-0002). Run once per cluster as a superuser:
--   psql -v owner_password=... -v app_password=... -v db_name=fcp -f scripts/db/create_roles.sql
--
-- fcp_owner: owns the schema, runs migrations and the test suite. NOT a superuser and
--            NOBYPASSRLS, so FORCE ROW LEVEL SECURITY applies to it as well.
-- fcp_app:   the runtime role. Data access only (grants are applied after each migration);
--            it can never change the schema or bypass row-level security.

SELECT format('CREATE ROLE fcp_owner LOGIN NOSUPERUSER CREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L',
              :'owner_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_owner') \gexec

SELECT format('CREATE ROLE fcp_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD %L',
              :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_app') \gexec

-- fcp_maintenance: NOLOGIN, BYPASSRLS. It owns exactly one SECURITY DEFINER function that lists
-- workspace IDs (no data) so platform jobs (audit verification, integrity checks) can visit every
-- workspace; each visit then runs under that workspace's normal RLS context.
SELECT 'CREATE ROLE fcp_maintenance NOLOGIN NOSUPERUSER BYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') \gexec
GRANT fcp_maintenance TO fcp_owner;

-- Membership lets fcp_owner (tests) run `SET ROLE fcp_app` to verify the runtime role's limits.
GRANT fcp_app TO fcp_owner;

SELECT format('ALTER DATABASE %I OWNER TO fcp_owner', :'db_name') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO fcp_app', :'db_name') \gexec
