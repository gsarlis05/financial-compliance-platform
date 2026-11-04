"""Isolation and integrity for banking (M2-5).

- FORCE row-level security and composite tenant keys on every table.
- A bank account's ledger account belongs to the same legal entity.
- A statement line can only be matched to a POSTED line on its bank's ledger account with the same
  signed amount (debit minus credit equals the statement amount).
- Reconciliations are append-only.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = (
    "banking_bank_account",
    "banking_statement_import",
    "banking_statement_line",
    "banking_reconciliation",
)

MATCH_GUARD = r"""
CREATE OR REPLACE FUNCTION banking_line_match_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    ok boolean;
BEGIN
    IF NEW.matched_line_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT (e.status = 'POSTED' AND l.account_id = b.ledger_account_id
            AND l.debit - l.credit = NEW.amount)
      INTO ok
      FROM ledger_journal_line l
      JOIN ledger_journal_entry e ON e.id = l.entry_id
      JOIN banking_bank_account b ON b.id = NEW.bank_account_id
     WHERE l.id = NEW.matched_line_id;
    IF ok IS NOT TRUE THEN
        RAISE EXCEPTION 'a statement line matches only a posted line of the same amount on its '
                        'bank''s ledger account'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER banking_line_match_guard
    BEFORE INSERT OR UPDATE OF matched_line_id, amount ON banking_statement_line
    FOR EACH ROW EXECUTE FUNCTION banking_line_match_guard();

CREATE OR REPLACE FUNCTION banking_reconciliation_append_only() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'reconciliations are append-only' USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER banking_reconciliation_append_only
    BEFORE UPDATE OR DELETE ON banking_reconciliation
    FOR EACH ROW EXECUTE FUNCTION banking_reconciliation_append_only();
"""

MATCH_GUARD_REVERSE = """
DROP TRIGGER IF EXISTS banking_reconciliation_append_only ON banking_reconciliation;
DROP FUNCTION IF EXISTS banking_reconciliation_append_only();
DROP TRIGGER IF EXISTS banking_line_match_guard ON banking_statement_line;
DROP FUNCTION IF EXISTS banking_line_match_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("ledger", "0015_year_end_close"),
        ("banking", "0001_bank_statements"),
    ]

    operations = [
        *[op for table in TABLES for op in tenant_isolation(table)],
        composite_tenant_fk("banking_bank_account", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("banking_bank_account", "ledger_account_id", "ledger_account"),
        migrations.RunSQL(
            "ALTER TABLE banking_bank_account ADD CONSTRAINT banking_bank_account_same_entity "
            "FOREIGN KEY (legal_entity_id, ledger_account_id) "
            "REFERENCES ledger_account (legal_entity_id, id)",
            reverse_sql="ALTER TABLE banking_bank_account "
            "DROP CONSTRAINT banking_bank_account_same_entity",
        ),
        composite_tenant_fk("banking_statement_import", "bank_account_id", "banking_bank_account"),
        composite_tenant_fk("banking_statement_line", "bank_account_id", "banking_bank_account"),
        composite_tenant_fk(
            "banking_statement_line", "statement_import_id", "banking_statement_import"
        ),
        composite_tenant_fk("banking_statement_line", "matched_line_id", "ledger_journal_line"),
        composite_tenant_fk("banking_reconciliation", "bank_account_id", "banking_bank_account"),
        migrations.RunSQL(MATCH_GUARD, reverse_sql=MATCH_GUARD_REVERSE),
    ]
