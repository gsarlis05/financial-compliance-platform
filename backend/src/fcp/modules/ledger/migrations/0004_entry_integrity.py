"""Tenant isolation and database-enforced ledger invariants (doc 05 §1-3, doc 09 AC-C2).

These triggers hold even if application code is bypassed (e.g. direct SQL as the app role):
- a POSTED entry and its lines can never change or be deleted (only ``reversed_by_entry_id``
  may be set once);
- an entry can only become POSTED into an existing period of its entity, on a date inside that
  period, not into a LOCKED period (unless an unlock applies, M1-9) and not into a SOFT_CLOSED
  period unless the application recorded the privilege;
- at commit, a POSTED entry has >= 2 lines, debits equal credits, and only postable, active
  accounts of its own entity.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, enable_rls, tenant_isolation

GUARDS = r"""
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
        IF p.status = 'LOCKED' AND NEW.unlock_request_id IS NULL THEN
            RAISE EXCEPTION 'cannot post into a locked period'
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

CREATE TRIGGER ledger_entry_guard
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_journal_entry
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_guard();

CREATE OR REPLACE FUNCTION ledger_line_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ledger_journal_entry e
        WHERE e.status = 'POSTED'
          AND e.id IN (
              CASE WHEN TG_OP <> 'INSERT' THEN OLD.entry_id END,
              CASE WHEN TG_OP <> 'DELETE' THEN NEW.entry_id END)
    ) THEN
        RAISE EXCEPTION 'lines of posted journal entries are immutable'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER ledger_line_guard
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_journal_line
    FOR EACH ROW EXECUTE FUNCTION ledger_line_guard();

CREATE OR REPLACE FUNCTION ledger_entry_balanced() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    total_debit numeric;
    total_credit numeric;
    line_count integer;
    bad_accounts integer;
BEGIN
    IF NEW.status <> 'POSTED' OR (TG_OP = 'UPDATE' AND OLD.status = 'POSTED') THEN
        RETURN NULL;
    END IF;
    SELECT coalesce(sum(debit), 0), coalesce(sum(credit), 0), count(*)
      INTO total_debit, total_credit, line_count
      FROM ledger_journal_line WHERE entry_id = NEW.id;
    IF line_count < 2 THEN
        RAISE EXCEPTION 'posted entry % needs at least two lines', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF total_debit <> total_credit THEN
        RAISE EXCEPTION 'posted entry % is unbalanced: debits % credits %',
            NEW.id, total_debit, total_credit USING ERRCODE = 'check_violation';
    END IF;
    SELECT count(*) INTO bad_accounts
      FROM ledger_journal_line l JOIN ledger_account a ON a.id = l.account_id
     WHERE l.entry_id = NEW.id
       AND (NOT a.is_postable OR a.status <> 'ACTIVE' OR a.legal_entity_id <> NEW.legal_entity_id);
    IF bad_accounts > 0 THEN
        RAISE EXCEPTION 'posted entry % uses accounts that are headings, inactive or of another entity',
            NEW.id USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END;
$$;

CREATE CONSTRAINT TRIGGER ledger_entry_balanced
    AFTER INSERT OR UPDATE ON ledger_journal_entry
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_entry_balanced();
"""

REVERSE = """
DROP TRIGGER IF EXISTS ledger_entry_balanced ON ledger_journal_entry;
DROP TRIGGER IF EXISTS ledger_line_guard ON ledger_journal_line;
DROP TRIGGER IF EXISTS ledger_entry_guard ON ledger_journal_entry;
DROP FUNCTION IF EXISTS ledger_entry_balanced();
DROP FUNCTION IF EXISTS ledger_line_guard();
DROP FUNCTION IF EXISTS ledger_entry_guard();
"""

SAME_ENTITY = [
    "ALTER TABLE ledger_journal ADD CONSTRAINT ledger_journal_entity_id_key UNIQUE (legal_entity_id, id)",
    "ALTER TABLE ledger_period ADD CONSTRAINT ledger_period_entity_id_key UNIQUE (legal_entity_id, id)",
    "ALTER TABLE ledger_journal_entry ADD CONSTRAINT ledger_entry_journal_same_entity "
    "FOREIGN KEY (legal_entity_id, journal_id) REFERENCES ledger_journal (legal_entity_id, id)",
    "ALTER TABLE ledger_journal_entry ADD CONSTRAINT ledger_entry_period_same_entity "
    "FOREIGN KEY (legal_entity_id, period_id) REFERENCES ledger_period (legal_entity_id, id)",
    "ALTER TABLE ledger_account_balance ADD CONSTRAINT ledger_balance_account_same_entity "
    "FOREIGN KEY (legal_entity_id, account_id) REFERENCES ledger_account (legal_entity_id, id)",
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0003_postingcounter_journal_entrysequence_journalentry_and_more")]

    operations = [
        *tenant_isolation("ledger_settings"),
        *tenant_isolation("ledger_journal"),
        *tenant_isolation("ledger_journal_entry"),
        *tenant_isolation("ledger_journal_line"),
        *tenant_isolation("ledger_entry_sequence"),
        *tenant_isolation("ledger_idempotency"),
        *tenant_isolation("ledger_account_balance"),
        enable_rls("ledger_posting_counter", "tenant_id = app_current_tenant()"),
        composite_tenant_fk("ledger_settings", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_journal", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_journal_entry", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_journal_entry", "journal_id", "ledger_journal"),
        composite_tenant_fk("ledger_journal_entry", "period_id", "ledger_period"),
        composite_tenant_fk("ledger_journal_entry", "fiscal_year_id", "ledger_fiscal_year"),
        composite_tenant_fk("ledger_journal_entry", "reverses_entry_id", "ledger_journal_entry"),
        composite_tenant_fk("ledger_journal_entry", "reversed_by_entry_id", "ledger_journal_entry"),
        composite_tenant_fk("ledger_journal_entry", "related_entry_id", "ledger_journal_entry"),
        composite_tenant_fk("ledger_journal_line", "entry_id", "ledger_journal_entry"),
        composite_tenant_fk("ledger_journal_line", "account_id", "ledger_account"),
        composite_tenant_fk("ledger_entry_sequence", "journal_id", "ledger_journal"),
        composite_tenant_fk("ledger_entry_sequence", "fiscal_year_id", "ledger_fiscal_year"),
        composite_tenant_fk("ledger_account_balance", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_account_balance", "account_id", "ledger_account"),
        composite_tenant_fk("ledger_account_balance", "period_id", "ledger_period"),
        migrations.RunSQL(SAME_ENTITY, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(GUARDS, reverse_sql=REVERSE),
    ]
