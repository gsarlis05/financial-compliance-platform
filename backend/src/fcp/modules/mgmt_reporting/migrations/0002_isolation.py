"""Isolation and history for report packs (M8-1), enforced by the database (AC-MR2, AC-MR3).

- FORCE row-level security and composite tenant keys (the entity, the superseded version).
- A pack starts as a draft: the first version of its family, or the next version of a final pack
  of the same family, entity and period. Its entity, family, version, period, origin and preparer
  never change. Nothing is deleted.
- A draft changes freely and can be submitted. A pack in review is frozen: it can only be returned
  to draft or finalised, by a reviewer who is not its preparer. A final pack never changes, except
  that it becomes superseded (once) when a newer version is finalised. A superseded pack never
  changes.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION mgmt_reporting_pack_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    fixed CONSTANT text[] := ARRAY['id', 'tenant_id', 'created_at', 'legal_entity_id',
        'family_id', 'version', 'supersedes_id', 'period_kind', 'period_start', 'period_end',
        'created_by_id'];
    frozen CONSTANT text[] := ARRAY['title', 'sections', 'columns', 'snapshot',
        'snapshot_hash', 'watermark', 'generated_at', 'generated_by_id'];
    prior mgmt_reporting_pack%ROWTYPE;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'report packs are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'DRAFT' OR NEW.submitted_at IS NOT NULL OR NEW.reviewed_by_id IS NOT NULL
           OR NEW.finalised_at IS NOT NULL OR NEW.superseded_at IS NOT NULL THEN
            RAISE EXCEPTION 'a report pack starts as a draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.supersedes_id IS NULL THEN
            IF NEW.version <> 1 THEN
                RAISE EXCEPTION 'the first version of a report pack is version 1'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END IF;
        SELECT * INTO prior FROM mgmt_reporting_pack WHERE id = NEW.supersedes_id;
        IF prior.status IS DISTINCT FROM 'FINAL' OR prior.family_id <> NEW.family_id
           OR prior.legal_entity_id <> NEW.legal_entity_id OR prior.version + 1 <> NEW.version
           OR prior.period_kind <> NEW.period_kind OR prior.period_start <> NEW.period_start
           OR prior.period_end <> NEW.period_end THEN
            RAISE EXCEPTION 'a new version follows the final version of the same pack'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF (SELECT jsonb_object_agg(k, to_jsonb(NEW) -> k) FROM unnest(fixed) k)
       IS DISTINCT FROM (SELECT jsonb_object_agg(k, to_jsonb(OLD) -> k) FROM unnest(fixed) k) THEN
        RAISE EXCEPTION 'the entity, period, version and preparer of a report pack never change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'DRAFT' THEN
        IF NEW.status = 'DRAFT' AND NEW.submitted_at IS NULL AND NEW.reviewed_by_id IS NULL
           AND NEW.finalised_at IS NULL AND NEW.superseded_at IS NULL THEN
            RETURN NEW;  -- editing or regenerating a draft
        END IF;
        IF NEW.status = 'IN_REVIEW' AND NEW.submitted_at IS NOT NULL
           AND NEW.reviewed_by_id IS NULL AND NEW.finalised_at IS NULL THEN
            RETURN NEW;
        END IF;
    ELSIF OLD.status = 'IN_REVIEW' THEN
        IF (SELECT jsonb_object_agg(k, to_jsonb(NEW) -> k) FROM unnest(frozen) k)
           IS DISTINCT FROM (SELECT jsonb_object_agg(k, to_jsonb(OLD) -> k) FROM unnest(frozen) k)
        THEN
            RAISE EXCEPTION 'a report pack in review cannot be edited; return it to draft first'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.status = 'DRAFT' AND NEW.submitted_at IS NULL AND NEW.finalised_at IS NULL THEN
            RETURN NEW;  -- returned to the preparer
        END IF;
        IF NEW.status = 'FINAL' AND NEW.finalised_at IS NOT NULL
           AND NEW.reviewed_by_id IS NOT NULL THEN
            IF NEW.reviewed_by_id = NEW.created_by_id THEN
                RAISE EXCEPTION 'the reviewer of a report pack cannot be its preparer'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END IF;
    ELSIF OLD.status = 'FINAL' THEN
        IF NEW.status = 'SUPERSEDED' AND NEW.superseded_at IS NOT NULL
           AND (to_jsonb(NEW) - ARRAY['status', 'superseded_at'])
               = (to_jsonb(OLD) - ARRAY['status', 'superseded_at']) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'a final report pack never changes; start a new version instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RAISE EXCEPTION 'this change of a report pack is not allowed (% to %)', OLD.status, NEW.status
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER mgmt_reporting_pack_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mgmt_reporting_pack
    FOR EACH ROW EXECUTE FUNCTION mgmt_reporting_pack_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS mgmt_reporting_pack_guard ON mgmt_reporting_pack;
DROP FUNCTION IF EXISTS mgmt_reporting_pack_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("mgmt_reporting", "0001_initial"),
    ]

    operations = [
        *tenant_isolation("mgmt_reporting_pack"),
        composite_tenant_fk("mgmt_reporting_pack", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("mgmt_reporting_pack", "supersedes_id", "mgmt_reporting_pack"),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
