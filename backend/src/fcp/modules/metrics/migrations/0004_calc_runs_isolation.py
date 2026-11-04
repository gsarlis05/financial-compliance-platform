"""Isolation and immutability of calculation runs (M3-2, doc 10 P4/P5, doc 12 "Immutability").

- FORCE row-level security and composite tenant keys on runs, results and lineage.
- A run is inserted RUNNING (then finished in the same transaction) or FAILED. While RUNNING, only
  its outcome can be set (status, output hash, invariants, error, finish time). A finished run
  can only become stale, and a valid run published, each once and never back.
- No run is still RUNNING at commit (deferred check), so results are written in one go.
- Results and lineage are inserted only while their run is RUNNING, and never changed after that.
- Nothing is ever deleted.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION metrics_run_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    outcome text[] := ARRAY['status', 'output_hash', 'invariant_results', 'error', 'finished_at'];
    flags text[] := ARRAY['stale', 'is_published'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'calculation runs are kept; they cannot be deleted'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status NOT IN ('RUNNING', 'FAILED') OR NEW.stale OR NEW.is_published THEN
            RAISE EXCEPTION 'a calculation run starts RUNNING (or is recorded FAILED)'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status = 'RUNNING' THEN
        IF NEW.status = 'RUNNING'
           OR (to_jsonb(NEW) - outcome) IS DISTINCT FROM (to_jsonb(OLD) - outcome) THEN
            RAISE EXCEPTION 'a running calculation can only be finished'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - flags) IS DISTINCT FROM (to_jsonb(OLD) - flags)
       OR (OLD.stale AND NOT NEW.stale)
       OR (OLD.is_published AND NOT NEW.is_published) THEN
        RAISE EXCEPTION 'a finished calculation run is immutable (it can only become stale or '
                        'published)'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER metrics_run_guard
    BEFORE INSERT OR UPDATE OR DELETE ON metrics_calc_run
    FOR EACH ROW EXECUTE FUNCTION metrics_run_guard();

CREATE OR REPLACE FUNCTION metrics_run_finished() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF EXISTS (SELECT 1 FROM metrics_calc_run WHERE id = NEW.id AND status = 'RUNNING') THEN
        RAISE EXCEPTION 'a calculation run must be finished in the transaction that started it'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER metrics_run_finished
    AFTER INSERT ON metrics_calc_run
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION metrics_run_finished();

CREATE OR REPLACE FUNCTION metrics_result_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    run_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'calculation results are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_TABLE_NAME = 'metrics_calc_result' THEN
        SELECT status INTO run_status FROM metrics_calc_run WHERE id = NEW.run_id;
    ELSE
        SELECT r.status INTO run_status
          FROM metrics_calc_result c JOIN metrics_calc_run r ON r.id = c.run_id
         WHERE c.id = NEW.result_id;
    END IF;
    IF run_status IS DISTINCT FROM 'RUNNING' THEN
        RAISE EXCEPTION 'results are written only while their calculation run is running'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER metrics_result_guard
    BEFORE INSERT OR UPDATE OR DELETE ON metrics_calc_result
    FOR EACH ROW EXECUTE FUNCTION metrics_result_guard();

CREATE TRIGGER metrics_lineage_guard
    BEFORE INSERT OR UPDATE OR DELETE ON metrics_calc_lineage
    FOR EACH ROW EXECUTE FUNCTION metrics_result_guard();
"""

GUARDS_REVERSE = """
DROP TRIGGER IF EXISTS metrics_lineage_guard ON metrics_calc_lineage;
DROP TRIGGER IF EXISTS metrics_result_guard ON metrics_calc_result;
DROP FUNCTION IF EXISTS metrics_result_guard();
DROP TRIGGER IF EXISTS metrics_run_finished ON metrics_calc_run;
DROP FUNCTION IF EXISTS metrics_run_finished();
DROP TRIGGER IF EXISTS metrics_run_guard ON metrics_calc_run;
DROP FUNCTION IF EXISTS metrics_run_guard();
"""

TABLES = ("metrics_calc_run", "metrics_calc_result", "metrics_calc_lineage")


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("metrics", "0003_calc_runs"),
    ]

    operations = [
        *[op for table in TABLES for op in tenant_isolation(table)],
        composite_tenant_fk("metrics_calc_run", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("metrics_calc_run", "supersedes_id", "metrics_calc_run"),
        composite_tenant_fk("metrics_calc_result", "run_id", "metrics_calc_run"),
        composite_tenant_fk("metrics_calc_lineage", "result_id", "metrics_calc_result"),
        migrations.RunSQL(GUARDS, reverse_sql=GUARDS_REVERSE),
    ]
