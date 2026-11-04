"""``cashflow_forecast_tenant_ids()``: the workspaces that have cash forecasts (M3-8).

The scheduled refresh (``cashflow_refresh``) runs with the runtime role, which may not list
workspaces. This function reveals only the IDs of workspaces with at least one CASH_13W run; the
job then works on each under its normal row-level security context, with the permissions of the
user who ran the latest forecast. Owned by ``fcp_maintenance`` when that role exists, like
``banking_pending_tenant_ids()``.
"""

from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION cashflow_forecast_tenant_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT DISTINCT tenant_id FROM metrics_calc_run WHERE kind = 'CASH_13W' ORDER BY tenant_id $$;

REVOKE ALL ON FUNCTION cashflow_forecast_tenant_ids() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') THEN
        GRANT SELECT (tenant_id, kind) ON metrics_calc_run TO fcp_maintenance;
        GRANT CREATE ON SCHEMA public TO fcp_maintenance;
        ALTER FUNCTION cashflow_forecast_tenant_ids() OWNER TO fcp_maintenance;
        REVOKE CREATE ON SCHEMA public FROM fcp_maintenance;
    END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("cashflow", "0002_cashflow_isolation"),
        ("metrics", "0004_calc_runs_isolation"),
        ("tenancy", "0003_tenant_ids_function"),
    ]
    operations = [
        migrations.RunSQL(
            SQL, reverse_sql="DROP FUNCTION IF EXISTS cashflow_forecast_tenant_ids();"
        )
    ]
