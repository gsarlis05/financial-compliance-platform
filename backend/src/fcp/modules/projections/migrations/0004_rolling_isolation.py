"""Isolation for rolling forecast settings (M6-4), and ``projections_rolling_tenant_ids()``.

The scheduled re-run (``projections_refresh``) runs with the runtime role, which may not list
workspaces. The function reveals only the IDs of workspaces with an active rolling forecast; the
job then works on each under its normal row-level security context, as the user who set it up.
Owned by ``fcp_maintenance`` when that role exists, like ``cashflow_forecast_tenant_ids()``.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

SQL = """
CREATE OR REPLACE FUNCTION projections_rolling_tenant_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT DISTINCT tenant_id FROM projections_rolling_forecast WHERE active ORDER BY tenant_id $$;

REVOKE ALL ON FUNCTION projections_rolling_tenant_ids() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') THEN
        GRANT SELECT (tenant_id, active) ON projections_rolling_forecast TO fcp_maintenance;
        GRANT CREATE ON SCHEMA public TO fcp_maintenance;
        ALTER FUNCTION projections_rolling_tenant_ids() OWNER TO fcp_maintenance;
        REVOKE CREATE ON SCHEMA public FROM fcp_maintenance;
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("projections", "0003_rollingforecast")]

    operations = [
        *tenant_isolation("projections_rolling_forecast"),
        composite_tenant_fk(
            "projections_rolling_forecast", "legal_entity_id", "tenancy_legal_entity"
        ),
        migrations.RunSQL(
            SQL, reverse_sql="DROP FUNCTION IF EXISTS projections_rolling_tenant_ids();"
        ),
    ]
