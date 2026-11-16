"""Maintain, read and verify the ``reporting.actuals`` read model (M2-7, AC-M2-7).

Incremental refresh: entries posted after the tenant's watermark (``posting_seq``) are added to the
facts. ``posting_seq`` is assigned under a row lock held until the posting commits, so sequence
numbers become visible in order and the watermark never skips an entry. The state row is locked
during refresh, so concurrent refreshes serialise and never count an entry twice.

All statements run inside the caller's transaction with the tenant's row-level security context;
facts are therefore only ever computed from, and written for, that tenant.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db import connection
from django.utils import timezone

from .models import ActualsState, FactDaily, FactMonthly

ZERO = Decimal(0)

_UPSERT = """
INSERT INTO {table} (id, tenant_id, created_at, legal_entity_id, account_id, {key},
                     debit_total, credit_total)
SELECT gen_random_uuid(), e.tenant_id, now(), e.legal_entity_id, l.account_id, {expr},
       sum(l.debit), sum(l.credit)
  FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
 WHERE e.tenant_id = %s AND e.status = 'POSTED' AND e.posting_seq > %s AND e.posting_seq <= %s
 GROUP BY e.tenant_id, e.legal_entity_id, l.account_id, {expr}
ON CONFLICT (legal_entity_id, account_id, {key}) DO UPDATE
   SET debit_total = {table}.debit_total + EXCLUDED.debit_total,
       credit_total = {table}.credit_total + EXCLUDED.credit_total
"""
_UPSERTS = (
    _UPSERT.format(
        table="reporting_fact_monthly",
        key="month",
        expr="date_trunc('month', e.accounting_date)::date",
    ),
    _UPSERT.format(table="reporting_fact_daily", key="day", expr="e.accounting_date"),
)


def _state(tenant_id: UUID) -> ActualsState:
    ActualsState.objects.bulk_create(
        [ActualsState(tenant_id=tenant_id)], ignore_conflicts=True
    )  # race-safe first use
    state: ActualsState = ActualsState.objects.select_for_update().get(tenant_id=tenant_id)
    return state


def refresh(tenant_id: UUID) -> int:
    """Bring the facts up to date; returns the watermark now included."""
    state = _state(tenant_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT max(posting_seq) FROM ledger_journal_entry "
            "WHERE tenant_id = %s AND status = 'POSTED' AND posting_seq > %s",
            [tenant_id, state.watermark],
        )
        row = cursor.fetchone()
        latest = row[0] if row else None
        if latest is None:
            return state.watermark
        for statement in _UPSERTS:
            cursor.execute(statement, [tenant_id, state.watermark, latest])
    state.watermark = latest
    state.refreshed_at = timezone.now()
    state.save(update_fields=["watermark", "refreshed_at"])
    return state.watermark


def rebuild(tenant_id: UUID) -> int:
    """Discard and recompute every fact of the tenant from the ledger (deterministic)."""
    state = _state(tenant_id)
    FactMonthly.objects.filter(tenant_id=tenant_id).delete()
    FactDaily.objects.filter(tenant_id=tenant_id).delete()
    state.watermark = 0
    state.rebuilt_at = timezone.now()
    state.save(update_fields=["watermark", "rebuilt_at"])
    return refresh(tenant_id)


# --- reading --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fact:
    account_id: UUID
    period: date  # month start (monthly) or day (daily)
    debit_total: Decimal
    credit_total: Decimal

    @property
    def net_debit(self) -> Decimal:
        return self.debit_total - self.credit_total


@dataclass(frozen=True)
class Actuals:
    watermark: int
    facts: list[Fact] = field(default_factory=list)


def monthly(entity_id: UUID, tenant_id: UUID, *, date_from: date, date_to: date) -> Actuals:
    watermark = refresh(tenant_id)
    rows = FactMonthly.objects.filter(
        legal_entity_id=entity_id,
        month__gte=date_from.replace(day=1),
        month__lte=date_to.replace(day=1),
    ).order_by("month", "account_id")
    return Actuals(watermark, [Fact(r.account_id, r.month, r.debit_total, r.credit_total)
                               for r in rows])  # fmt: skip


def daily(entity_id: UUID, tenant_id: UUID, *, account_ids: list[UUID], date_from: date,
          date_to: date) -> Actuals:  # fmt: skip
    watermark = refresh(tenant_id)
    rows = FactDaily.objects.filter(
        legal_entity_id=entity_id, account_id__in=account_ids, day__gte=date_from, day__lte=date_to
    ).order_by("day", "account_id")
    return Actuals(watermark, [Fact(r.account_id, r.day, r.debit_total, r.credit_total)
                               for r in rows])  # fmt: skip


def net_before(
    entity_id: UUID, tenant_id: UUID, *, before: date
) -> tuple[int, dict[UUID, Decimal]]:
    """Net debit balance per account from all postings dated before ``before`` (openings)."""
    watermark = refresh(tenant_id)
    totals: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    for r in FactDaily.objects.filter(legal_entity_id=entity_id, day__lt=before):
        totals[r.account_id] += r.debit_total - r.credit_total
    return watermark, dict(totals)


# --- verification ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Drift:
    grain: str  # "monthly" | "daily"
    entity_id: UUID
    account_id: UUID
    period: date
    ledger: tuple[Decimal, Decimal]
    facts: tuple[Decimal, Decimal]


_COMPARE = """
WITH ledger AS (
    SELECT e.legal_entity_id AS entity, l.account_id AS account, {expr} AS period,
           sum(l.debit) AS d, sum(l.credit) AS c
      FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
     WHERE e.tenant_id = %s AND e.status = 'POSTED' AND e.posting_seq <= %s
     GROUP BY 1, 2, 3
), facts AS (
    SELECT legal_entity_id AS entity, account_id AS account, {key} AS period,
           debit_total AS d, credit_total AS c
      FROM {table} WHERE tenant_id = %s
)
SELECT coalesce(l.entity, f.entity), coalesce(l.account, f.account), coalesce(l.period, f.period),
       coalesce(l.d, 0), coalesce(l.c, 0), coalesce(f.d, 0), coalesce(f.c, 0)
  FROM ledger l FULL OUTER JOIN facts f
    ON f.entity = l.entity AND f.account = l.account AND f.period = l.period
 WHERE coalesce(l.d, 0) <> coalesce(f.d, 0) OR coalesce(l.c, 0) <> coalesce(f.c, 0)
 ORDER BY 3, 2
"""
_COMPARES = (
    (
        "monthly",
        _COMPARE.format(
            table="reporting_fact_monthly",
            key="month",
            expr="date_trunc('month', e.accounting_date)::date",
        ),
    ),
    ("daily", _COMPARE.format(table="reporting_fact_daily", key="day", expr="e.accounting_date")),
)


def verify(tenant_id: UUID) -> tuple[int, list[Drift]]:
    """Refresh, then compare every fact with the ledger up to the watermark (AC-M2-7)."""
    watermark = refresh(tenant_id)
    drifts: list[Drift] = []
    with connection.cursor() as cursor:
        for grain, statement in _COMPARES:
            cursor.execute(statement, [tenant_id, watermark, tenant_id])
            drifts += [Drift(grain, r[0], r[1], r[2], (r[3], r[4]), (r[5], r[6]))
                       for r in cursor.fetchall()]  # fmt: skip
    return watermark, drifts
