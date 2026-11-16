"""Public interface of the ``personal`` module and its HTTP routes (M5-1: personal finances).

Routes are entity-scoped (``/api/w/{slug}/entities/{entity_id}/personal/...``) and exist in
personal workspaces only. Amounts are decimal strings in each account's natural direction.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.ledger.api import Account
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import Valuation

__all__ = ["Valuation", "router"]

router = Router(tags=["personal"])
BASE = "/w/{slug}/entities/{uuid:entity_id}/personal"
AMOUNT = r"^\d{1,12}(\.\d{1,2})?$"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class PersonalSetupOut(Schema):
    created: bool = Field(description="True when the personal accounts were set up just now")


@router.post(f"{BASE}/setup", response=PersonalSetupOut)
@requires("ledger.account.manage")
def setup(request: HttpRequest, slug: str, entity_id: UUID) -> PersonalSetupOut:
    """Set up the personal accounts and open this year (safe to repeat)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return PersonalSetupOut(created=services.setup(ctx, entity_id))


class PersonalAccountOut(Schema):
    id: UUID
    code: str
    name: str
    type: str = Field(description="ASSET, LIABILITY (money accounts), INCOME or EXPENSE")
    balance: str = Field(description="From the ledger, in the account's natural direction")
    amount: str = Field(description="The valuation if there is one, otherwise the balance")
    nature: str = Field(description="ACTUAL, or EXPECTED for a valuation")
    valuation_date: date | None


def _account_out(v: services.AccountView) -> PersonalAccountOut:
    return PersonalAccountOut(
        id=v.account.id,
        code=v.account.code,
        name=v.account.name,
        type=v.account.type,
        balance=_money(v.balance),
        amount=_money(v.amount),
        nature=v.nature,
        valuation_date=v.valuation.value_date if v.valuation else None,
    )


class AsOfQuery(Schema):
    as_of: date | None = Field(None, description="Default: today")


