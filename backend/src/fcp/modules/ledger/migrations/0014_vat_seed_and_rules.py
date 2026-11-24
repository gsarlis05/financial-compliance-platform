"""Seed the VAT code catalogue and enforce VAT rules at posting (M2-3, AC-M2-3).

Seeding is idempotent (update_or_create by id), so re-running or extending the JSON file in a later
migration updates the catalogue without touching posted lines (which reference ids).

At posting (deferred constraint trigger): every line on a VAT control account carries a VAT code;
every VAT code used is valid on the entry's accounting date and belongs to the entity's
jurisdiction. Reversals mirror their original exactly, so the date-validity check uses the original
entry's date for them (a code that has since expired may still be reversed).
"""

from typing import Any

from django.db import migrations

from fcp.modules.ledger.vat import seed_catalogue


def seed(apps: Any, schema_editor: Any) -> None:
    del schema_editor
    seed_catalogue(apps.get_model("ledger", "VatCode"))


TRIGGER = r"""
CREATE OR REPLACE FUNCTION ledger_entry_vat_valid() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    check_date date;
BEGIN
    IF NEW.status <> 'POSTED' OR (TG_OP = 'UPDATE' AND OLD.status = 'POSTED') THEN
        RETURN NULL;
    END IF;
    check_date := NEW.accounting_date;
    IF NEW.entry_type = 'REVERSAL' AND NEW.reverses_entry_id IS NOT NULL THEN
        SELECT accounting_date INTO check_date FROM ledger_journal_entry
         WHERE id = NEW.reverses_entry_id;
    END IF;
    IF EXISTS (
        SELECT 1 FROM ledger_journal_line l JOIN ledger_account a ON a.id = l.account_id
         WHERE l.entry_id = NEW.id AND a.vat_role <> '' AND l.vat_code_id IS NULL
    ) THEN
        RAISE EXCEPTION 'posted entry % has a VAT-account line without a VAT code', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ledger_journal_line l
          JOIN ledger_vat_code v ON v.id = l.vat_code_id
          JOIN tenancy_legal_entity le ON le.id = NEW.legal_entity_id
         WHERE l.entry_id = NEW.id
           AND (v.jurisdiction <> le.jurisdiction
                OR (v.valid_from IS NOT NULL AND check_date < v.valid_from)
                OR (v.valid_to IS NOT NULL AND check_date > v.valid_to))
    ) THEN
        RAISE EXCEPTION 'posted entry % uses a VAT code not valid for its date or jurisdiction',
            NEW.id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entry_vat_valid
    AFTER INSERT OR UPDATE ON ledger_journal_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_vat_valid();
"""

REVERSE = """
DROP TRIGGER IF EXISTS ledger_entry_vat_valid ON ledger_journal_entry;
DROP FUNCTION IF EXISTS ledger_entry_vat_valid();
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0013_vat_codes")]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        migrations.RunSQL(TRIGGER, reverse_sql=REVERSE),
    ]
