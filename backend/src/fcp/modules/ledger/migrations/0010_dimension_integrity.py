"""Isolation and database-enforced rules for analytical dimensions (M2-1, AC-M2-1).

- Every dimension table is tenant-isolated with FORCE row-level security and composite tenant FKs.
- A value belongs to its dimension's legal entity; a line tag's value belongs to the tagged
  dimension (composite FKs), so a tag can never point at another entity's or dimension's value.
- Tags of posted lines are immutable, like the lines themselves.
- At posting (deferred constraint trigger, so it sees the whole transaction): every line carries
  each dimension its account REQUIRES, none that it BLOCKS, only active values, and only
  dimensions of the entry's own legal entity. Reversals are exempt from the rules and status
  checks (they mirror a posted entry), not from the entity check. This holds even if the
  application is bypassed.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

STRUCTURE = [
    "ALTER TABLE ledger_dimension ADD CONSTRAINT ledger_dimension_entity_id_key "
    "UNIQUE (legal_entity_id, id)",
    "ALTER TABLE ledger_dimension_value ADD CONSTRAINT ledger_dimension_value_same_entity "
    "FOREIGN KEY (legal_entity_id, dimension_id) REFERENCES ledger_dimension (legal_entity_id, id)",
    "ALTER TABLE ledger_dimension_value ADD CONSTRAINT ledger_dimension_value_dim_id_key "
    "UNIQUE (dimension_id, id)",
    "ALTER TABLE ledger_dimension_value ADD CONSTRAINT ledger_dimension_value_parent_same_dim "
    "FOREIGN KEY (dimension_id, parent_id) REFERENCES ledger_dimension_value (dimension_id, id)",
    "ALTER TABLE ledger_line_dimension ADD CONSTRAINT ledger_line_dimension_value_of_dimension "
    "FOREIGN KEY (dimension_id, value_id) REFERENCES ledger_dimension_value (dimension_id, id)",
]

STRUCTURE_REVERSE = [
    "ALTER TABLE ledger_line_dimension DROP CONSTRAINT ledger_line_dimension_value_of_dimension",
    "ALTER TABLE ledger_dimension_value DROP CONSTRAINT ledger_dimension_value_parent_same_dim",
    "ALTER TABLE ledger_dimension_value DROP CONSTRAINT ledger_dimension_value_dim_id_key",
    "ALTER TABLE ledger_dimension_value DROP CONSTRAINT ledger_dimension_value_same_entity",
    "ALTER TABLE ledger_dimension DROP CONSTRAINT ledger_dimension_entity_id_key",
]

TRIGGERS = r"""
CREATE OR REPLACE FUNCTION ledger_line_dimension_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
        WHERE e.status = 'POSTED'
          AND l.id IN (
              CASE WHEN TG_OP <> 'INSERT' THEN OLD.line_id END,
              CASE WHEN TG_OP <> 'DELETE' THEN NEW.line_id END)
    ) THEN
        RAISE EXCEPTION 'dimension tags of posted journal lines are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_line_dimension_guard
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_line_dimension
    FOR EACH ROW EXECUTE FUNCTION ledger_line_dimension_guard();

CREATE OR REPLACE FUNCTION ledger_entry_dimensions_valid() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF NEW.status <> 'POSTED' OR (TG_OP = 'UPDATE' AND OLD.status = 'POSTED') THEN
        RETURN NULL;
    END IF;
    -- Reversals mirror a posted entry exactly (checked by the application, including tags), so
    -- account rules and value status, which may have changed since, do not apply to them.
    IF NEW.entry_type <> 'REVERSAL' AND EXISTS (
        SELECT 1 FROM ledger_journal_line l
          JOIN ledger_account_dimension_rule r ON r.account_id = l.account_id AND r.rule = 'REQUIRED'
         WHERE l.entry_id = NEW.id
           AND NOT EXISTS (SELECT 1 FROM ledger_line_dimension t
                            WHERE t.line_id = l.id AND t.dimension_id = r.dimension_id)
    ) THEN
        RAISE EXCEPTION 'posted entry % lacks a dimension required by an account', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    -- A BLOCKED dimension present, an inactive value or dimension, or another entity's dimension.
    IF EXISTS (
        SELECT 1 FROM ledger_journal_line l
          JOIN ledger_line_dimension t ON t.line_id = l.id
          JOIN ledger_dimension d ON d.id = t.dimension_id
          JOIN ledger_dimension_value v ON v.id = t.value_id
          LEFT JOIN ledger_account_dimension_rule r
                 ON r.account_id = l.account_id AND r.dimension_id = t.dimension_id
         WHERE l.entry_id = NEW.id
           AND (d.legal_entity_id <> NEW.legal_entity_id
                OR (NEW.entry_type <> 'REVERSAL'
                    AND (r.rule = 'BLOCKED' OR d.status <> 'ACTIVE' OR v.status <> 'ACTIVE')))
    ) THEN
        RAISE EXCEPTION 'posted entry % has a blocked, inactive or foreign dimension tag', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entry_dimensions_valid
    AFTER INSERT OR UPDATE ON ledger_journal_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_dimensions_valid();
"""

TRIGGERS_REVERSE = """
DROP TRIGGER IF EXISTS ledger_entry_dimensions_valid ON ledger_journal_entry;
DROP TRIGGER IF EXISTS ledger_line_dimension_guard ON ledger_line_dimension;
DROP FUNCTION IF EXISTS ledger_entry_dimensions_valid();
DROP FUNCTION IF EXISTS ledger_line_dimension_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0009_dimensions")]

    operations = [
        *tenant_isolation("ledger_dimension"),
        *tenant_isolation("ledger_dimension_value"),
        *tenant_isolation("ledger_account_dimension_rule"),
        *tenant_isolation("ledger_line_dimension"),
        composite_tenant_fk("ledger_dimension", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_dimension_value", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_dimension_value", "dimension_id", "ledger_dimension"),
        composite_tenant_fk("ledger_account_dimension_rule", "account_id", "ledger_account"),
        composite_tenant_fk("ledger_account_dimension_rule", "dimension_id", "ledger_dimension"),
        composite_tenant_fk("ledger_line_dimension", "line_id", "ledger_journal_line"),
        composite_tenant_fk("ledger_line_dimension", "dimension_id", "ledger_dimension"),
        composite_tenant_fk("ledger_line_dimension", "value_id", "ledger_dimension_value"),
        migrations.RunSQL(STRUCTURE, reverse_sql=STRUCTURE_REVERSE),
        migrations.RunSQL(TRIGGERS, reverse_sql=TRIGGERS_REVERSE),
    ]
