"""Isolation for period unlocks, and the posting guard's locked-period exception.

A posting into a LOCKED period is accepted only when the entry is tagged with an unlock of that
same period that is ACTIVE and inside its time window at the moment of posting.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

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
               AND now() BETWEEN u.active_from AND u.active_until
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


class Migration(migrations.Migration):
    dependencies = [("ledger", "0005_periodunlock")]

    operations = [
        *tenant_isolation("ledger_period_unlock"),
        composite_tenant_fk("ledger_period_unlock", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_period_unlock", "period_id", "ledger_period"),
        composite_tenant_fk("ledger_journal_entry", "unlock_request_id", "ledger_period_unlock"),
        migrations.RunSQL(GUARD, reverse_sql=migrations.RunSQL.noop),
    ]
