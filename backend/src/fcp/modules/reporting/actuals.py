"""Maintain, read and verify the ``reporting.actuals`` read model (M2-7, AC-M2-7).

Incremental refresh: entries posted after the tenant's watermark (``posting_seq``) are added to the
facts. ``posting_seq`` is assigned under a row lock held until the posting commits, so sequence
numbers become visible in order and the watermark never skips an entry. The state row is locked
during refresh, so concurrent refreshes serialise and never count an entry twice.

All statements run inside the caller's transaction with the tenant's row-level security context;
facts are therefore only ever computed from, and written for, that tenant.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from django.db import connection
from django.db.models import F, Q, Sum
from django.utils import timezone

from .models import ActualsState, FactDaily, FactMonthly

ZERO = Decimal(0)

# Year-end closing entries, and reversals of them (re-opening a year), are kept apart (M2-9).
_IS_CLOSING = """(e.entry_type = 'CLOSING' OR (e.entry_type = 'REVERSAL' AND EXISTS (
    SELECT 1 FROM ledger_journal_entry o
     WHERE o.id = e.reverses_entry_id AND o.entry_type = 'CLOSING')))"""

_UPSERT = """
INSERT INTO {table} (id, tenant_id, created_at, legal_entity_id, account_id, {key}, is_closing,
                     debit_total, credit_total)
SELECT gen_random_uuid(), e.tenant_id, now(), e.legal_entity_id, l.account_id, {expr},
       {closing}, sum(l.debit), sum(l.credit)
  FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
 WHERE e.tenant_id = %s AND e.status = 'POSTED' AND e.posting_seq > %s AND e.posting_seq <= %s
 GROUP BY e.tenant_id, e.legal_entity_id, l.account_id, {expr}, {closing}
ON CONFLICT (legal_entity_id, account_id, {key}, is_closing) DO UPDATE
   SET debit_total = {table}.debit_total + EXCLUDED.debit_total,
       credit_total = {table}.credit_total + EXCLUDED.credit_total
"""
_UPSERTS = (
    _UPSERT.format(
        table="reporting_fact_monthly",
        key="month",
        expr="date_trunc('month', e.accounting_date)::date",
        closing=_IS_CLOSING,
    ),
    _UPSERT.format(
        table="reporting_fact_daily", key="day", expr="e.accounting_date", closing=_IS_CLOSING
    ),
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


class WatermarkError(ValueError):
    """A pinned read asked for a watermark the read model has not reached (or a negative one)."""


Later = list[tuple[UUID, date, bool, Decimal, Decimal]]
_LATER_TEMPLATE = """
SELECT l.account_id, e.accounting_date, {closing}, sum(l.debit), sum(l.credit)
  FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
 WHERE e.tenant_id = %s AND e.legal_entity_id = %s AND e.status = 'POSTED'
   AND e.posting_seq > %s AND e.posting_seq <= %s
 GROUP BY 1, 2, 3
"""
_LATER = _LATER_TEMPLATE.format(closing=_IS_CLOSING)
Totals = dict[tuple[UUID, date], list[Decimal]]


def _pinned(entity_id: UUID, tenant_id: UUID, watermark: int | None) -> tuple[int, Later]:
    """The watermark to read at and the postings made after it, which a pinned read subtracts.

    Posted entries are immutable and their ``posting_seq`` only grows, so "the facts as of
    watermark W" are exactly the current facts minus the lines of entries posted after W (doc 10
    §2.3: a calculation run re-reads the same actuals later)."""
    latest = refresh(tenant_id)
    if watermark is None or watermark == latest:
        return latest, []
    if watermark < 0 or watermark > latest:
        raise WatermarkError(f"watermark {watermark} is outside 0..{latest}")
    with connection.cursor() as cursor:
        cursor.execute(_LATER, [tenant_id, entity_id, watermark, latest])
        return watermark, list(cursor.fetchall())


def _subtract(facts: Totals,
              later: Iterable[tuple[UUID, date, Decimal, Decimal]]) -> None:  # fmt: skip
    """Remove later postings from facts; a fact that only existed because of them disappears."""
    for account_id, period, debit, credit in later:
        key = (account_id, period)
        if key not in facts:
            continue
        totals = facts[key]
        totals[0] -= debit
        totals[1] -= credit
        if not totals[0] and not totals[1]:
            del facts[key]


def _facts(rows: Iterable[tuple[UUID, date, Decimal, Decimal]]) -> Totals:
    return {(a, p): [d, c] for a, p, d, c in rows}


def _as_facts(facts: Totals) -> list[Fact]:
    ordered = sorted(facts.items(), key=lambda kv: (kv[0][1], str(kv[0][0])))
    return [Fact(a, p, d, c) for (a, p), (d, c) in ordered]


def posted_since(entity_id: UUID, tenant_id: UUID, watermark: int) -> bool:
    """Whether the entity has posted entries after ``watermark`` (an entity-level change check:
    the watermark itself is per tenant)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM ledger_journal_entry WHERE tenant_id = %s "
            "AND legal_entity_id = %s AND status = 'POSTED' AND posting_seq > %s)",
            [tenant_id, entity_id, watermark],
        )
        row = cursor.fetchone()
    return bool(row and row[0])


