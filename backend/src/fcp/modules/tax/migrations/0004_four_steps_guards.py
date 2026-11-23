"""The rules of the four steps, adjustments and inclusions (V1-2d, #215), enforced by the database.

**Reports:**
- A report starts as a draft: version 1, or the next version of a finalised or filed report of
  the same entity and period. Its entity, period, version and preparer never change, and nothing
  is deleted.
- A draft changes freely (it is regenerated). It carries no review, finalisation or filing.
- **Reviewing** freezes the figures: the snapshot never changes again.
  - The reviewer is not the preparer, unless the report is marked self-approved in a one-person
    workspace.
  - A report with an adjustment still proposed cannot be reviewed.
- A reviewed report goes back to draft only with a note saying why. Its review is then cleared.
- **Finalising** follows review. The finaliser is not the preparer, unless self-approved.
- A finalised report can only be recorded as filed, with the portal's reference, or superseded.
  A filed report can only be superseded, and a superseded report never changes.
- The due date, and the settlement entry (once), may be recorded after review.

**Adjustments:**
- An adjustment is added to a draft only. It starts as proposed.
- It is decided once, while its report is a draft: approved or rejected.
- It never changes after that and is never deleted.

**Inclusions:**
- A line's inclusion is recorded when its report is finalised.
- An inclusion is turned inactive only when its report is superseded.
- A line is in at most one active return (a unique index); inclusions are never deleted.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION tax_vat_report_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    fixed CONSTANT text[] := ARRAY['id', 'tenant_id', 'created_at', 'legal_entity_id',
        'period_start', 'period_end', 'version', 'supersedes_id', 'created_by_id'];
    frozen CONSTANT text[] := ARRAY['snapshot', 'snapshot_hash', 'watermark', 'generated_at'];
    review CONSTANT text[] := ARRAY['status', 'reviewed_by_id', 'reviewed_at', 'self_approved',
        'review_note'];
    filing CONSTANT text[] := ARRAY['status', 'filed_by_id', 'filed_on', 'filing_reference',
        'filing_evidence'];
    prior tax_vat_report%ROWTYPE;
    changed text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VAT reports are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'DRAFT' OR NEW.reviewed_by_id IS NOT NULL
           OR NEW.finalised_by_id IS NOT NULL OR NEW.self_approved OR NEW.filed_on IS NOT NULL
           OR NEW.superseded_at IS NOT NULL OR NEW.settlement_entry_id IS NOT NULL THEN
            RAISE EXCEPTION 'a VAT report starts as a draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.supersedes_id IS NULL THEN
            IF NEW.version <> 1 THEN
                RAISE EXCEPTION 'the first version of a VAT report is version 1'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END IF;
        SELECT * INTO prior FROM tax_vat_report WHERE id = NEW.supersedes_id;
        IF prior.status NOT IN ('FINALISED', 'FILED') OR prior.legal_entity_id <> NEW.legal_entity_id
           OR prior.period_start <> NEW.period_start OR prior.period_end <> NEW.period_end
           OR prior.version + 1 <> NEW.version THEN
            RAISE EXCEPTION 'a new version follows a finalised report of the same period'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    SELECT coalesce(array_agg(n.key), '{}') INTO changed
      FROM jsonb_each(to_jsonb(NEW)) n JOIN jsonb_each(to_jsonb(OLD)) o USING (key)
     WHERE n.value IS DISTINCT FROM o.value;
    IF changed && fixed THEN
        RAISE EXCEPTION 'the entity, period, version and preparer of a VAT report never change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'SUPERSEDED' THEN
        RAISE EXCEPTION 'a superseded VAT report never changes'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status <> 'DRAFT' AND changed && frozen THEN
        RAISE EXCEPTION 'the figures of a reviewed VAT report never change; send it back to draft '
            'or start a new version' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.status = 'DRAFT' AND NEW.status = 'DRAFT' THEN
        IF NEW.reviewed_by_id IS NULL AND NEW.finalised_by_id IS NULL AND NOT NEW.self_approved
           AND NEW.filed_on IS NULL AND NEW.settlement_entry_id IS NULL THEN
            RETURN NEW;  -- regenerated, or its due date set
        END IF;
    ELSIF OLD.status = 'DRAFT' AND NEW.status = 'REVIEWED' THEN
        IF changed <@ review AND NEW.reviewed_by_id IS NOT NULL AND NEW.reviewed_at IS NOT NULL THEN
            IF NEW.reviewed_by_id = NEW.created_by_id
               AND NOT (NEW.self_approved AND tenancy_one_person(NEW.tenant_id)) THEN
                RAISE EXCEPTION 'the reviewer of a VAT report cannot be its preparer'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            IF EXISTS (SELECT 1 FROM tax_vat_adjustment a
                        WHERE a.report_id = NEW.id AND a.status = 'PROPOSED') THEN
                RAISE EXCEPTION 'approve or reject every proposed adjustment before the review'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END IF;
    ELSIF OLD.status = 'REVIEWED' AND NEW.status = 'DRAFT' THEN
        IF changed <@ review AND NEW.reviewed_by_id IS NULL AND NEW.reviewed_at IS NULL
           AND NOT NEW.self_approved AND NEW.review_note <> '' THEN
            RETURN NEW;  -- sent back to draft, with the reason
        END IF;
    ELSIF OLD.status = 'REVIEWED' AND NEW.status = 'FINALISED' THEN
        IF changed <@ ARRAY['status', 'finalised_by_id', 'finalised_at', 'self_approved']
           AND NEW.finalised_by_id IS NOT NULL AND NEW.finalised_at IS NOT NULL
           AND (NEW.self_approved OR NOT OLD.self_approved) THEN
            IF NEW.finalised_by_id = NEW.created_by_id
               AND NOT (NEW.self_approved AND tenancy_one_person(NEW.tenant_id)) THEN
                RAISE EXCEPTION 'the person who finalises a VAT report cannot be its preparer'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END IF;
    ELSIF OLD.status = NEW.status THEN
        IF changed <@ ARRAY['due_date', 'settlement_entry_id']
           AND (OLD.settlement_entry_id IS NULL
                OR NEW.settlement_entry_id IS NOT DISTINCT FROM OLD.settlement_entry_id)
           AND (NEW.settlement_entry_id IS NULL OR NEW.status IN ('FINALISED', 'FILED')) THEN
            RETURN NEW;
        END IF;
    ELSIF OLD.status = 'FINALISED' AND NEW.status = 'FILED' THEN
        IF changed <@ filing AND NEW.filed_on IS NOT NULL AND NEW.filing_reference <> '' THEN
            RETURN NEW;
        END IF;
    ELSIF OLD.status IN ('FINALISED', 'FILED') AND NEW.status = 'SUPERSEDED' THEN
        IF changed <@ ARRAY['status', 'superseded_at'] AND NEW.superseded_at IS NOT NULL THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION 'this change of a VAT report is not allowed (% to %, changed: %)',
        OLD.status, NEW.status, changed USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER tax_vat_report_guard BEFORE INSERT OR UPDATE OR DELETE ON tax_vat_report
    FOR EACH ROW EXECUTE FUNCTION tax_vat_report_guard();

CREATE OR REPLACE FUNCTION tax_vat_adjustment_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    report_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VAT adjustments are kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT status INTO report_status FROM tax_vat_report WHERE id = NEW.report_id;
    IF report_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'adjustments are added and decided while the VAT report is a draft'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'PROPOSED' OR NEW.decided_by_id IS NOT NULL OR NEW.self_approved THEN
            RAISE EXCEPTION 'an adjustment starts as proposed'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.status <> 'PROPOSED' OR NEW.status = 'PROPOSED'
       OR (NEW.id, NEW.tenant_id, NEW.created_at, NEW.report_id, NEW.box, NEW.amount, NEW.reason,
           NEW.evidence, NEW.created_by_id)
          IS DISTINCT FROM
          (OLD.id, OLD.tenant_id, OLD.created_at, OLD.report_id, OLD.box, OLD.amount, OLD.reason,
           OLD.evidence, OLD.created_by_id) THEN
        RAISE EXCEPTION 'an adjustment is decided once and never changes'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tax_vat_adjustment_guard BEFORE INSERT OR UPDATE OR DELETE ON tax_vat_adjustment
    FOR EACH ROW EXECUTE FUNCTION tax_vat_adjustment_guard();
CREATE TRIGGER tax_vat_adjustment_self_approval
    BEFORE INSERT OR UPDATE OF self_approved ON tax_vat_adjustment
    FOR EACH ROW EXECUTE FUNCTION tenancy_self_approval_guard();

CREATE OR REPLACE FUNCTION tax_vat_inclusion_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    report_status text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'the inclusion of a line in a return is kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT status INTO report_status FROM tax_vat_report WHERE id = NEW.report_id;
    IF TG_OP = 'INSERT' THEN
        IF report_status <> 'FINALISED' OR NOT NEW.active THEN
            RAISE EXCEPTION 'a line is included in a return when the return is finalised'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF NOT (OLD.active AND NOT NEW.active AND report_status = 'SUPERSEDED')
       OR (NEW.id, NEW.tenant_id, NEW.created_at, NEW.report_id, NEW.line_id, NEW.entry_id)
          IS DISTINCT FROM
          (OLD.id, OLD.tenant_id, OLD.created_at, OLD.report_id, OLD.line_id, OLD.entry_id) THEN
        RAISE EXCEPTION 'an inclusion only ends when its return is superseded'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tax_vat_inclusion_guard BEFORE INSERT OR UPDATE OR DELETE ON tax_vat_inclusion
    FOR EACH ROW EXECUTE FUNCTION tax_vat_inclusion_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tax_vat_inclusion_guard ON tax_vat_inclusion;
DROP FUNCTION IF EXISTS tax_vat_inclusion_guard();
DROP TRIGGER IF EXISTS tax_vat_adjustment_self_approval ON tax_vat_adjustment;
DROP TRIGGER IF EXISTS tax_vat_adjustment_guard ON tax_vat_adjustment;
DROP FUNCTION IF EXISTS tax_vat_adjustment_guard();
DROP TRIGGER IF EXISTS tax_vat_report_guard ON tax_vat_report;
"""


class Migration(migrations.Migration):
    dependencies = [("tax", "0003_four_steps")]

    operations = [
        *tenant_isolation("tax_vat_adjustment"),
        *tenant_isolation("tax_vat_inclusion"),
        composite_tenant_fk("tax_vat_adjustment", "report_id", "tax_vat_report"),
        composite_tenant_fk("tax_vat_inclusion", "report_id", "tax_vat_report"),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
