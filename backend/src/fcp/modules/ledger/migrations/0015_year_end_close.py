"""Year-end close (M2-9): closed fiscal years refuse postings; closing entries are derived.

- The posting guard refuses any posting into a CLOSED fiscal year, except the reversal of that
  year's closing entry (which re-opens it).
- Closing entries mirror posted balances per account and dimension tags, so, like reversals, they
  are exempt from account dimension rules (the application checks them line by line).
- At most one live (posted, not reversed) closing entry per fiscal year.
"""

from django.db import migrations

GUARD = r"""
CREATE OR REPLACE FUNCTION ledger_entry_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    p record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'POSTED' THEN
            RAISE EXCEPTION 'posted journal entries are immutable (delete rejected)'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status = 'POSTED' THEN
        IF OLD.reversed_by_entry_id IS NOT NULL
           OR (to_jsonb(NEW) - 'reversed_by_entry_id') IS DISTINCT FROM
              (to_jsonb(OLD) - 'reversed_by_entry_id') THEN
            RAISE EXCEPTION 'posted journal entries are immutable (update rejected)'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status = 'POSTED' THEN
        SELECT status, start_date, end_date, legal_entity_id, fiscal_year_id INTO p
          FROM ledger_period WHERE id = NEW.period_id;
        IF NOT FOUND OR p.legal_entity_id <> NEW.legal_entity_id THEN
            RAISE EXCEPTION 'posting period not found for this entity'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.accounting_date < p.start_date OR NEW.accounting_date > p.end_date THEN
            RAISE EXCEPTION 'accounting date % is outside the posting period', NEW.accounting_date
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF p.status = 'LOCKED' AND NOT EXISTS (
            SELECT 1 FROM ledger_period_unlock u
             WHERE u.id = NEW.unlock_request_id
               AND u.period_id = NEW.period_id
               AND u.status = 'ACTIVE'
               -- clock_timestamp(): the actual time, not the transaction start (now()).
               AND clock_timestamp() BETWEEN u.active_from AND u.active_until
        ) THEN
            RAISE EXCEPTION 'cannot post into a locked period without an active unlock'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        -- A closed fiscal year takes no postings, except the reversal of its closing entry,
        -- which re-opens the year (doc 05 §5; M2-9).
        IF EXISTS (SELECT 1 FROM ledger_fiscal_year y
                    WHERE y.id = p.fiscal_year_id AND y.status = 'CLOSED')
           AND NOT (NEW.entry_type = 'REVERSAL' AND EXISTS (
                    SELECT 1 FROM ledger_journal_entry o
                     WHERE o.id = NEW.reverses_entry_id AND o.entry_type = 'CLOSING'
                       AND o.fiscal_year_id = p.fiscal_year_id)) THEN
            RAISE EXCEPTION 'cannot post into a closed fiscal year; re-open it first'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF p.status = 'SOFT_CLOSED' AND NOT NEW.posted_in_soft_closed THEN
            RAISE EXCEPTION 'cannot post into a soft-closed period without the privilege'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

DIMENSIONS = r"""
CREATE OR REPLACE FUNCTION ledger_entry_dimensions_valid() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF NEW.status <> 'POSTED' OR (TG_OP = 'UPDATE' AND OLD.status = 'POSTED') THEN
        RETURN NULL;
    END IF;
    -- Reversals mirror a posted entry, and closing entries mirror posted balances, exactly
    -- (checked by the application, including tags), so account rules and value status, which
    -- may have changed since, do not apply to them.
    IF NEW.entry_type NOT IN ('REVERSAL', 'CLOSING') AND EXISTS (
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
                OR (NEW.entry_type NOT IN ('REVERSAL', 'CLOSING')
                    AND (r.rule = 'BLOCKED' OR d.status <> 'ACTIVE' OR v.status <> 'ACTIVE')))
    ) THEN
        RAISE EXCEPTION 'posted entry % has a blocked, inactive or foreign dimension tag', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;
"""

# Previous definitions (0006, 0010), restored when this migration is reversed.
GUARD_PREVIOUS = r"""
CREATE OR REPLACE FUNCTION ledger_entry_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    p record;
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.status = 'POSTED' THEN
            RAISE EXCEPTION 'posted journal entries are immutable (delete rejected)'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN OLD;
    END IF;

    IF TG_OP = 'UPDATE' AND OLD.status = 'POSTED' THEN
        IF OLD.reversed_by_entry_id IS NOT NULL
           OR (to_jsonb(NEW) - 'reversed_by_entry_id') IS DISTINCT FROM
              (to_jsonb(OLD) - 'reversed_by_entry_id') THEN
            RAISE EXCEPTION 'posted journal entries are immutable (update rejected)'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.status = 'POSTED' THEN
        SELECT status, start_date, end_date, legal_entity_id INTO p
          FROM ledger_period WHERE id = NEW.period_id;
        IF NOT FOUND OR p.legal_entity_id <> NEW.legal_entity_id THEN
            RAISE EXCEPTION 'posting period not found for this entity'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF NEW.accounting_date < p.start_date OR NEW.accounting_date > p.end_date THEN
            RAISE EXCEPTION 'accounting date % is outside the posting period', NEW.accounting_date
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF p.status = 'LOCKED' AND NOT EXISTS (
            SELECT 1 FROM ledger_period_unlock u
             WHERE u.id = NEW.unlock_request_id
               AND u.period_id = NEW.period_id
               AND u.status = 'ACTIVE'
               -- clock_timestamp(): the actual time, not the transaction start (now()).
               AND clock_timestamp() BETWEEN u.active_from AND u.active_until
        ) THEN
            RAISE EXCEPTION 'cannot post into a locked period without an active unlock'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        IF p.status = 'SOFT_CLOSED' AND NOT NEW.posted_in_soft_closed THEN
            RAISE EXCEPTION 'cannot post into a soft-closed period without the privilege'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

DIMENSIONS_PREVIOUS = r"""
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
"""

ONE_CLOSING = """
CREATE UNIQUE INDEX ledger_entry_one_live_closing ON ledger_journal_entry (fiscal_year_id)
 WHERE entry_type = 'CLOSING' AND status = 'POSTED' AND reversed_by_entry_id IS NULL;
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0014_vat_seed_and_rules")]

    operations = [
        migrations.RunSQL(GUARD, reverse_sql=GUARD_PREVIOUS),
        migrations.RunSQL(DIMENSIONS, reverse_sql=DIMENSIONS_PREVIOUS),
        migrations.RunSQL(ONE_CLOSING, reverse_sql="DROP INDEX ledger_entry_one_live_closing;"),
    ]
