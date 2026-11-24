"""Isolation for alert email preferences and the email outbox (M8-5), and two narrow functions.

- ``dashboards_alert_email_tenant_ids()``: the scheduled sender runs with the runtime role, which
  may not list workspaces. It reveals only the IDs of workspaces with email to send or digests to
  prepare; the job then works on each under its normal row-level security context.
- ``dashboards_alert_email_unsubscribe(token)``: the one-click "stop these emails" link works
  without signing in. It turns off exactly the preference that holds the token and says whether
  it found one; it reveals nothing else.
Both are owned by ``fcp_maintenance`` when that role exists, like the other job functions.
"""

from django.db import migrations

from fcp.core.db.operations import tenant_isolation

SQL = """
CREATE OR REPLACE FUNCTION dashboards_alert_email_tenant_ids() RETURNS SETOF uuid
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT tenant_id FROM dashboards_alert_email_preference WHERE mode <> 'OFF'
   UNION SELECT tenant_id FROM dashboards_alert_email WHERE status = 'PENDING'
   ORDER BY 1 $$;

CREATE OR REPLACE FUNCTION dashboards_alert_email_unsubscribe(token text) RETURNS boolean
    LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = public AS
$$ WITH off AS (UPDATE dashboards_alert_email_preference SET mode = 'OFF', updated_at = now()
                WHERE unsubscribe_token = token AND length(token) >= 32 RETURNING 1)
   SELECT EXISTS (SELECT 1 FROM off) $$;

REVOKE ALL ON FUNCTION dashboards_alert_email_tenant_ids() FROM PUBLIC;
REVOKE ALL ON FUNCTION dashboards_alert_email_unsubscribe(text) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') THEN
        GRANT SELECT (tenant_id, mode) ON dashboards_alert_email_preference TO fcp_maintenance;
        GRANT UPDATE (mode, updated_at) ON dashboards_alert_email_preference TO fcp_maintenance;
        GRANT SELECT (unsubscribe_token) ON dashboards_alert_email_preference TO fcp_maintenance;
        GRANT SELECT (tenant_id, status) ON dashboards_alert_email TO fcp_maintenance;
        GRANT CREATE ON SCHEMA public TO fcp_maintenance;
        ALTER FUNCTION dashboards_alert_email_tenant_ids() OWNER TO fcp_maintenance;
        ALTER FUNCTION dashboards_alert_email_unsubscribe(text) OWNER TO fcp_maintenance;
        REVOKE CREATE ON SCHEMA public FROM fcp_maintenance;
    END IF;
END $$;
"""

REVERSE = """
DROP FUNCTION IF EXISTS dashboards_alert_email_unsubscribe(text);
DROP FUNCTION IF EXISTS dashboards_alert_email_tenant_ids();
"""


class Migration(migrations.Migration):
    dependencies = [("dashboards", "0007_alert_emails")]

    operations = [
        *tenant_isolation("dashboards_alert_email_preference"),
        *tenant_isolation("dashboards_alert_email"),
        migrations.RunSQL(SQL, REVERSE),
    ]
