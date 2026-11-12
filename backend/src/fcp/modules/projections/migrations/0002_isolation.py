"""Isolation and history for assumption sets (M6-2), enforced by the database (doc 10 P5).

- FORCE row-level security and composite tenant keys.
- A set is never deleted. While it is a draft, only its name and note can change; it can then be
  approved (once), and an approved set can only be marked superseded (once).
- Values can be added, changed or removed only while their set is a draft.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("projections_assumption_set", "projections_assumption_value")

GUARDS = r"""
CREATE OR REPLACE FUNCTION projections_set_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    frozen CONSTANT text[] := ARRAY['name', 'note', 'status', 'approved_by_id', 'approved_at',
                                    'superseded_at'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'assumption sets are kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (to_jsonb(NEW) - frozen) IS DISTINCT FROM (to_jsonb(OLD) - frozen) THEN
        RAISE EXCEPTION 'the horizon and origin of an assumption set never change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'DRAFT'
       AND NEW.approved_by_id IS NULL AND NEW.approved_at IS NULL AND NEW.superseded_at IS NULL THEN
        RETURN NEW;  -- renaming a draft
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'APPROVED'
       AND NEW.name = OLD.name AND NEW.note = OLD.note AND NEW.superseded_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'APPROVED' AND NEW.status = 'SUPERSEDED' AND NEW.superseded_at IS NOT NULL
       AND NEW.name = OLD.name AND NEW.note = OLD.note
       AND NEW.approved_by_id = OLD.approved_by_id AND NEW.approved_at = OLD.approved_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'an approved assumption set never changes; revise it as a new version'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER projections_set_guard BEFORE UPDATE OR DELETE ON projections_assumption_set
    FOR EACH ROW EXECUTE FUNCTION projections_set_guard();

CREATE OR REPLACE FUNCTION projections_value_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    set_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        SELECT status INTO set_status FROM projections_assumption_set
         WHERE id = OLD.assumption_set_id;
    ELSE
        SELECT status INTO set_status FROM projections_assumption_set
         WHERE id = NEW.assumption_set_id;
        IF TG_OP = 'UPDATE' AND NEW.assumption_set_id <> OLD.assumption_set_id THEN
            RAISE EXCEPTION 'a value cannot move to another assumption set'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    IF set_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'values can change only while the assumption set is a draft'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER projections_value_guard
    BEFORE INSERT OR UPDATE OR DELETE ON projections_assumption_value
    FOR EACH ROW EXECUTE FUNCTION projections_value_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS projections_value_guard ON projections_assumption_value;
DROP FUNCTION IF EXISTS projections_value_guard();
DROP TRIGGER IF EXISTS projections_set_guard ON projections_assumption_set;
DROP FUNCTION IF EXISTS projections_set_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("projections", "0001_initial"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        composite_tenant_fk(
            "projections_assumption_set", "legal_entity_id", "tenancy_legal_entity"
        ),
        composite_tenant_fk(
            "projections_assumption_set", "supersedes_id", "projections_assumption_set"
        ),
        composite_tenant_fk(
            "projections_assumption_value", "assumption_set_id", "projections_assumption_set"
        ),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
