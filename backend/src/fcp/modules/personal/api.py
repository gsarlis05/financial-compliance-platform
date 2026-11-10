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

from . import counterpart, plans, services
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


# --- budget, goals and projection (M5-2) ----------------------------------------------------------


class PersonalBudgetIn(Schema):
    account_id: UUID = Field(description="An income or spending category")
    monthly_amount: str = Field(pattern=AMOUNT, description="0 ends the budget")
    from_month: date = Field(description="Any day of the first month it applies to")


class PersonalBudgetLineOut(Schema):
    account_id: UUID
    name: str
    type: str
    budgeted: str
    actual: str
    remaining: str
    over: bool = Field(description="Spending above budget, or income below it")


class PersonalBudgetOut(Schema):
    month: date
    lines: list[PersonalBudgetLineOut]
    budgeted_spending: str
    actual_spending: str


def _budget_out(b: plans.MonthBudget) -> PersonalBudgetOut:
    lines = [
        PersonalBudgetLineOut(
            account_id=x.account.id, name=x.account.name, type=x.account.type,
            budgeted=_money(x.budgeted), actual=_money(x.actual), remaining=_money(x.remaining),
            over=bool(x.budgeted) and ((x.actual > x.budgeted) if x.account.type == "EXPENSE"
                                       else (x.actual < x.budgeted)),
        )
        for x in b.lines
    ]  # fmt: skip
    spend = [x for x in b.lines if x.account.type == "EXPENSE"]
    return PersonalBudgetOut(
        month=b.month, lines=lines,
        budgeted_spending=_money(sum((x.budgeted for x in spend), Decimal(0))),
        actual_spending=_money(sum((x.actual for x in spend), Decimal(0))),
    )  # fmt: skip


class MonthQuery(Schema):
    month: date | None = Field(None, description="Any day of the month; default: this month")


@router.get(f"{BASE}/budget", response=PersonalBudgetOut)
@requires("reports.read")
def month_budget(request: HttpRequest, slug: str, entity_id: UUID,
                 q: Query[MonthQuery]) -> PersonalBudgetOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _budget_out(plans.month_budget(ctx, entity_id, q.month or timezone.localdate()))


@router.put(f"{BASE}/budget", response=PersonalBudgetOut)
@requires("ledger.entry.create")
def set_budget(request: HttpRequest, slug: str, entity_id: UUID,
               payload: PersonalBudgetIn) -> PersonalBudgetOut:  # fmt: skip
    """Set a category's monthly amount from a month on (kept as a new version)."""
    ctx = workspace_ctx(request, slug, entity_id)
    plans.set_budget(ctx, entity_id, account_id=payload.account_id,
                     monthly=payload.monthly_amount, from_month=payload.from_month)  # fmt: skip
    return _budget_out(plans.month_budget(ctx, entity_id, payload.from_month))


class PersonalGoalIn(Schema):
    kind: Literal["SAVINGS", "EMERGENCY_FUND", "DEBT_PAYOFF"]
    name: str = Field(min_length=1, max_length=120)
    account_ids: list[UUID] = Field(min_length=1, max_length=20)
    target_date: date
    target_amount: str = Field("0", pattern=AMOUNT)
    months: int | None = Field(None, description="Emergency fund: months of spending")


class PersonalGoalOut(Schema):
    id: UUID
    kind: str
    name: str
    account_ids: list[UUID]
    target_date: date
    months: int | None
    retired_at: datetime | None
    current: str
    target: str
    months_left: int
    needed_per_month: str | None
    pace_per_month: str
    projected: str
    status: str = Field(description="ON_TRACK, AT_RISK (within 5%) or OFF_TRACK")
    average_spending: str | None = Field(description="Emergency fund: per month, last 3 months")


