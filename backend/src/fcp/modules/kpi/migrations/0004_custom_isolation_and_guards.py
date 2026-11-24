"""Isolation and history for custom KPIs and operational metrics (M4-5), enforced by the database.

- FORCE row-level security and composite tenant keys; a value belongs to its metric's legal entity.
- A custom KPI version is never deleted and its content never changes. Only its decision may be
  recorded, along these status changes: SUBMITTED to APPROVED or REJECTED; APPROVED or ACTIVE to
  SUPERSEDED or RETIRED (AC-KP4: values name the version they were computed with).
- An operational value is never deleted; the only change is superseding it, once.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("kpi_custom", "kpi_operational_metric", "kpi_operational_value")

GUARDS = r"""
CREATE OR REPLACE FUNCTION kpi_custom_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    changed text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'KPI versions are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT coalesce(array_agg(n.key), '{}') INTO changed
      FROM jsonb_each(to_jsonb(NEW)) n JOIN jsonb_each(to_jsonb(OLD)) o USING (key)
     WHERE n.value IS DISTINCT FROM o.value;
    IF NOT changed <@ ARRAY['status', 'decided_by_id', 'decided_at', 'decision_comment']
       OR NOT ((OLD.status = 'SUBMITTED' AND NEW.status IN ('APPROVED', 'REJECTED'))
               OR (OLD.status IN ('APPROVED', 'ACTIVE') AND NEW.status IN ('SUPERSEDED', 'RETIRED')
                   AND NOT changed && ARRAY['decided_by_id', 'decided_at', 'decision_comment']))
    THEN
        RAISE EXCEPTION 'KPI version % cannot change from % to %', OLD.version, OLD.status,
            NEW.status USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER kpi_custom_guard BEFORE UPDATE OR DELETE ON kpi_custom
    FOR EACH ROW EXECUTE FUNCTION kpi_custom_guard();

CREATE OR REPLACE FUNCTION kpi_operational_value_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'operational values are kept; enter a correction instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'operational values are immutable; a correction adds a new version'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER kpi_operational_value_guard BEFORE UPDATE OR DELETE ON kpi_operational_value
    FOR EACH ROW EXECUTE FUNCTION kpi_operational_value_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS kpi_operational_value_guard ON kpi_operational_value;
DROP FUNCTION IF EXISTS kpi_operational_value_guard();
DROP TRIGGER IF EXISTS kpi_custom_guard ON kpi_custom;
DROP FUNCTION IF EXISTS kpi_custom_guard();
"""


def _sql(sql: str, reverse: str) -> migrations.RunSQL:
    return migrations.RunSQL(sql, reverse_sql=reverse)


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("kpi", "0003_custom_and_operational"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity") for t in TABLES],
        _sql("ALTER TABLE kpi_operational_metric ADD CONSTRAINT kpi_operational_metric_entity_id_key "
             "UNIQUE (legal_entity_id, id)",
             "ALTER TABLE kpi_operational_metric DROP CONSTRAINT kpi_operational_metric_entity_id_key"),
        _sql("ALTER TABLE kpi_operational_value ADD CONSTRAINT kpi_operational_value_same_entity "
             "FOREIGN KEY (legal_entity_id, metric_id) REFERENCES kpi_operational_metric "
             "(legal_entity_id, id)",
             "ALTER TABLE kpi_operational_value DROP CONSTRAINT kpi_operational_value_same_entity"),
        _sql("ALTER TABLE kpi_custom ADD CONSTRAINT kpi_custom_entity_id_key "
             "UNIQUE (legal_entity_id, id)",
             "ALTER TABLE kpi_custom DROP CONSTRAINT kpi_custom_entity_id_key"),
        _sql("ALTER TABLE kpi_custom ADD CONSTRAINT kpi_custom_supersedes_same_entity "
             "FOREIGN KEY (legal_entity_id, supersedes_id) REFERENCES kpi_custom "
             "(legal_entity_id, id)",
             "ALTER TABLE kpi_custom DROP CONSTRAINT kpi_custom_supersedes_same_entity"),
        _sql(GUARDS, REVERSE),
    ]  # fmt: skip
