"""Isolation and history for VAT periods and VAT reports (V1-2), enforced by the database.

- FORCE row-level security and composite tenant keys.
- A VAT period scheme is never changed or deleted: a change of periods is a new scheme.
- A report starts as a draft: version 1, or the next version of a signed-off or filed report of the
  same entity and period. Its entity, period, version and preparer never change; nothing is
  deleted.
- A draft changes freely (regenerated) but carries no sign-off or filing. Signing off freezes its
  figures: the snapshot never changes again. The person who signs off is not the preparer, unless
  the report is marked self-approved in a one-person workspace. A signed-off report can only be
  recorded as filed or superseded; a filed report only superseded; a superseded report never
  changes. The due date and the settlement entry (once) may be recorded after sign-off.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION tax_vat_scheme_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'a VAT period scheme never changes; add a new one from a later date'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER tax_vat_scheme_guard BEFORE UPDATE OR DELETE ON tax_vat_period_scheme
    FOR EACH ROW EXECUTE FUNCTION tax_vat_scheme_guard();

CREATE OR REPLACE FUNCTION tax_vat_report_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    fixed CONSTANT text[] := ARRAY['id', 'tenant_id', 'created_at', 'legal_entity_id',
        'period_start', 'period_end', 'version', 'supersedes_id', 'created_by_id'];
    frozen CONSTANT text[] := ARRAY['snapshot', 'snapshot_hash', 'watermark', 'generated_at',
        'signed_off_by_id', 'signed_off_at', 'self_approved'];
    filing CONSTANT text[] := ARRAY['filed_by_id', 'filed_on', 'filing_reference'];
    prior tax_vat_report%ROWTYPE;
    changed text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VAT reports are kept' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'DRAFT' OR NEW.signed_off_by_id IS NOT NULL OR NEW.self_approved
           OR NEW.filed_on IS NOT NULL OR NEW.superseded_at IS NOT NULL
           OR NEW.settlement_entry_id IS NOT NULL THEN
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
        IF prior.status NOT IN ('SIGNED_OFF', 'FILED') OR prior.legal_entity_id <> NEW.legal_entity_id
           OR prior.period_start <> NEW.period_start OR prior.period_end <> NEW.period_end
           OR prior.version + 1 <> NEW.version THEN
            RAISE EXCEPTION 'a new version follows a signed-off report of the same period'
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
    IF OLD.status = 'DRAFT' AND NEW.status = 'DRAFT' THEN
        IF NEW.signed_off_by_id IS NULL AND NOT NEW.self_approved AND NEW.filed_on IS NULL
           AND NEW.settlement_entry_id IS NULL THEN
            RETURN NEW;  -- regenerated, or its due date set
        END IF;
    ELSIF OLD.status = 'DRAFT' AND NEW.status = 'SIGNED_OFF' THEN
        IF changed <@ ARRAY['status', 'signed_off_by_id', 'signed_off_at', 'self_approved']
           AND NEW.signed_off_by_id IS NOT NULL THEN
            IF NEW.signed_off_by_id = NEW.created_by_id
               AND NOT (NEW.self_approved AND tenancy_one_person(NEW.tenant_id)) THEN
                RAISE EXCEPTION 'the person who signs off a VAT report cannot be its preparer'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END IF;
    ELSIF OLD.status = 'SUPERSEDED' THEN
        RAISE EXCEPTION 'a superseded VAT report never changes'
            USING ERRCODE = 'integrity_constraint_violation';
    ELSIF changed && frozen THEN
        RAISE EXCEPTION 'a signed-off VAT report never changes; start a new version'
            USING ERRCODE = 'integrity_constraint_violation';
    ELSIF OLD.status = NEW.status THEN
        IF changed <@ ARRAY['due_date', 'settlement_entry_id']
           AND (OLD.settlement_entry_id IS NULL
                OR NEW.settlement_entry_id IS NOT DISTINCT FROM OLD.settlement_entry_id) THEN
            RETURN NEW;
        END IF;
    ELSIF OLD.status = 'SIGNED_OFF' AND NEW.status = 'FILED' THEN
        IF changed <@ (ARRAY['status'] || filing) THEN
            RETURN NEW;
        END IF;
    ELSIF NEW.status = 'SUPERSEDED' THEN
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
CREATE TRIGGER tax_vat_report_self_approval
    BEFORE INSERT OR UPDATE OF self_approved ON tax_vat_report
    FOR EACH ROW EXECUTE FUNCTION tenancy_self_approval_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tax_vat_report_self_approval ON tax_vat_report;
DROP TRIGGER IF EXISTS tax_vat_report_guard ON tax_vat_report;
DROP FUNCTION IF EXISTS tax_vat_report_guard();
DROP TRIGGER IF EXISTS tax_vat_scheme_guard ON tax_vat_period_scheme;
DROP FUNCTION IF EXISTS tax_vat_scheme_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0009_one_person"),
        ("tax", "0001_initial"),
    ]

    operations = [
        *tenant_isolation("tax_vat_period_scheme"),
        *tenant_isolation("tax_vat_report"),
        composite_tenant_fk("tax_vat_period_scheme", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("tax_vat_report", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("tax_vat_report", "supersedes_id", "tax_vat_report"),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