def _goal_out(s: plans.GoalStatus) -> PersonalGoalOut:
    g = s.goal
    return PersonalGoalOut(
        id=g.id, kind=g.kind, name=g.name, account_ids=[UUID(a) for a in g.account_ids],
        target_date=g.target_date, months=g.months, retired_at=g.retired_at,
        current=_money(s.current), target=_money(s.target), months_left=s.months_left,
        needed_per_month=None if s.needed_per_month is None else _money(s.needed_per_month),
        pace_per_month=_money(s.pace_per_month), projected=_money(s.projected), status=s.status,
        average_spending=None if s.average_spending is None else _money(s.average_spending),
    )  # fmt: skip


class GoalsQuery(Schema):
    include_retired: bool = False


@router.get(f"{BASE}/goals", response=list[PersonalGoalOut])
@requires("reports.read")
def list_goals(request: HttpRequest, slug: str, entity_id: UUID,
               q: Query[GoalsQuery]) -> list[PersonalGoalOut]:  # fmt: skip
    """Each goal evaluated now from your books and valuations."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = plans.goals(ctx, entity_id, include_retired=q.include_retired)
    return [_goal_out(s) for s in found]


@router.post(f"{BASE}/goals", response={201: PersonalGoalOut})
@requires("ledger.entry.create")
def create_goal(request: HttpRequest, slug: str, entity_id: UUID,
                payload: PersonalGoalIn) -> Status[PersonalGoalOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    goal = plans.create_goal(ctx, entity_id, plans.GoalInput(
        kind=payload.kind, name=payload.name, account_ids=payload.account_ids,
        target_date=payload.target_date, target_amount=payload.target_amount,
        months=payload.months,
    ))  # fmt: skip
    return Status(201, _goal_out(plans.evaluate(ctx, entity_id, goal)))


@router.post(f"{BASE}/goals/{{uuid:goal_id}}/retire", response=PersonalGoalOut)
@requires("ledger.entry.create")
def retire_goal(request: HttpRequest, slug: str, entity_id: UUID,
                goal_id: UUID) -> PersonalGoalOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    goal = plans.retire_goal(ctx, entity_id, goal_id)
    return _goal_out(plans.evaluate(ctx, entity_id, goal))


class ProjectionMonthOut(Schema):
    month: date
    income: str
    spending: str
    closing_cash: str
    nature: str = Field(description="BUDGET when every amount is budgeted, otherwise FORECAST")


class ProjectionOut(Schema):
    as_of: date
    opening_cash: str = Field(description="Money accounts you have, without valued assets")
    months: list[ProjectionMonthOut]
    first_negative: date | None = Field(description="The first month cash would fall below 0")


@router.get(f"{BASE}/projection", response=ProjectionOut)
@requires("reports.read")
def projection(request: HttpRequest, slug: str, entity_id: UUID) -> ProjectionOut:
    """The next 12 months: the budget where set, otherwise the last 3 months' average."""
    ctx = workspace_ctx(request, slug, entity_id)
    p = plans.projection(ctx, entity_id)
    return ProjectionOut(
        as_of=p.as_of, opening_cash=_money(p.opening_cash),
        months=[ProjectionMonthOut(month=m.month, income=_money(m.income),
                                   spending=_money(m.spending), closing_cash=_money(m.closing_cash),
                                   nature="BUDGET" if m.from_budget else "FORECAST")
                for m in p.months],
        first_negative=p.first_negative,
    )  # fmt: skip


# --- counterpart hints (M5-3) ---------------------------------------------------------------------


class CounterpartLinkIn(Schema):
    business_slug: str = Field(max_length=64, description="One of your business workspaces")
    business_entity_id: UUID
    business_account_id: UUID = Field(description="e.g. the director's loan account")
    label: str = Field(max_length=200, description="How the link is named here")
    account_id: UUID = Field(description="Your money account the payments arrive in")
    category_id: UUID = Field(description="Your income category for them")
    since: date = Field(description="Suggest payments from this date")


class CounterpartLinkOut(Schema):
    id: UUID
    business_slug: str
    business_entity_id: UUID
    business_account_id: UUID
    label: str
    account_id: UUID
    category_id: UUID
    since: date
    created_at: datetime


class CounterpartDecisionIn(Schema):
    business_entry_id: UUID = Field(description="The business entry the suggestion comes from")
    date: date
    amount: str = Field(pattern=AMOUNT)
    description: str = Field(max_length=300)


