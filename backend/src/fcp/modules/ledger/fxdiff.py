"""Exchange differences on foreign-currency positions (V1-2h2, #230; ADR-0066; IAS 21).

A **position** is the posted foreign-currency lines of one monetary account, counterparty and
currency, on or before a date: receivables and payables (control accounts) and accounts kept in
a foreign currency (for example a dollar bank account). Its foreign balance is the sum of the
lines' foreign amounts; its euro balance the sum of their functional amounts, including earlier
exchange differences, so a new revaluation only adds what changed since the last one.

- **Unrealised:** a position still open is revalued at the closing rate on the date: the euro
  balance it should have (the foreign balance times the rate, rounded half up to the cent)
  minus the euro balance it has.
- **Realised:** a position whose foreign balance is settled to zero but with euros left is cleared.

Both go to the entity's exchange-differences account (Ledger settings) in one **draft** entry:
it follows the normal approval and posting, and nothing is posted automatically. Non-monetary
items (assets, expenses, income) stay at the rate of their transaction, as IAS 21 requires.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.db.models import F, Q, Sum

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import entries, fx
from .models import Account, JournalEntry, JournalLine

READ = "ledger.entry.read"
CENT = Decimal("0.01")


@dataclass(frozen=True)
class Position:
    account_id: UUID
    account_code: str
    account_name: str
    counterparty_id: UUID | None
    currency: str
    foreign: Decimal
    euros: Decimal
    rate: Decimal | None
    rate_date: date | None
    rate_source: str
    revalued: Decimal | None
    difference: Decimal
    kind: str  # UNREALISED, REALISED, NO_RATE or "" (nothing to do)


@dataclass(frozen=True)
class Positions:
    on: date
    positions: list[Position]
    unrealised: Decimal
    realised: Decimal
    missing_rates: list[str]
    fx_account_id: UUID | None
    waiting_entry_id: UUID | None


def _monetary() -> Q:
    return Q(account__control_type__in=[Account.Control.RECEIVABLE, Account.Control.PAYABLE]) | ~Q(
        account__currency=""
    )


def _waiting(entity_id: UUID) -> UUID | None:
    """An exchange-differences draft not yet posted or voided, if any."""
    line = (
        JournalLine.objects.filter(entry__legal_entity_id=entity_id)
        .exclude(fx_difference="")
        .exclude(entry__status__in=[JournalEntry.Status.POSTED, JournalEntry.Status.VOID])
        .first()
    )
    return line.entry_id if line else None


def positions(ctx: WorkspaceContext, entity_id: UUID, on: date) -> Positions:
    """Every foreign-currency position on ``on`` and its exchange difference."""
    get_entity(ctx, entity_id, READ)
    rows = (
        JournalLine.objects.filter(
            entry__legal_entity_id=entity_id,
            entry__status=JournalEntry.Status.POSTED,
            entry__accounting_date__lte=on,
            txn_currency__isnull=False,
        )
        .filter(_monetary())
        .values("account_id", "account__code", "account__name", "counterparty_id", "txn_currency")
        .annotate(
            foreign=Sum(F("txn_debit") - F("txn_credit")),
            euros=Sum(F("debit") - F("credit")),
        )
        .order_by("account__code", "txn_currency", "counterparty_id")
    )
    rates: dict[str, fx.SuggestedRate | None] = {}
    found: list[Position] = []
    for r in rows:
        currency = str(r["txn_currency"])  # never null: the query filters it
        foreign: Decimal = r["foreign"]
        euros: Decimal = r["euros"].quantize(CENT)
        if currency not in rates:
            rates[currency] = fx.suggested_rate(ctx, entity_id, currency, on, prefer="CLOSING")
        rate = rates[currency]
        revalued: Decimal | None = None
        if foreign == 0:
            kind, difference = ("REALISED" if euros else ""), -euros
        elif rate is None:
            kind, difference = "NO_RATE", Decimal(0)
        else:
            revalued = (foreign * rate.rate).quantize(CENT, ROUND_HALF_UP)
            difference = revalued - euros
            kind = "UNREALISED" if difference else ""
        found.append(
            Position(
                account_id=r["account_id"],
                account_code=r["account__code"],
                account_name=r["account__name"],
                counterparty_id=r["counterparty_id"],
                currency=currency,
                foreign=foreign,
                euros=euros,
                rate=rate.rate if rate else None,
                rate_date=rate.rate_date if rate else None,
                rate_source=f"{rate.source} ({rate.rate_type}, {rate.rate_date})" if rate else "",
                revalued=revalued,
                difference=difference,
                kind=kind,
            )
        )
    return Positions(
        on=on,
        positions=found,
        unrealised=sum((p.difference for p in found if p.kind == "UNREALISED"), Decimal(0)),
        realised=sum((p.difference for p in found if p.kind == "REALISED"), Decimal(0)),
        missing_rates=sorted(c for c, rate in rates.items() if rate is None),
        fx_account_id=entries.ledger_settings(ctx, entity_id).fx_account_id,
        waiting_entry_id=_waiting(entity_id),
    )


def _side(amount: Decimal) -> tuple[str, str]:
    """(debit, credit) for a signed functional amount, debit positive."""
    return (f"{amount:.2f}", "0") if amount > 0 else ("0", f"{-amount:.2f}")


def draft(ctx: WorkspaceContext, entity_id: UUID, on: date) -> JournalEntry:
    """One draft entry with every exchange difference on ``on`` against the exchange-differences
    account. Refused while an earlier one is waiting, so a difference is never booked twice."""
    found = positions(ctx, entity_id, on)
    if found.waiting_entry_id:
        raise ConflictError("An exchange-differences entry is waiting: post or void it first.")
    if found.fx_account_id is None:
        raise ValidationFailedError(
            "Choose the account for exchange differences in the ledger settings first."
        )
    due = [p for p in found.positions if p.kind in ("UNREALISED", "REALISED")]
    if not due:
        raise ValidationFailedError(f"There are no exchange differences to record on {on}.")
    at = datetime.combine(on, time(23, 59), tzinfo=UTC)
    lines: list[entries.LineInput] = []
    for p in due:
        unrealised = p.kind == "UNREALISED"
        debit, credit = _side(p.difference)
        lines.append(
            entries.LineInput(
                account_id=p.account_id,
                counterparty_id=p.counterparty_id,
                memo=f"Exchange difference, {p.currency} "
                + ("revalued at the closing rate" if unrealised else "balance settled"),
                txn_currency=p.currency,
                txn_amount="0",
                exchange_rate=str(p.rate) if unrealised else None,
                rate_at=datetime.combine(p.rate_date, time(0), tzinfo=UTC)
                if unrealised and p.rate_date
                else at,
                rate_source=p.rate_source
                if unrealised
                else f"Realised: the {p.currency} balance is settled",
                fx_difference=p.kind,
                debit=debit,
                credit=credit,
            )
        )
    for kind, total in (("UNREALISED", found.unrealised), ("REALISED", found.realised)):
        if total:
            debit, credit = _side(-total)
            lines.append(
                entries.LineInput(
                    account_id=found.fx_account_id,
                    memo=f"Exchange differences, {kind.lower()}",
                    debit=debit,
                    credit=credit,
                )
            )
    return entries.create_draft(
        ctx,
        entity_id,
        entries.EntryInput(
            accounting_date=on,
            description=f"Exchange differences on {on.isoformat()}",
            lines=lines,
        ),
        source=JournalEntry.Source.SYSTEM,
    )
