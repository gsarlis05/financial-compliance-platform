"""``app_tenant_ids()``: workspace IDs for platform jobs (audit verification, integrity checks).

The function returns IDs only, no workspace data. It is owned by the NOLOGIN ``fcp_maintenance``
role (BYPASSRLS) when that role exists; each job then visits a workspace under its normal RLS
context. Without the role (a bare developer database) it only sees what RLS allows.
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION app_tenant_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT id FROM tenancy_tenant WHERE status = 'ACTIVE' ORDER BY id $$;

REVOKE ALL ON FUNCTION app_tenant_ids() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') THEN
        GRANT USAGE ON SCHEMA public TO fcp_maintenance;
        GRANT SELECT (id, status) ON tenancy_tenant TO fcp_maintenance;
        -- A new owner needs CREATE on the schema at the moment ownership changes; it is
        -- revoked straight afterwards so the role can never create objects.
        GRANT CREATE ON SCHEMA public TO fcp_maintenance;
        ALTER FUNCTION app_tenant_ids() OWNER TO fcp_maintenance;
        REVOKE CREATE ON SCHEMA public FROM fcp_maintenance;
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0002_isolation")]
    operations = [migrations.RunSQL(SQL, reverse_sql="DROP FUNCTION IF EXISTS app_tenant_ids();")]
