"""Isolation and database-enforced rules for allocations and open-item flags (AC-M2-2).

An allocation row is accepted only if, at the moment of insertion:
- both lines belong to POSTED entries of the allocation's legal entity;
- both are on the same control account and carry the same counterparty;
- the debit line has a debit and the credit line a credit;
- the total allocated against each line, including this row, does not exceed the line amount.
The two lines are locked (FOR UPDATE) so concurrent allocations serialise. ``allocated_on`` is set
here to the later accounting date. Allocations are never updated (delete and re-create instead).
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TRIGGER = r"""
CREATE OR REPLACE FUNCTION registers_allocation_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    d record;
    c record;
    used_d numeric;
    used_c numeric;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'allocations are not updated; delete and create a new one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT l.id, l.account_id, l.counterparty_id, l.debit, l.credit, e.status, e.legal_entity_id,
           e.accounting_date, a.control_type
      INTO d
      FROM ledger_journal_line l
      JOIN ledger_journal_entry e ON e.id = l.entry_id
      JOIN ledger_account a ON a.id = l.account_id
     WHERE l.id = NEW.debit_line_id
       FOR UPDATE OF l;
    SELECT l.id, l.account_id, l.counterparty_id, l.debit, l.credit, e.status, e.legal_entity_id,
           e.accounting_date
      INTO c
      FROM ledger_journal_line l
      JOIN ledger_journal_entry e ON e.id = l.entry_id
     WHERE l.id = NEW.credit_line_id
       FOR UPDATE OF l;
    IF d.id IS NULL OR c.id IS NULL OR d.status <> 'POSTED' OR c.status <> 'POSTED' THEN
        RAISE EXCEPTION 'allocations need two posted lines'
            USING ERRCODE = 'check_violation';
    END IF;
    IF d.legal_entity_id <> NEW.legal_entity_id OR c.legal_entity_id <> NEW.legal_entity_id
       OR d.account_id <> c.account_id OR d.control_type = ''
       OR d.counterparty_id IS NULL OR d.counterparty_id IS DISTINCT FROM c.counterparty_id THEN
        RAISE EXCEPTION 'allocated lines must share a control account and counterparty'
            USING ERRCODE = 'check_violation';
    END IF;
    IF d.debit <= 0 OR c.credit <= 0 THEN
        RAISE EXCEPTION 'allocate a credit line against a debit line'
            USING ERRCODE = 'check_violation';
    END IF;
    SELECT coalesce(sum(amount), 0) INTO used_d FROM registers_allocation
     WHERE debit_line_id = NEW.debit_line_id;
    SELECT coalesce(sum(amount), 0) INTO used_c FROM registers_allocation
     WHERE credit_line_id = NEW.credit_line_id;
    IF used_d + NEW.amount > d.debit OR used_c + NEW.amount > c.credit THEN
        RAISE EXCEPTION 'allocation exceeds the open amount of a line'
            USING ERRCODE = 'check_violation';
    END IF;
    NEW.allocated_on := greatest(d.accounting_date, c.accounting_date);
    RETURN NEW;
END;
$$;

CREATE TRIGGER registers_allocation_guard
    BEFORE INSERT OR UPDATE ON registers_allocation
    FOR EACH ROW EXECUTE FUNCTION registers_allocation_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS registers_allocation_guard ON registers_allocation;
DROP FUNCTION IF EXISTS registers_allocation_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("registers", "0003_allocations")]

    operations = [
        *tenant_isolation("registers_allocation"),
        *tenant_isolation("registers_open_item_flag"),
        composite_tenant_fk("registers_allocation", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("registers_allocation", "debit_line_id", "ledger_journal_line"),
        composite_tenant_fk("registers_allocation", "credit_line_id", "ledger_journal_line"),
        composite_tenant_fk("registers_open_item_flag", "line_id", "ledger_journal_line"),
        migrations.RunSQL(TRIGGER, reverse_sql=REVERSE),
    ]