@router.get(f"{BASE}/accounts", response=list[PersonalAccountOut])
@requires("reports.read")
def list_accounts(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[AsOfQuery]
) -> list[PersonalAccountOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.accounts(ctx, entity_id, q.as_of or timezone.localdate())
    return [_account_out(v) for v in found]


class PersonalAccountIn(Schema):
    kind: Literal["ASSET", "LIABILITY", "INCOME", "EXPENSE"]
    name: str = Field(min_length=1, max_length=120)


@router.post(f"{BASE}/accounts", response={201: PersonalAccountOut})
@requires("ledger.account.manage")
def add_account(
    request: HttpRequest, slug: str, entity_id: UUID, payload: PersonalAccountIn
) -> Status[PersonalAccountOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.new_account(ctx, entity_id, kind=payload.kind, name=payload.name)
    return Status(201, _account_out(services.AccountView(made, Decimal(0), None)))


class PersonalTransactionIn(Schema):
    kind: Literal["SPENT", "RECEIVED", "MOVED"]
    date: date
    amount: str = Field(pattern=AMOUNT)
    description: str = Field(min_length=1, max_length=300)
    account_id: UUID = Field(description="The money account it leaves, or arrives in if received")
    category_id: UUID | None = None
    to_account_id: UUID | None = None


class PersonalTransactionOut(Schema):
    entry_id: UUID
    ref: str
    date: date
    description: str
    kind: str = Field(description="SPENT, RECEIVED, MOVED, OPENING, UNDO or OTHER")
    amount: str
    account_id: UUID | None
    other_id: UUID | None = Field(description="The category, or the account money moved to")
    undone: bool = Field(description="A later reversal undid it")


def _transaction_out(t: services.Transaction) -> PersonalTransactionOut:
    e = t.entry
    return PersonalTransactionOut(
        entry_id=e.id,
        ref=e.ref,
        date=e.accounting_date,
        description=e.description,
        kind=t.kind,
        amount=_money(t.amount),
        account_id=t.account_id,
        other_id=t.other_id,
        undone=e.reversed_by_entry_id is not None,
    )


@router.post(f"{BASE}/transactions", response={201: PersonalTransactionOut})
@requires("ledger.entry.create")
def record(
    request: HttpRequest, slug: str, entity_id: UUID, payload: PersonalTransactionIn
) -> Status[PersonalTransactionOut]:
    """Record what you spent, received or moved: a balanced entry, posted at once."""
    ctx = workspace_ctx(request, slug, entity_id)
    entry = services.record(
        ctx,
        entity_id,
        services.TransactionInput(
            kind=payload.kind,
            day=payload.date,
            amount=payload.amount,
            description=payload.description,
            account_id=payload.account_id,
            category_id=payload.category_id,
            to_account_id=payload.to_account_id,
        ),
    )
    found = services.transactions(
        ctx, entity_id, date_from=entry.accounting_date, date_to=entry.accounting_date
    )
    return Status(201, _transaction_out(next(t for t in found if t.entry.id == entry.id)))


class PersonalTransactionsQuery(Schema):
    date_from: date
    date_to: date
    account_id: UUID | None = None


@router.get(f"{BASE}/transactions", response=list[PersonalTransactionOut])
@requires("reports.read")
def list_transactions(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[PersonalTransactionsQuery]
) -> list[PersonalTransactionOut]:
    """Newest first, at most 500."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.transactions(
        ctx, entity_id, date_from=q.date_from, date_to=q.date_to, account_id=q.account_id
    )
    return [_transaction_out(t) for t in found]


class PersonalUndoIn(Schema):
    reason: str = Field(min_length=1, max_length=500)


@router.post(f"{BASE}/transactions/{{uuid:entry_id}}/undo", response={201: PersonalTransactionOut})
@requires("ledger.entry.create")
def undo(
    request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID, payload: PersonalUndoIn
) -> Status[PersonalTransactionOut]:
    """Undo with a reversal dated today; the original stays in the history, marked undone."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.undo(ctx, entity_id, entry_id, reason=payload.reason)
    found = services.transactions(
        ctx, entity_id, date_from=made.accounting_date, date_to=made.accounting_date
    )
    return Status(201, _transaction_out(next(t for t in found if t.entry.id == made.id)))


class PersonalOpeningIn(Schema):
    account_id: UUID
    date: date
    amount: str = Field(pattern=AMOUNT, description="What it held (or owed) on that date")


@router.post(f"{BASE}/opening-balances", response={201: PersonalTransactionOut})
@requires("ledger.entry.create")
def opening_balance(
    request: HttpRequest, slug: str, entity_id: UUID, payload: PersonalOpeningIn
) -> Status[PersonalTransactionOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.opening_balance(
        ctx, entity_id, account_id=payload.account_id, day=payload.date, amount=payload.amount
    )
    found = services.transactions(
        ctx, entity_id, date_from=made.accounting_date, date_to=made.accounting_date
    )
    return Status(201, _transaction_out(next(t for t in found if t.entry.id == made.id)))


class PersonalValuationIn(Schema):
    account_id: UUID
    date: date
    value: str = Field(pattern=AMOUNT)
    note: str = Field("", max_length=300)


class PersonalValuationOut(Schema):
    id: UUID
    account_id: UUID
    date: date
    value: str
    nature: str
    note: str
    created_at: datetime
    superseded_at: datetime | None


def _valuation_out(v: Valuation) -> PersonalValuationOut:
    return PersonalValuationOut(
        id=v.id,
        account_id=v.account_id,
        date=v.value_date,
        value=_money(v.value),
        nature=v.nature,
        note=v.note,
        created_at=v.created_at,
        superseded_at=v.superseded_at,
    )


@router.post(f"{BASE}/valuations", response={201: PersonalValuationOut})
@requires("ledger.entry.create")
def set_valuation(
    request: HttpRequest, slug: str, entity_id: UUID, payload: PersonalValuationIn
) -> Status[PersonalValuationOut]:
    """What an asset is worth at a date (nature EXPECTED); never posted to the books."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.set_valuation(
        ctx,
        entity_id,
        account_id=payload.account_id,
        day=payload.date,
        value=payload.value,
        note=payload.note,
    )
    return Status(201, _valuation_out(made))


@router.get(f"{BASE}/accounts/{{uuid:account_id}}/valuations", response=list[PersonalValuationOut])
@requires("reports.read")
def list_valuations(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID
) -> list[PersonalValuationOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_valuation_out(v) for v in services.valuations(ctx, entity_id, account_id)]


class NetWorthPointOut(Schema):
    date: date
    net_worth: str
    includes_valuations: bool


class NetWorthOut(Schema):
    as_of: date
    assets: list[PersonalAccountOut]
    liabilities: list[PersonalAccountOut]
    total_assets: str
    total_liabilities: str
    net_worth: str
    includes_valuations: bool = Field(description="Some lines are valuations (EXPECTED)")
    trend: list[NetWorthPointOut] = Field(description="Month ends over the last 12 months")


@router.get(f"{BASE}/net-worth", response=NetWorthOut)
@requires("reports.read")
def net_worth(request: HttpRequest, slug: str, entity_id: UUID, q: Query[AsOfQuery]) -> NetWorthOut:
    ctx = workspace_ctx(request, slug, entity_id)
    n = services.net_worth(ctx, entity_id, q.as_of or timezone.localdate())
    return NetWorthOut(
        as_of=n.as_of,
        assets=[_account_out(v) for v in n.assets],
        liabilities=[_account_out(v) for v in n.liabilities],
        total_assets=_money(n.total_assets),
        total_liabilities=_money(n.total_liabilities),
        net_worth=_money(n.net_worth),
        includes_valuations=n.includes_valuations,
        trend=[
            NetWorthPointOut(date=d, net_worth=_money(v), includes_valuations=x)
            for d, v, x in n.trend
        ],
    )


class PeriodQuery(Schema):
    date_from: date
    date_to: date


class CategoryTotalOut(Schema):
    account_id: UUID
    name: str
    amount: str


class SpendingOut(Schema):
    date_from: date
    date_to: date
    income: list[CategoryTotalOut]
    spending: list[CategoryTotalOut]
    total_income: str
    total_spending: str
    left_over: str = Field(description="Income minus spending")


def _totals(rows: list[tuple[Account, Decimal]]) -> list[CategoryTotalOut]:
    return [CategoryTotalOut(account_id=a.id, name=a.name, amount=_money(v)) for a, v in rows]


@router.get(f"{BASE}/spending", response=SpendingOut)
@requires("reports.read")
def spending(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[PeriodQuery]
) -> SpendingOut:
    ctx = workspace_ctx(request, slug, entity_id)
    s = services.spending(ctx, entity_id, date_from=q.date_from, date_to=q.date_to)
    return SpendingOut(
        date_from=s.date_from,
        date_to=s.date_to,
        income=_totals(s.income),
        spending=_totals(s.spending),
        total_income=_money(s.total_income),
        total_spending=_money(s.total_spending),
        left_over=_money(s.total_income - s.total_spending),
    )
