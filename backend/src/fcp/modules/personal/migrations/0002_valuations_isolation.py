"""Isolation and history for personal valuations (M5-1), enforced by the database.

- FORCE row-level security and composite tenant keys; a valuation is of an account of the same
  legal entity.
- A valuation is never deleted and never changes; a correction supersedes it, once.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARD = r"""
CREATE OR REPLACE FUNCTION personal_valuation_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'valuations are kept; enter a new value instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'valuations are immutable; a correction adds a new value'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER personal_valuation_guard BEFORE UPDATE OR DELETE ON personal_valuation
    FOR EACH ROW EXECUTE FUNCTION personal_valuation_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS personal_valuation_guard ON personal_valuation;
DROP FUNCTION IF EXISTS personal_valuation_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("ledger", "0016_dimension_value_entity_key"),
        ("personal", "0001_valuations"),
    ]

    operations = [
        *tenant_isolation("personal_valuation"),
        composite_tenant_fk("personal_valuation", "legal_entity_id", "tenancy_legal_entity"),
        migrations.RunSQL(
            "ALTER TABLE personal_valuation ADD CONSTRAINT personal_valuation_same_entity "
            "FOREIGN KEY (legal_entity_id, account_id) REFERENCES ledger_account "
            "(legal_entity_id, id)",
            "ALTER TABLE personal_valuation DROP CONSTRAINT personal_valuation_same_entity",
        ),
        migrations.RunSQL(GUARD, REVERSE),
    ]
