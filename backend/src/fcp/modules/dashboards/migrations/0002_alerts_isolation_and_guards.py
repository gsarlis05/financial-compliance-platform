"""Isolation and history for alerts (M4-7), enforced by the database.

- FORCE row-level security and composite tenant keys on alerts and alert states.
- An alert is never deleted, and its content never changes. The only update is its
  acknowledgement, once.
- Alert states are never deleted (they are what prevents raising the same alert twice).
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("dashboards_alert", "dashboards_alert_state")
ACK = "ARRAY['acknowledged_by_id', 'acknowledged_at', 'acknowledgement_note']"

GUARDS = rf"""
CREATE OR REPLACE FUNCTION dashboards_alert_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'alerts are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.acknowledged_at IS NOT NULL OR NEW.acknowledged_at IS NULL
       OR (to_jsonb(NEW) - {ACK}) IS DISTINCT FROM (to_jsonb(OLD) - {ACK}) THEN
        RAISE EXCEPTION 'an alert can only be acknowledged, once'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER dashboards_alert_guard BEFORE UPDATE OR DELETE ON dashboards_alert
    FOR EACH ROW EXECUTE FUNCTION dashboards_alert_guard();

CREATE OR REPLACE FUNCTION dashboards_alert_state_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'alert states are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NEW.key IS DISTINCT FROM OLD.key OR NEW.legal_entity_id IS DISTINCT FROM OLD.legal_entity_id
       OR NEW.changes < OLD.changes THEN
        RAISE EXCEPTION 'an alert state only moves forward'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER dashboards_alert_state_guard BEFORE UPDATE OR DELETE ON dashboards_alert_state
    FOR EACH ROW EXECUTE FUNCTION dashboards_alert_state_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS dashboards_alert_state_guard ON dashboards_alert_state;
DROP FUNCTION IF EXISTS dashboards_alert_state_guard();
DROP TRIGGER IF EXISTS dashboards_alert_guard ON dashboards_alert;
DROP FUNCTION IF EXISTS dashboards_alert_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("dashboards", "0001_alerts"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity") for t in TABLES],
        migrations.RunSQL(GUARDS, reverse_sql=REVERSE),
    ]
