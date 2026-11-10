"""Personal finances over the ledger (M5-1, doc 11 §5).

Personal workspaces only (the ``personal_finances`` feature). Everything here is plain words on top
of double entry: each transaction becomes a balanced two-line entry that is posted at once, with
every ledger rule applied (open period, numbering, audit). A mistake is undone by a reversal.

- **Money accounts** are the postable asset and liability accounts; **categories** are the
  postable income and expense accounts. Amounts are shown in each account's natural direction
  (what you have, what you owe, what you earned, what you spent).
- **spent:** money account → spending category; **received:** income category → money account;
  **moved:** between money accounts (e.g. paying the credit card from the current account).
- **Valuations** (property, investments, a business stake) have nature EXPECTED and are never
  posted. Net worth uses the latest valuation on or before the date, otherwise the ledger balance,
  and labels each line.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.ledger.api import (
    Account,
    AccountInput,
    EntryInput,
    LineInput,
    PostedEntry,
    account_list,
    add_account,
    add_fiscal_year,
    apply_account_template,
    create_and_post,
    fiscal_year_list,
    posted_entries,
    reverse_and_post,
    trial_balance_rows,
)
from fcp.modules.tenancy.api import Feature, WorkspaceContext, get_entity, require_feature

from .models import Valuation

READ, WRITE, SETUP = "reports.read", "ledger.entry.create", "ledger.account.manage"
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1e12")
OPENING_EQUITY = "3000"
PARENTS = {"ASSET": "1", "LIABILITY": "2", "INCOME": "4", "EXPENSE": "6"}
MONEY, CATEGORY = ("ASSET", "LIABILITY"), ("INCOME", "EXPENSE")
SPENT, RECEIVED, MOVED = "SPENT", "RECEIVED", "MOVED"


def _invalid(name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={name: [message]})


def _entity(ctx: WorkspaceContext, entity_id: UUID, permission: str) -> UUID:
    require_feature(ctx.tenant.kind, Feature.PERSONAL_FINANCES)
    return get_entity(ctx, entity_id, permission).id


def _amount(raw: str | Decimal, name: str = "amount", *, allow_zero: bool = False) -> Decimal:
    try:
        value = Decimal(str(raw))
    except InvalidOperation:
        raise _invalid(name, "Enter an amount such as 12.50.") from None
    if (
        not value.is_finite()
        or value.quantize(CENT) != value
        or abs(value) >= MAX_AMOUNT
        or value < 0
        or (value == 0 and not allow_zero)
    ):
        raise _invalid(name, "Enter a positive amount with at most 2 decimals.")
    return value


# --- setup and accounts -------------------------------------------------------------------------


def ensure_year(ctx: WorkspaceContext, entity_id: UUID, day: date) -> None:
    """Personal books run by calendar year; a year is opened when it is first used."""
    if any(y.start_date <= day <= y.end_date for y in fiscal_year_list(ctx, entity_id)):
        return
    add_fiscal_year(
        ctx, entity_id, start_date=date(day.year, 1, 1), months=12, adjustment_period=False
    )


@transaction.atomic
def setup(ctx: WorkspaceContext, entity_id: UUID) -> bool:
    """Apply the personal chart of accounts (once) and open this year. True when it was new."""
    entity = _entity(ctx, entity_id, SETUP)
    fresh = not account_list(ctx, entity)
    if fresh:
        apply_account_template(ctx, entity, "personal")
    ensure_year(ctx, entity, timezone.localdate())
    return fresh


@dataclass(frozen=True)
class AccountView:
    account: Account
    balance: Decimal  # natural direction, from the ledger
    valuation: Valuation | None  # the latest current one on or before the date

    @property
    def amount(self) -> Decimal:
        return self.valuation.value if self.valuation is not None else self.balance

    @property
    def nature(self) -> str:
        return "EXPECTED" if self.valuation is not None else "ACTUAL"


def _latest_valuations(entity_id: UUID, as_of: date) -> dict[UUID, Valuation]:
    found: dict[UUID, Valuation] = {}
    rows = Valuation.objects.filter(
        legal_entity_id=entity_id, superseded_at__isnull=True, value_date__lte=as_of
    ).order_by("value_date", "created_at")
    for v in rows:
        found[v.account_id] = v
    return found


def accounts(ctx: WorkspaceContext, entity_id: UUID, as_of: date) -> list[AccountView]:
    """Every postable account with its balance at ``as_of`` (money accounts and categories)."""
    entity = _entity(ctx, entity_id, READ)
    balances = {r.account_id: r.balance for r in trial_balance_rows(ctx, entity, as_of=as_of)}
    valued = _latest_valuations(entity, as_of)
    return [
        AccountView(a, balances.get(a.id, Decimal(0)), valued.get(a.id))
        for a in account_list(ctx, entity)
        if a.is_postable and a.status == Account.Status.ACTIVE and a.type in (*MONEY, *CATEGORY)
    ]


def new_account(ctx: WorkspaceContext, entity_id: UUID, *, kind: str, name: str) -> Account:
    """A money account (ASSET or LIABILITY) or a category (INCOME or EXPENSE), numbered after the
    last one of its group."""
    entity = _entity(ctx, entity_id, SETUP)
    if kind not in PARENTS:
        raise _invalid("kind", "Choose an account you have, one you owe, income or spending.")
    name = name.strip()
    if not name or len(name) > 120:
        raise _invalid("name", "Give it a name of 1 to 120 characters.")
    parent = PARENTS[kind]
    siblings = [
        int(a.code)
        for a in account_list(ctx, entity)
        if a.code.isdigit() and a.code.startswith(parent) and len(a.code) == 4
    ]
    code = max(siblings, default=int(parent) * 1000) + 10
    if str(code)[0] != parent or code > int(parent) * 1000 + 999:
        raise _invalid("name", "This group is full: rename or archive an account instead.")
    return add_account(
        ctx, entity, AccountInput(code=str(code), name=name, type=kind, parent_code=parent)
    )


# --- transactions -------------------------------------------------------------------------------


@dataclass(frozen=True)
class TransactionInput:
    kind: str  # SPENT | RECEIVED | MOVED
    day: date
    amount: str
    description: str
    account_id: UUID  # the money account it leaves (SPENT, MOVED) or arrives in (RECEIVED)
    category_id: UUID | None = None  # SPENT, RECEIVED
    to_account_id: UUID | None = None  # MOVED


def _account(
    ctx: WorkspaceContext,
    entity_id: UUID,
    account_id: UUID | None,
    types: tuple[str, ...],
    name: str,
) -> Account:
    found = next((a for a in account_list(ctx, entity_id) if a.id == account_id), None)
    if (
        found is None
        or not found.is_postable
        or found.status != Account.Status.ACTIVE
        or found.type not in types
    ):
        what = "a money account" if types == MONEY else "a category"
        raise _invalid(name, f"Choose {what}.")
    return found


def record(ctx: WorkspaceContext, entity_id: UUID, data: TransactionInput) -> PostedEntry:
    entity = _entity(ctx, entity_id, WRITE)
    amount = _amount(data.amount)
    description = data.description.strip()
    if not description or len(description) > 300:
        raise _invalid("description", "Describe it in 1 to 300 characters.")
    money = _account(ctx, entity, data.account_id, MONEY, "account_id")
    text = f"{amount:.2f}"
    if data.kind == SPENT:
        other = _account(ctx, entity, data.category_id, ("EXPENSE",), "category_id")
        lines = [LineInput(other.id, debit=text), LineInput(money.id, credit=text)]
    elif data.kind == RECEIVED:
        other = _account(ctx, entity, data.category_id, ("INCOME",), "category_id")
        lines = [LineInput(money.id, debit=text), LineInput(other.id, credit=text)]
    elif data.kind == MOVED:
        other = _account(ctx, entity, data.to_account_id, MONEY, "to_account_id")
        if other.id == money.id:
            raise _invalid("to_account_id", "Choose a different account to move the money to.")
        lines = [LineInput(other.id, debit=text), LineInput(money.id, credit=text)]
    else:
        raise _invalid("kind", "Choose spent, received or moved.")
    with transaction.atomic():
        ensure_year(ctx, entity, data.day)
        return create_and_post(
            ctx, entity, EntryInput(accounting_date=data.day, description=description, lines=lines)
        )


def opening_balance(
    ctx: WorkspaceContext, entity_id: UUID, *, account_id: UUID, day: date, amount: str
) -> PostedEntry:
    """What a money account held (or owed) at a date, against "Opening net worth"."""
    entity = _entity(ctx, entity_id, WRITE)
    value = _amount(amount)
    money = _account(ctx, entity, account_id, MONEY, "account_id")
    equity = next((a for a in account_list(ctx, entity) if a.code == OPENING_EQUITY), None)
    if equity is None:
        raise NotFoundError("Set up your personal finances first.")
    text = f"{value:.2f}"
    if money.type == "ASSET":
        lines = [LineInput(money.id, debit=text), LineInput(equity.id, credit=text)]
    else:
        lines = [LineInput(equity.id, debit=text), LineInput(money.id, credit=text)]
    with transaction.atomic():
        ensure_year(ctx, entity, day)
        return create_and_post(
            ctx,
            entity,
            EntryInput(
                accounting_date=day, description=f"Opening balance: {money.name}", lines=lines
            ),
        )


def undo(ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID, *, reason: str) -> PostedEntry:
    """Undo a transaction with a reversal dated today (the original is kept)."""
    entity = _entity(ctx, entity_id, WRITE)
    today = timezone.localdate()
    with transaction.atomic():
        ensure_year(ctx, entity, today)
        return reverse_and_post(ctx, entity, entry_id, reason=reason, reversal_date=today)


@dataclass(frozen=True)
class Transaction:
    entry: PostedEntry
    kind: str  # SPENT | RECEIVED | MOVED | OPENING | UNDO | OTHER
    amount: Decimal
    account_id: UUID | None
    other_id: UUID | None  # the category, or the account money moved to


def _classify(entry: PostedEntry, types: dict[UUID, str], codes: dict[UUID, str]) -> Transaction:
    if entry.reverses_entry_id is not None:
        total = sum((ln.debit for ln in entry.lines), Decimal(0))
        return Transaction(entry, "UNDO", total, None, None)
    if len(entry.lines) == 2:
        debit = next((ln for ln in entry.lines if ln.debit), None)
        credit = next((ln for ln in entry.lines if ln.credit), None)
        if debit is not None and credit is not None:
            dt, ct = types.get(debit.account_id), types.get(credit.account_id)
            amount = debit.debit
            if OPENING_EQUITY in (codes.get(debit.account_id), codes.get(credit.account_id)):
                money = credit if ct in MONEY else debit
                return Transaction(entry, "OPENING", amount, money.account_id, None)
            if dt == "EXPENSE" and ct in MONEY:
                return Transaction(entry, SPENT, amount, credit.account_id, debit.account_id)
            if dt in MONEY and ct == "INCOME":
                return Transaction(entry, RECEIVED, amount, debit.account_id, credit.account_id)
            if dt in MONEY and ct in MONEY:
                return Transaction(entry, MOVED, amount, credit.account_id, debit.account_id)
    total = sum((ln.debit for ln in entry.lines), Decimal(0))
    return Transaction(entry, "OTHER", total, None, None)


def transactions(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    date_from: date,
    date_to: date,
    account_id: UUID | None = None,
) -> list[Transaction]:
    entity = _entity(ctx, entity_id, READ)
    every = account_list(ctx, entity)
    types = {a.id: a.type for a in every}
    codes = {a.id: a.code for a in every}
    found = [
        _classify(e, types, codes)
        for e in posted_entries(ctx, entity, date_from=date_from, date_to=date_to, limit=500)
    ]
    if account_id is not None:
        found = [t for t in found if any(ln.account_id == account_id for ln in t.entry.lines)]
    return found


# --- valuations and net worth ---------------------------------------------------------------------


@transaction.atomic
def set_valuation(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    account_id: UUID,
    day: date,
    value: str,
    note: str = "",
) -> Valuation:
    """What an asset is worth at a date (nature EXPECTED). A new value for the same date
    supersedes the earlier one, which is kept."""
    entity = _entity(ctx, entity_id, WRITE)
    asset = _account(ctx, entity, account_id, ("ASSET",), "account_id")
    amount = _amount(value, "value", allow_zero=True)
    note = note.strip()
    if len(note) > 300:
        raise _invalid("note", "Keep the note to 300 characters.")
    previous = (
        Valuation.objects.select_for_update()
        .filter(
            legal_entity_id=entity, account_id=asset.id, value_date=day, superseded_at__isnull=True
        )
        .first()
    )
    if previous is not None:
        previous.superseded_at = timezone.now()
        previous.save(update_fields=["superseded_at"])
    made = Valuation.objects.create(
        tenant=ctx.tenant,
        legal_entity_id=entity,
        account_id=asset.id,
        value_date=day,
        value=amount,
        note=note,
        created_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="personal.valuation.set",
        subject_type="valuation",
        subject_id=made.id,
        entity_id=entity,
        changes={
            "account": asset.code,
            "date": day.isoformat(),
            "value": f"{amount:.2f}",
            "previous": None if previous is None else f"{previous.value:.2f}",
        },
    )
    return made


def valuations(ctx: WorkspaceContext, entity_id: UUID, account_id: UUID) -> list[Valuation]:
    entity = _entity(ctx, entity_id, READ)
    return list(
        Valuation.objects.filter(legal_entity_id=entity, account_id=account_id).order_by(
            "-value_date", "-created_at"
        )
    )


@dataclass(frozen=True)
class NetWorth:
    as_of: date
    assets: list[AccountView]
    liabilities: list[AccountView]
    total_assets: Decimal
    total_liabilities: Decimal
    net_worth: Decimal
    includes_valuations: bool
    trend: list[tuple[date, Decimal, bool]]  # month end, net worth, includes valuations


def _totals(views: list[AccountView]) -> tuple[Decimal, Decimal, bool]:
    assets = sum((v.amount for v in views if v.account.type == "ASSET"), Decimal(0))
    owed = sum((v.amount for v in views if v.account.type == "LIABILITY"), Decimal(0))
    return assets, owed, any(v.valuation is not None for v in views)


def net_worth(ctx: WorkspaceContext, entity_id: UUID, as_of: date) -> NetWorth:
    views = [v for v in accounts(ctx, entity_id, as_of) if v.account.type in MONEY]
    assets, owed, valued = _totals(views)
    trend = []
    for i in range(11, -1, -1):
        end = month_end(add_months(month_start(as_of), -i))
        end = min(end, as_of)
        a, o, v = _totals([x for x in accounts(ctx, entity_id, end) if x.account.type in MONEY])
        trend.append((end, a - o, v))
    return NetWorth(
        as_of,
        [v for v in views if v.account.type == "ASSET"],
        [v for v in views if v.account.type == "LIABILITY"],
        assets,
        owed,
        assets - owed,
        valued,
        trend,
    )


@dataclass(frozen=True)
class Spending:
    date_from: date
    date_to: date
    income: list[tuple[Account, Decimal]]
    spending: list[tuple[Account, Decimal]]
    total_income: Decimal
    total_spending: Decimal


def spending(ctx: WorkspaceContext, entity_id: UUID, *, date_from: date, date_to: date) -> Spending:
    """Income and spending by category in a period (posted entries only)."""
    entity = _entity(ctx, entity_id, READ)
    if date_to < date_from:
        raise _invalid("date_to", "The end is before the start.")
    by_type: dict[str, list[tuple[Account, Decimal]]] = defaultdict(list)
    known = {a.id: a for a in account_list(ctx, entity)}
    for row in trial_balance_rows(ctx, entity, as_of=date_to, date_from=date_from):
        account = known.get(row.account_id)
        if account is not None and account.type in CATEGORY and row.balance:
            by_type[account.type].append((account, row.balance))
    income = sorted(by_type["INCOME"], key=lambda x: -x[1])
    spent = sorted(by_type["EXPENSE"], key=lambda x: -x[1])
    return Spending(
        date_from,
        date_to,
        income,
        spent,
        sum((x[1] for x in income), Decimal(0)),
        sum((x[1] for x in spent), Decimal(0)),
    )
