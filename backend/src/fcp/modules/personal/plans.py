"""Personal budget, goals and the 12-month cash projection (M5-2).

Kept simple on purpose (owner, 2026-11-10: "continue with what is easier for now"):
- **Budget:** a monthly amount per income or spending category, in force from a month until
  changed (versioned, nature BUDGET). Each month compares it with what was actually posted.
- **Goals:** evaluated on request from the books and valuations; nothing derived is stored.
  - **Savings:** the chosen money accounts reach a total by a date.
  - **Emergency fund:** they hold a number of months of average spending (the last 3 complete
    months).
  - **Debt payoff:** the chosen debts are paid down to a target (default 0) by a date.

  Each goal shows the current amount, the monthly amount needed, the recent pace (over the last 3
  complete months), the projected amount at the date, and on track / at risk (within 5%) / off
  track.
- **Projection:** 12 months of income, spending and cash, starting from the cash today (money
  assets without a valuation). A category with a budget uses it (nature BUDGET); without one, its
  average of the last 3 complete months (nature FORECAST). The first month cash would fall below
  zero is flagged. Moves between your own accounts are not projected.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.ledger.api import Account, account_list, trial_balance_rows
from fcp.modules.tenancy.api import WorkspaceContext

from .models import BudgetAmount, PersonalGoal
from .services import CATEGORY, READ, WRITE, _account, _amount, _entity, _invalid, accounts

ZERO = Decimal(0)
MATERIALITY = Decimal("0.05")
HISTORY_MONTHS = 3
Kind = PersonalGoal.Kind


def _months_between(first: date, last: date) -> int:
    """Months from ``first``'s month to ``last``'s month, both counted (0 if last is earlier)."""
    return max(0, (last.year - first.year) * 12 + last.month - first.month + 1)


def _flows(ctx: WorkspaceContext, entity: UUID, first: date, last: date) -> dict[UUID, Decimal]:
    """Category totals (natural direction) posted from ``first`` to ``last``."""
    rows = trial_balance_rows(ctx, entity, as_of=last, date_from=first)
    return {r.account_id: r.balance for r in rows}


# --- budget ---------------------------------------------------------------------------------------


@transaction.atomic
def set_budget(
    ctx: WorkspaceContext, entity_id: UUID, *, account_id: UUID, monthly: str, from_month: date
) -> BudgetAmount:
    entity = _entity(ctx, entity_id, WRITE)
    category = _account(ctx, entity, account_id, CATEGORY, "account_id")
    amount = _amount(monthly, "monthly_amount", allow_zero=True)
    start = month_start(from_month)
    previous = (
        BudgetAmount.objects.select_for_update()
        .filter(
            legal_entity_id=entity,
            account_id=category.id,
            effective_from=start,
            superseded_at__isnull=True,
        )
        .first()
    )
    if previous is not None:
        previous.superseded_at = timezone.now()
        previous.save(update_fields=["superseded_at"])
    made = BudgetAmount.objects.create(
        tenant=ctx.tenant,
        legal_entity_id=entity,
        account_id=category.id,
        effective_from=start,
        monthly_amount=amount,
        created_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="personal.budget.set",
        subject_type="budget_amount",
        subject_id=made.id,
        entity_id=entity,
        changes={"category": category.code, "from": start.isoformat(), "monthly": f"{amount:.2f}"},
    )
    return made


def _budgets_in_force(entity: UUID, month: date) -> dict[UUID, BudgetAmount]:
    found: dict[UUID, BudgetAmount] = {}
    rows = BudgetAmount.objects.filter(
        legal_entity_id=entity, superseded_at__isnull=True, effective_from__lte=month
    ).order_by("effective_from")
    for row in rows:
        found[row.account_id] = row
    return {k: v for k, v in found.items() if v.monthly_amount > 0}


@dataclass(frozen=True)
class BudgetLine:
    account: Account
    budgeted: Decimal
    actual: Decimal

    @property
    def remaining(self) -> Decimal:
        return self.budgeted - self.actual


@dataclass(frozen=True)
class MonthBudget:
    month: date
    lines: list[BudgetLine]


def month_budget(ctx: WorkspaceContext, entity_id: UUID, month: date) -> MonthBudget:
    """Every category with a budget or actuals in the month, with both."""
    entity = _entity(ctx, entity_id, READ)
    first = month_start(month)
    budgets = _budgets_in_force(entity, first)
    actual = _flows(ctx, entity, first, month_end(first))
    lines = []
    for a in account_list(ctx, entity):
        if a.type not in CATEGORY or not a.is_postable:
            continue
        b = budgets[a.id].monthly_amount if a.id in budgets else ZERO
        spent = actual.get(a.id, ZERO)
        if b or spent:
            lines.append(BudgetLine(a, b, spent))
    return MonthBudget(first, lines)


# --- goals ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalInput:
    kind: str
    name: str
    account_ids: list[UUID]
    target_date: date
    target_amount: str = "0"
    months: int | None = None


@transaction.atomic
def create_goal(ctx: WorkspaceContext, entity_id: UUID, data: GoalInput) -> PersonalGoal:
    entity = _entity(ctx, entity_id, WRITE)
    if data.kind not in Kind.values:
        raise _invalid("kind", "Choose savings, an emergency fund or paying off debt.")
    name = data.name.strip()
    if not name or len(name) > 120:
        raise _invalid("name", "Give the goal a name of 1 to 120 characters.")
    wanted = ("LIABILITY",) if data.kind == Kind.DEBT_PAYOFF else ("ASSET",)
    if not data.account_ids or len(set(data.account_ids)) != len(data.account_ids):
        raise _invalid("account_ids", "Choose the accounts this goal counts.")
    for account_id in data.account_ids:
        _account(ctx, entity, account_id, wanted, "account_ids")
    if data.target_date <= timezone.localdate():
        raise _invalid("target_date", "Choose a date in the future.")
    target = _amount(data.target_amount, "target_amount", allow_zero=True)
    months = data.months
    if data.kind == Kind.EMERGENCY_FUND:
        if months is None or not 1 <= months <= 36:
            raise _invalid("months", "Choose 1 to 36 months of spending.")
    elif data.kind == Kind.SAVINGS and target == 0:
        raise _invalid("target_amount", "Enter how much you want to have saved.")
    goal = PersonalGoal.objects.create(
        tenant=ctx.tenant,
        legal_entity_id=entity,
        kind=data.kind,
        name=name,
        account_ids=[str(a) for a in data.account_ids],
        target_amount=target,
        months=months if data.kind == Kind.EMERGENCY_FUND else None,
        target_date=data.target_date,
        created_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="personal.goal.created",
        subject_type="personal_goal",
        subject_id=goal.id,
        entity_id=entity,
        changes={
            "kind": goal.kind,
            "name": name,
            "target": f"{target:.2f}",
            "target_date": data.target_date.isoformat(),
        },
    )
    return goal


@transaction.atomic
def retire_goal(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID) -> PersonalGoal:
    entity = _entity(ctx, entity_id, WRITE)
    goal = (
        PersonalGoal.objects.select_for_update().filter(legal_entity_id=entity, id=goal_id).first()
    )
    if goal is None:
        raise NotFoundError("Goal not found.")
    if goal.retired_at is not None:
        raise ConflictError("This goal is already retired.")
    goal.retired_at = timezone.now()
    goal.save(update_fields=["retired_at"])
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="personal.goal.retired",
        subject_type="personal_goal",
        subject_id=goal.id,
        entity_id=entity,
        changes={},
    )
    return goal


@dataclass(frozen=True)
class GoalStatus:
    goal: PersonalGoal
    current: Decimal  # what the accounts hold (or, for debts, owe) today
    target: Decimal  # for an emergency fund: months x average monthly spending
    months_left: int
    needed_per_month: Decimal | None  # None when the date has passed
    pace_per_month: Decimal  # saved (or paid down) per month over the last 3 months
    projected: Decimal  # at the target date, at the recent pace
    status: str  # ON_TRACK | AT_RISK | OFF_TRACK
    average_spending: Decimal | None = None  # emergency fund only


def _status(on_target: bool, gap: Decimal, target: Decimal) -> str:
    if on_target:
        return "ON_TRACK"
    return "AT_RISK" if gap <= MATERIALITY * max(abs(target), Decimal(1)) else "OFF_TRACK"


def _sum(views: dict[UUID, Any], ids: list[str]) -> Decimal:
    return sum((views[UUID(i)].amount for i in ids if UUID(i) in views), ZERO)


def average_spending(ctx: WorkspaceContext, entity: UUID, today: date) -> Decimal:
    """Average monthly spending over the last 3 complete months."""
    last = month_start(today) - timedelta(days=1)
    first = add_months(month_start(last), -(HISTORY_MONTHS - 1))
    kinds = {a.id: a.type for a in account_list(ctx, entity)}
    total = sum(
        (v for a, v in _flows(ctx, entity, first, last).items() if kinds.get(a) == "EXPENSE"), ZERO
    )
    return total / HISTORY_MONTHS


def evaluate(ctx: WorkspaceContext, entity_id: UUID, goal: PersonalGoal) -> GoalStatus:
    entity = _entity(ctx, entity_id, READ)
    today = timezone.localdate()
    now = {v.account.id: v for v in accounts(ctx, entity, today)}
    # The recent pace: the change over the last 3 complete months.
    recent_day = month_start(today) - timedelta(days=1)
    earlier_day = add_months(month_start(today), -HISTORY_MONTHS) - timedelta(days=1)
    recent = {v.account.id: v for v in accounts(ctx, entity, recent_day)}
    before = {v.account.id: v for v in accounts(ctx, entity, earlier_day)}
    current = _sum(now, goal.account_ids)
    latest, earlier = _sum(recent, goal.account_ids), _sum(before, goal.account_ids)
    months_left = _months_between(add_months(month_start(today), 1), goal.target_date)
    average = None
    if goal.kind == Kind.DEBT_PAYOFF:
        target = goal.target_amount
        pace = (earlier - latest) / HISTORY_MONTHS  # paid down per month
        projected = max(current - pace * months_left, ZERO)
        needed = (max(current - target, ZERO) / months_left) if months_left else None
        status = _status(projected <= target, projected - target, target)
    else:
        if goal.kind == Kind.EMERGENCY_FUND:
            average = average_spending(ctx, entity, today)
            target = (average * (goal.months or 0)).quantize(Decimal("0.01"))
        else:
            target = goal.target_amount
        pace = (latest - earlier) / HISTORY_MONTHS
        projected = current + pace * months_left
        needed = (max(target - current, ZERO) / months_left) if months_left else None
        status = _status(projected >= target, target - projected, target)
    return GoalStatus(goal, current, target, months_left, needed, pace, projected, status, average)


def goals(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    include_retired: bool = False,
) -> list[GoalStatus]:
    entity = _entity(ctx, entity_id, READ)
    rows = PersonalGoal.objects.filter(legal_entity_id=entity).order_by("target_date", "name")
    if not include_retired:
        rows = rows.filter(retired_at__isnull=True)
    return [evaluate(ctx, entity, g) for g in rows]


# --- projection -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectionMonth:
    month: date
    income: Decimal
    spending: Decimal
    closing_cash: Decimal
    from_budget: bool  # every amount this month comes from the budget


@dataclass(frozen=True)
class Projection:
    as_of: date
    opening_cash: Decimal
    months: list[ProjectionMonth]
    first_negative: date | None


def projection(ctx: WorkspaceContext, entity_id: UUID, months: int = 12) -> Projection:
    entity = _entity(ctx, entity_id, READ)
    today = timezone.localdate()
    views = accounts(ctx, entity, today)
    cash = sum(
        (v.balance for v in views if v.account.type == "ASSET" and v.valuation is None), ZERO
    )
    kinds = {v.account.id: v.account.type for v in views if v.account.type in CATEGORY}
    last = month_start(today) - timedelta(days=1)
    first = add_months(month_start(last), -(HISTORY_MONTHS - 1))
    history = {
        a: v / HISTORY_MONTHS
        for a, v in _flows(ctx, entity, first, last).items()
        if a in kinds and v
    }
    rows, balance, negative = [], cash, None
    for i in range(1, months + 1):
        month = add_months(month_start(today), i)
        budgets = _budgets_in_force(entity, month)
        amounts: dict[str, Decimal] = defaultdict(Decimal)
        from_budget = True
        for account, kind in kinds.items():
            if account in budgets:
                amounts[kind] += budgets[account].monthly_amount
            elif account in history:
                amounts[kind] += history[account]
                from_budget = False
        balance += amounts["INCOME"] - amounts["EXPENSE"]
        if negative is None and balance < 0:
            negative = month
        rows.append(
            ProjectionMonth(month, amounts["INCOME"], amounts["EXPENSE"], balance, from_budget)
        )
    return Projection(today, cash, rows, negative)
