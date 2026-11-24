"""Currency integrity of the ledger (M6F-1, #80).

- ISO 4217 guards on account, entry, transaction-currency and exchange-rate columns.
- An entry is recorded in its entity's functional currency.
- A line may carry transaction-currency fields only when the entity has multi-currency enabled,
  which the database refuses in this release (``tenancy_entity_multi_currency_off``): so every
  line is in the functional currency until the full treatment (translation, revaluation, FX gains
  and losses, rounding) is implemented and tested.
- Exchange rates are tenant-owned, isolated and append-only.
"""

from django.db import migrations

from fcp.core.db.operations import tenant_isolation

SQL = """
CREATE TRIGGER ledger_account_currency
    BEFORE INSERT OR UPDATE OF currency ON ledger_account
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('currency', 'blank');
CREATE TRIGGER ledger_entry_currency
    BEFORE INSERT OR UPDATE OF currency ON ledger_journal_entry
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('currency');
CREATE TRIGGER ledger_line_txn_currency
    BEFORE INSERT OR UPDATE OF txn_currency ON ledger_journal_line
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('txn_currency');
CREATE TRIGGER ledger_exchange_rate_base
    BEFORE INSERT ON ledger_exchange_rate
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('base_currency');
CREATE TRIGGER ledger_exchange_rate_quote
    BEFORE INSERT ON ledger_exchange_rate
    FOR EACH ROW EXECUTE FUNCTION core_currency_guard('quote_currency');

CREATE OR REPLACE FUNCTION ledger_exchange_rate_kept() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'exchange rates are never changed or deleted; record a new one'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER ledger_exchange_rate_kept
    BEFORE UPDATE OR DELETE ON ledger_exchange_rate
    FOR EACH ROW EXECUTE FUNCTION ledger_exchange_rate_kept();

CREATE OR REPLACE FUNCTION ledger_entry_functional_currency() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    functional text;
BEGIN
    SELECT functional_currency INTO functional FROM tenancy_legal_entity
     WHERE id = NEW.legal_entity_id;
    IF NEW.currency IS DISTINCT FROM functional THEN
        RAISE EXCEPTION 'an entry is recorded in its entity''s functional currency (%)', functional
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ledger_entry_functional_currency
    BEFORE INSERT OR UPDATE OF currency, legal_entity_id ON ledger_journal_entry
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_functional_currency();

CREATE OR REPLACE FUNCTION ledger_line_multi_currency() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    enabled boolean;
BEGIN
    IF NEW.txn_currency IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT e.multi_currency_enabled INTO enabled
      FROM ledger_journal_entry j JOIN tenancy_legal_entity e ON e.id = j.legal_entity_id
     WHERE j.id = NEW.entry_id;
    IF enabled IS NOT TRUE THEN
        RAISE EXCEPTION 'multi-currency transactions are disabled for this entity'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER ledger_line_multi_currency
    BEFORE INSERT OR UPDATE ON ledger_journal_line
    FOR EACH ROW EXECUTE FUNCTION ledger_line_multi_currency();
"""
REVERSE = """
DROP TRIGGER IF EXISTS ledger_line_multi_currency ON ledger_journal_line;
DROP FUNCTION IF EXISTS ledger_line_multi_currency();
DROP TRIGGER IF EXISTS ledger_entry_functional_currency ON ledger_journal_entry;
DROP FUNCTION IF EXISTS ledger_entry_functional_currency();
DROP TRIGGER IF EXISTS ledger_exchange_rate_kept ON ledger_exchange_rate;
DROP FUNCTION IF EXISTS ledger_exchange_rate_kept();
DROP TRIGGER IF EXISTS ledger_exchange_rate_quote ON ledger_exchange_rate;
DROP TRIGGER IF EXISTS ledger_exchange_rate_base ON ledger_exchange_rate;
DROP TRIGGER IF EXISTS ledger_line_txn_currency ON ledger_journal_line;
DROP TRIGGER IF EXISTS ledger_entry_currency ON ledger_journal_entry;
DROP TRIGGER IF EXISTS ledger_account_currency ON ledger_account;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0002_currencies"),
        ("tenancy", "0008_currency_guards"),
        ("ledger", "0017_currency_foundation"),
    ]
    operations = [
        *tenant_isolation("ledger_exchange_rate"),
        migrations.RunSQL(SQL, REVERSE),
    ]
