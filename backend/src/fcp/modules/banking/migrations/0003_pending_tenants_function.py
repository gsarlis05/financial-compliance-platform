"""``banking_pending_tenant_ids()``: the workspaces that have statement imports waiting.

The import worker runs with the runtime role, which may not list workspaces (``app_tenant_ids`` is
for maintenance jobs). This function reveals only the IDs of workspaces with PENDING imports; the
worker then processes each under its normal row-level security context. It is owned by the NOLOGIN
``fcp_maintenance`` role (BYPASSRLS) when that role exists, and the runtime role may execute it
(``fcp.core.db.registry.RUNTIME_FUNCTIONS``).
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION banking_pending_tenant_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT DISTINCT tenant_id FROM banking_statement_import WHERE status = 'PENDING'
   ORDER BY tenant_id $$;

REVOKE ALL ON FUNCTION banking_pending_tenant_ids() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') THEN
        GRANT SELECT (tenant_id, status) ON banking_statement_import TO fcp_maintenance;
        -- A new owner needs CREATE on the schema while ownership changes; revoked right after.
        GRANT CREATE ON SCHEMA public TO fcp_maintenance;
        ALTER FUNCTION banking_pending_tenant_ids() OWNER TO fcp_maintenance;
        REVOKE CREATE ON SCHEMA public FROM fcp_maintenance;
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("banking", "0002_banking_isolation"), ("tenancy", "0003_tenant_ids_function")]
    operations = [
        migrations.RunSQL(SQL, reverse_sql="DROP FUNCTION IF EXISTS banking_pending_tenant_ids();")
    ]
