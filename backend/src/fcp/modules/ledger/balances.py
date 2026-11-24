"""Account balances maintained at posting time (doc 05 §7)."""

from django.db import connection

from .models import JournalEntry


def apply_posting(entry: JournalEntry) -> None:
    """Add a posted entry's lines to the per-period account balances (same transaction)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ledger_account_balance
                (id, tenant_id, created_at, legal_entity_id, account_id, period_id,
                 debit_total, credit_total)
            SELECT gen_random_uuid(), l.tenant_id, now(), %(entity)s, l.account_id, %(period)s,
                   sum(l.debit), sum(l.credit)
            FROM ledger_journal_line l
            WHERE l.entry_id = %(entry)s
            GROUP BY l.tenant_id, l.account_id
            ON CONFLICT (account_id, period_id) DO UPDATE
               SET debit_total = ledger_account_balance.debit_total + EXCLUDED.debit_total,
                   credit_total = ledger_account_balance.credit_total + EXCLUDED.credit_total
            """,
            {"entity": entry.legal_entity_id, "period": entry.period_id, "entry": entry.id},
        )
