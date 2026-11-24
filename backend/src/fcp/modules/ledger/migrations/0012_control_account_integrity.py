"""Database rules for control accounts (M2-2, doc 05 §3 "counterparty required on control accounts").

At posting (deferred constraint trigger): every line on a control account carries a counterparty,
and every counterparty on any line belongs to the entry's legal entity. Line columns, including the
counterparty, are already immutable once posted (ledger_line_guard, migration 0004).
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk

TRIGGER = r"""
CREATE OR REPLACE FUNCTION ledger_entry_subledger_valid() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF NEW.status <> 'POSTED' OR (TG_OP = 'UPDATE' AND OLD.status = 'POSTED') THEN
        RETURN NULL;
    END IF;
    IF EXISTS (
        SELECT 1 FROM ledger_journal_line l JOIN ledger_account a ON a.id = l.account_id
         WHERE l.entry_id = NEW.id AND a.control_type <> '' AND l.counterparty_id IS NULL
    ) THEN
        RAISE EXCEPTION 'posted entry % has a control-account line without a counterparty', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ledger_journal_line l JOIN registers_counterparty c ON c.id = l.counterparty_id
         WHERE l.entry_id = NEW.id AND c.legal_entity_id <> NEW.legal_entity_id
    ) THEN
        RAISE EXCEPTION 'posted entry % uses a counterparty of another entity', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entry_subledger_valid
    AFTER INSERT OR UPDATE ON ledger_journal_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_subledger_valid();
"""

REVERSE = """
DROP TRIGGER IF EXISTS ledger_entry_subledger_valid ON ledger_journal_entry;
DROP FUNCTION IF EXISTS ledger_entry_subledger_valid();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0011_control_accounts"),
        ("registers", "0002_counterparty_isolation"),
    ]

    operations = [
        composite_tenant_fk("ledger_journal_line", "counterparty_id", "registers_counterparty"),
        migrations.RunSQL(TRIGGER, reverse_sql=REVERSE),
    ]
