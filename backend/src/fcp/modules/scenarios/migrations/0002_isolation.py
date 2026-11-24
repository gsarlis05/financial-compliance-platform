"""Isolation and history for scenarios (M7-1), enforced by the database.

- FORCE row-level security and composite tenant keys (the entity, the base set, the copied
  scenario, and each override's scenario).
- A scenario starts as a draft on an approved (or since superseded) assumption set of the same
  entity. Its entity, base, author and origin never change. While a draft, only its name and
  description change; it can then be shared (once) or archived; a shared scenario can only be
  archived. Nothing is deleted.
- Overrides can be added, changed, reordered or removed only while their scenario is a draft.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION scenarios_scenario_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    editable CONSTANT text[] := ARRAY['name', 'description', 'status', 'shared_at',
                                      'archived_at'];
    base_status text;
    base_entity uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'scenarios are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        SELECT status, legal_entity_id INTO base_status, base_entity
          FROM projections_assumption_set WHERE id = NEW.base_set_id;
        IF base_status IS NULL OR base_status = 'DRAFT' THEN
            RAISE EXCEPTION 'a scenario is based on an approved assumption set'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF base_entity <> NEW.legal_entity_id THEN
            RAISE EXCEPTION 'a scenario and its base belong to the same legal entity'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.status <> 'DRAFT' OR NEW.shared_at IS NOT NULL OR NEW.archived_at IS NOT NULL THEN
            RAISE EXCEPTION 'a scenario starts as a draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (to_jsonb(NEW) - editable) IS DISTINCT FROM (to_jsonb(OLD) - editable) THEN
        RAISE EXCEPTION 'the entity, base, author and origin of a scenario never change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'DRAFT'
       AND NEW.shared_at IS NULL AND NEW.archived_at IS NULL THEN
        RETURN NEW;  -- renaming or describing a draft
    END IF;
    IF NEW.name IS DISTINCT FROM OLD.name OR NEW.description IS DISTINCT FROM OLD.description THEN
        RAISE EXCEPTION 'only a draft scenario can be renamed; copy it to change it'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'SHARED'
       AND NEW.shared_at IS NOT NULL AND NEW.archived_at IS NULL THEN
        RETURN NEW;
    END IF;
    IF OLD.status IN ('DRAFT', 'SHARED') AND NEW.status = 'ARCHIVED'
       AND NEW.archived_at IS NOT NULL AND NEW.shared_at IS NOT DISTINCT FROM OLD.shared_at THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'a shared or archived scenario never changes; copy it to change it'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER scenarios_scenario_guard
    BEFORE INSERT OR UPDATE OR DELETE ON scenarios_scenario
    FOR EACH ROW EXECUTE FUNCTION scenarios_scenario_guard();

CREATE OR REPLACE FUNCTION scenarios_override_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    scenario_status text;
BEGIN
    SELECT status INTO scenario_status FROM scenarios_scenario
     WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.scenario_id ELSE NEW.scenario_id END;
    IF TG_OP = 'UPDATE' AND NEW.scenario_id <> OLD.scenario_id THEN
        RAISE EXCEPTION 'an override cannot move to another scenario'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF scenario_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'overrides can change only while the scenario is a draft'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER scenarios_override_guard
    BEFORE INSERT OR UPDATE OR DELETE ON scenarios_override
    FOR EACH ROW EXECUTE FUNCTION scenarios_override_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS scenarios_override_guard ON scenarios_override;
DROP FUNCTION IF EXISTS scenarios_override_guard();
DROP TRIGGER IF EXISTS scenarios_scenario_guard ON scenarios_scenario;
DROP FUNCTION IF EXISTS scenarios_scenario_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("projections", "0002_isolation"),
        ("scenarios", "0001_initial"),
    ]

    operations = [
        *tenant_isolation("scenarios_scenario"),
        *tenant_isolation("scenarios_override"),
        composite_tenant_fk("scenarios_scenario", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("scenarios_scenario", "base_set_id", "projections_assumption_set"),
        composite_tenant_fk("scenarios_scenario", "copied_from_id", "scenarios_scenario"),
        composite_tenant_fk("scenarios_override", "scenario_id", "scenarios_scenario"),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
