"""Isolation and history for goals (M4-6), enforced by the database.

- FORCE row-level security and composite tenant keys; versions and evaluations belong to their
  goal's legal entity, and baselines and evaluations name a calculation run of that entity.
- A goal's definition never changes; it can only be retired, once. Nothing is deleted.
- A goal version's content (target, baseline, ...) never changes; it can only be superseded, once
  (AC-GO1: the baseline stays frozen, a new target is a new version).
- Evaluation summaries are append-only (runtime grants, see the table registry).
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("goals_goal", "goals_version", "goals_evaluation")

GUARDS = r"""
CREATE OR REPLACE FUNCTION goals_goal_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'goals are kept; retire a goal instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status <> 'ACTIVE' OR NEW.status <> 'RETIRED'
       OR (to_jsonb(NEW) - ARRAY['status', 'retired_by_id', 'retired_at'])
          IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['status', 'retired_by_id', 'retired_at']) THEN
        RAISE EXCEPTION 'a goal can only be retired; a new target is a new version'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER goals_goal_guard BEFORE UPDATE OR DELETE ON goals_goal
    FOR EACH ROW EXECUTE FUNCTION goals_goal_guard();

CREATE OR REPLACE FUNCTION goals_version_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'goal versions are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'a goal version is immutable (its baseline is frozen); it can only be '
                        'superseded by a new version'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER goals_version_guard BEFORE UPDATE OR DELETE ON goals_version
    FOR EACH ROW EXECUTE FUNCTION goals_version_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS goals_version_guard ON goals_version;
DROP FUNCTION IF EXISTS goals_version_guard();
DROP TRIGGER IF EXISTS goals_goal_guard ON goals_goal;
DROP FUNCTION IF EXISTS goals_goal_guard();
"""


def _sql(sql: str, reverse: str) -> migrations.RunSQL:
    return migrations.RunSQL(sql, reverse_sql=reverse)


def _same_entity(table: str, column: str, target: str, name: str) -> migrations.RunSQL:
    return _sql(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (legal_entity_id, {column}) "
        f"REFERENCES {target} (legal_entity_id, id)",
        f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("metrics", "0005_calc_run_entity_key"),
        ("goals", "0001_goals"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity") for t in TABLES],
        _sql("ALTER TABLE goals_goal ADD CONSTRAINT goals_goal_entity_id_key "
             "UNIQUE (legal_entity_id, id)",
             "ALTER TABLE goals_goal DROP CONSTRAINT goals_goal_entity_id_key"),
        _sql("ALTER TABLE goals_version ADD CONSTRAINT goals_version_entity_id_key "
             "UNIQUE (legal_entity_id, id)",
             "ALTER TABLE goals_version DROP CONSTRAINT goals_version_entity_id_key"),
        _same_entity("goals_version", "goal_id", "goals_goal", "goals_version_same_entity"),
        _same_entity("goals_version", "baseline_run_id", "metrics_calc_run",
                     "goals_version_baseline_run"),
        _same_entity("goals_evaluation", "goal_id", "goals_goal", "goals_evaluation_same_entity"),
        _same_entity("goals_evaluation", "version_id", "goals_version",
                     "goals_evaluation_version_same_entity"),
        _same_entity("goals_evaluation", "run_id", "metrics_calc_run", "goals_evaluation_run"),
        _sql(GUARDS, REVERSE),
    ]  # fmt: skip
