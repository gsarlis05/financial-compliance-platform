"""Import records (V1-2f, #217), enforced by the database.

- FORCE row-level security and composite tenant keys, to the entity and to the evidence document.
- A record is never edited or deleted.
- It is voided once, with a reason, and only while its entry is not in a finalised return.
- An active record per customs reference and per entry: the same import VAT is never claimed
  twice (unique indexes in 0005).
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARD = r"""
CREATE OR REPLACE FUNCTION tax_vat_import_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'import records are kept; void a wrong one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.voided_at IS NOT NULL THEN
            RAISE EXCEPTION 'an import record starts active'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.voided_at IS NOT NULL OR NEW.voided_at IS NULL
       OR (NEW.id, NEW.tenant_id, NEW.created_at, NEW.legal_entity_id, NEW.entry_id,
           NEW.customs_reference, NEW.customs_date, NEW.customs_value, NEW.import_vat,
           NEW.document_id, NEW.document_name, NEW.created_by_id)
          IS DISTINCT FROM
          (OLD.id, OLD.tenant_id, OLD.created_at, OLD.legal_entity_id, OLD.entry_id,
           OLD.customs_reference, OLD.customs_date, OLD.customs_value, OLD.import_vat,
           OLD.document_id, OLD.document_name, OLD.created_by_id) THEN
        RAISE EXCEPTION 'an import record is never changed; void it and record it again'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF EXISTS (SELECT 1 FROM tax_vat_inclusion i
                WHERE i.entry_id = OLD.entry_id AND i.active) THEN
        RAISE EXCEPTION 'this import is in a finalised return; start a new version to correct it'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tax_vat_import_guard BEFORE INSERT OR UPDATE OR DELETE ON tax_vat_import
    FOR EACH ROW EXECUTE FUNCTION tax_vat_import_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tax_vat_import_guard ON tax_vat_import;
DROP FUNCTION IF EXISTS tax_vat_import_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("tax", "0005_imports"), ("documents", "0002_documents_isolation")]

    operations = [
        *tenant_isolation("tax_vat_import"),
        composite_tenant_fk("tax_vat_import", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("tax_vat_import", "document_id", "documents_document"),
        migrations.RunSQL(GUARD, REVERSE),
    ]
