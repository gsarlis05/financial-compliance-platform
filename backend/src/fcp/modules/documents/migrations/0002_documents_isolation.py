"""Isolation and integrity for the document vault (M2-4).

- FORCE row-level security and composite tenant keys.
- Documents are immutable and cannot be deleted (evidence; retention is a platform job).
- A link targets an entry, or a posted line, of the document's own legal entity.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION documents_document_immutable() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'documents are immutable evidence and cannot be changed or deleted'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER documents_document_immutable
    BEFORE UPDATE OR DELETE ON documents_document
    FOR EACH ROW EXECUTE FUNCTION documents_document_immutable();

CREATE OR REPLACE FUNCTION documents_link_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    doc_entity uuid;
    target_entity uuid;
BEGIN
    SELECT legal_entity_id INTO doc_entity FROM documents_document WHERE id = NEW.document_id;
    IF NEW.entry_id IS NOT NULL THEN
        SELECT legal_entity_id INTO target_entity FROM ledger_journal_entry WHERE id = NEW.entry_id;
    ELSE
        SELECT e.legal_entity_id INTO target_entity
          FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
         WHERE l.id = NEW.line_id AND e.status = 'POSTED';
    END IF;
    IF target_entity IS NULL OR target_entity <> doc_entity THEN
        RAISE EXCEPTION 'a document links only to an entry or posted line of its own legal entity'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER documents_link_guard
    BEFORE INSERT OR UPDATE ON documents_link
    FOR EACH ROW EXECUTE FUNCTION documents_link_guard();
"""

GUARDS_REVERSE = """
DROP TRIGGER IF EXISTS documents_link_guard ON documents_link;
DROP FUNCTION IF EXISTS documents_link_guard();
DROP TRIGGER IF EXISTS documents_document_immutable ON documents_document;
DROP FUNCTION IF EXISTS documents_document_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("ledger", "0015_year_end_close"),
        ("documents", "0001_document_vault"),
    ]

    operations = [
        *tenant_isolation("documents_document"),
        *tenant_isolation("documents_link"),
        composite_tenant_fk("documents_document", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("documents_link", "document_id", "documents_document"),
        composite_tenant_fk("documents_link", "entry_id", "ledger_journal_entry"),
        composite_tenant_fk("documents_link", "line_id", "ledger_journal_line"),
        migrations.RunSQL(GUARDS, reverse_sql=GUARDS_REVERSE),
    ]