def monthly(entity_id: UUID, tenant_id: UUID, *, date_from: date, date_to: date,
            watermark: int | None = None) -> Actuals:  # fmt: skip
    """Operating actuals per month: year-end closing entries are left out. With ``watermark``, the
    facts as they were at that watermark."""
    pinned, later = _pinned(entity_id, tenant_id, watermark)
    first, last = date_from.replace(day=1), date_to.replace(day=1)
    rows = FactMonthly.objects.filter(
        legal_entity_id=entity_id, is_closing=False, month__gte=first, month__lte=last
    )
    facts = _facts((r.account_id, r.month, r.debit_total, r.credit_total) for r in rows)
    _subtract(facts, ((a, d.replace(day=1), dr, cr) for a, d, closing, dr, cr in later
                      if not closing))  # fmt: skip
    return Actuals(pinned, _as_facts(facts))


def daily(entity_id: UUID, tenant_id: UUID, *, account_ids: list[UUID], date_from: date,
          date_to: date, watermark: int | None = None) -> Actuals:  # fmt: skip
    pinned, later = _pinned(entity_id, tenant_id, watermark)
    rows = FactDaily.objects.filter(
        legal_entity_id=entity_id, account_id__in=account_ids, day__gte=date_from,
        day__lte=date_to, is_closing=False,
    )  # fmt: skip
    facts = _facts((r.account_id, r.day, r.debit_total, r.credit_total) for r in rows)
    _subtract(facts, ((a, d, dr, cr) for a, d, closing, dr, cr in later if not closing))
    return Actuals(pinned, _as_facts(facts))


def net_before(
    entity_id: UUID, tenant_id: UUID, *, before: date, watermark: int | None = None
) -> tuple[int, dict[UUID, Decimal]]:
    """Net debit balance per account from all postings dated before ``before`` (openings)."""
    pinned, later = _pinned(entity_id, tenant_id, watermark)
    rows: dict[tuple[UUID, date, bool], list[Decimal]] = {
        (r.account_id, r.day, r.is_closing): [r.debit_total, r.credit_total]
        for r in FactDaily.objects.filter(legal_entity_id=entity_id, day__lt=before)
    }
    for account_id, day, closing, debit, credit in later:
        key = (account_id, day, closing)
        if key in rows:
            rows[key][0] -= debit
            rows[key][1] -= credit
            if not rows[key][0] and not rows[key][1]:
                del rows[key]
    totals: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    for (account_id, _, _), (debit, credit) in rows.items():
        totals[account_id] += debit - credit
    return pinned, dict(totals)


Balances = dict[date, dict[UUID, Decimal]]


def net_before_many(
    entity_id: UUID, tenant_id: UUID, *, cutoffs: list[date]
) -> tuple[int, Balances, Balances]:
    """Net debit balance per account before each cut-off date, in one pass over the daily facts:
    all postings, and the part from year-end closing entries (included in the first).

    Accounts without postings before a cut-off are absent from that cut-off's mapping."""
    watermark = refresh(tenant_id)
    unique = sorted(set(cutoffs))
    net = F("debit_total") - F("credit_total")
    every: Balances = {d: {} for d in unique}
    closing: Balances = {d: {} for d in unique}
    if not unique:
        return watermark, every, closing
    sums = {}
    for i, d in enumerate(unique):
        sums[f"c{i}"] = Sum(net, filter=Q(day__lt=d))
        sums[f"k{i}"] = Sum(net, filter=Q(day__lt=d, is_closing=True))
    rows = cast(
        Iterable[dict[str, Any]],
        FactDaily.objects.filter(legal_entity_id=entity_id, day__lt=unique[-1])
        .values("account_id")
        .annotate(**sums),
    )
    for row in rows:
        for i, d in enumerate(unique):
            for prefix, target in (("c", every), ("k", closing)):
                value = row[f"{prefix}{i}"]
                if value is not None:
                    target[d][row["account_id"]] = value
    return watermark, every, closing


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
           {closing} AS closing, sum(l.debit) AS d, sum(l.credit) AS c
      FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
     WHERE e.tenant_id = %s AND e.status = 'POSTED' AND e.posting_seq <= %s
     GROUP BY 1, 2, 3, 4
), facts AS (
    SELECT legal_entity_id AS entity, account_id AS account, {key} AS period,
           is_closing AS closing, debit_total AS d, credit_total AS c
      FROM {table} WHERE tenant_id = %s
)
SELECT coalesce(l.entity, f.entity), coalesce(l.account, f.account), coalesce(l.period, f.period),
       coalesce(l.d, 0), coalesce(l.c, 0), coalesce(f.d, 0), coalesce(f.c, 0)
  FROM ledger l FULL OUTER JOIN facts f
    ON f.entity = l.entity AND f.account = l.account AND f.period = l.period
   AND f.closing = l.closing
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
            closing=_IS_CLOSING,
        ),
    ),
    (
        "daily",
        _COMPARE.format(
            table="reporting_fact_daily", key="day", expr="e.accounting_date", closing=_IS_CLOSING
        ),
    ),
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
