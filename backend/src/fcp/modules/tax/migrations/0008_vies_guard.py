"""VIES statements (V1-2g, #218), enforced by the database.

- FORCE row-level security and composite tenant keys.
- A statement is never edited or deleted; it is voided once, with a reason.
- Its lines are added only while it is active, and are never changed or deleted.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARD = r"""
CREATE OR REPLACE FUNCTION tax_vies_statement_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'VIES statements are kept; void a wrong one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.voided_at IS NOT NULL THEN
            RAISE EXCEPTION 'a VIES statement starts active'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.voided_at IS NOT NULL OR NEW.voided_at IS NULL
       OR (NEW.id, NEW.tenant_id, NEW.created_at, NEW.legal_entity_id, NEW.month, NEW.kind,
           NEW.filed_on, NEW.reference, NEW.note, NEW.created_by_id)
          IS DISTINCT FROM
          (OLD.id, OLD.tenant_id, OLD.created_at, OLD.legal_entity_id, OLD.month, OLD.kind,
           OLD.filed_on, OLD.reference, OLD.note, OLD.created_by_id) THEN
        RAISE EXCEPTION 'a VIES statement is never changed; void it and record it again'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tax_vies_statement_guard BEFORE INSERT OR UPDATE OR DELETE
    ON tax_vat_vies_statement FOR EACH ROW EXECUTE FUNCTION tax_vies_statement_guard();

CREATE OR REPLACE FUNCTION tax_vies_line_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'the lines of a VIES statement are never changed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM tax_vat_vies_statement s
                    WHERE s.id = NEW.statement_id AND s.voided_at IS NULL) THEN
        RAISE EXCEPTION 'lines are added to an active VIES statement'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tax_vies_line_guard BEFORE INSERT OR UPDATE OR DELETE ON tax_vat_vies_line
    FOR EACH ROW EXECUTE FUNCTION tax_vies_line_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tax_vies_line_guard ON tax_vat_vies_line;
DROP FUNCTION IF EXISTS tax_vies_line_guard();
DROP TRIGGER IF EXISTS tax_vies_statement_guard ON tax_vat_vies_statement;
DROP FUNCTION IF EXISTS tax_vies_statement_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("tax", "0007_vies")]

    operations = [
        *tenant_isolation("tax_vat_vies_statement"),
        *tenant_isolation("tax_vat_vies_line"),
        composite_tenant_fk("tax_vat_vies_statement", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("tax_vat_vies_line", "statement_id", "tax_vat_vies_statement"),
        migrations.RunSQL(GUARD, REVERSE),
    ]