def _decision(payload: CounterpartDecisionIn) -> counterpart.DecisionInput:
    return counterpart.DecisionInput(
        business_entry_id=payload.business_entry_id, day=payload.date, amount=payload.amount,
        description=payload.description,
    )  # fmt: skip


class CounterpartDecisionOut(Schema):
    id: UUID
    business_entry_id: UUID
    decision: str = Field(description="CONFIRMED (recorded here) or DISMISSED")
    amount: str
    entry_date: date
    personal_entry_id: UUID | None
    created_at: datetime


def _link_out(link: counterpart.CounterpartLink) -> CounterpartLinkOut:
    return CounterpartLinkOut(
        id=link.id, business_slug=link.business_slug, business_entity_id=link.business_entity_id,
        business_account_id=link.business_account_id, label=link.label,
        account_id=link.account_id, category_id=link.category_id, since=link.since,
        created_at=link.created_at,
    )  # fmt: skip


def _decision_out(d: counterpart.CounterpartDecision) -> CounterpartDecisionOut:
    return CounterpartDecisionOut(
        id=d.id, business_entry_id=d.business_entry_id, decision=d.decision,
        amount=_money(d.amount), entry_date=d.entry_date, personal_entry_id=d.personal_entry_id,
        created_at=d.created_at,
    )  # fmt: skip


@router.get(f"{BASE}/counterpart-links", response=list[CounterpartLinkOut])
@requires("reports.read")
def list_counterpart_links(request: HttpRequest, slug: str,
                           entity_id: UUID) -> list[CounterpartLinkOut]:  # fmt: skip
    """Your opt-in links to business accounts (no business figures are stored here)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_link_out(link) for link in counterpart.links(ctx, entity_id)]


@router.post(f"{BASE}/counterpart-links", response={201: CounterpartLinkOut})
@requires("ledger.entry.create")
def create_counterpart_link(request: HttpRequest, slug: str, entity_id: UUID,
                            payload: CounterpartLinkIn) -> Status[CounterpartLinkOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    link = counterpart.create_link(ctx, entity_id, counterpart.LinkInput(**payload.dict()))
    return Status(201, _link_out(link))


@router.post(f"{BASE}/counterpart-links/{{uuid:link_id}}/revoke", response={204: None})
@requires("ledger.entry.create")
def revoke_counterpart_link(request: HttpRequest, slug: str, entity_id: UUID,
                            link_id: UUID) -> Status[None]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    counterpart.revoke_link(ctx, entity_id, link_id)
    return Status(204, None)


@router.get(f"{BASE}/counterpart-links/{{uuid:link_id}}/decisions",
            response=list[CounterpartDecisionOut])  # fmt: skip
@requires("reports.read")
def list_counterpart_decisions(request: HttpRequest, slug: str, entity_id: UUID,
                               link_id: UUID) -> list[CounterpartDecisionOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return [_decision_out(d) for d in counterpart.decided(ctx, entity_id, link_id)]


@router.post(f"{BASE}/counterpart-links/{{uuid:link_id}}/confirm",
             response={201: CounterpartDecisionOut})  # fmt: skip
@requires("ledger.entry.create")
def confirm_counterpart(
    request: HttpRequest, slug: str, entity_id: UUID, link_id: UUID, payload: CounterpartDecisionIn
) -> Status[CounterpartDecisionOut]:
    """Record a suggested business payment as money received here."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = counterpart.confirm(ctx, entity_id, link_id, _decision(payload))
    return Status(201, _decision_out(made))


@router.post(f"{BASE}/counterpart-links/{{uuid:link_id}}/dismiss",
             response={201: CounterpartDecisionOut})  # fmt: skip
@requires("ledger.entry.create")
def dismiss_counterpart(
    request: HttpRequest, slug: str, entity_id: UUID, link_id: UUID, payload: CounterpartDecisionIn
) -> Status[CounterpartDecisionOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    made = counterpart.dismiss(ctx, entity_id, link_id, _decision(payload))
    return Status(201, _decision_out(made))
