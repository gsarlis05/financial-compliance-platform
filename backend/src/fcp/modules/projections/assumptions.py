"""Assumption sets (M6-2, brief §3).

A set has one value per driver per month of its horizon (the 12, 24 or 36 months after the
cut-over). It starts from one of:
- **last year's actuals:** revenue and operating costs repeat the same month of the 12 months up to
  the cut-over (revenue grown by an optional % a year); gross margin, DSO, DIO, DPO, the effective
  tax rate and the interest rate as observed over those 12 months and at the cut-over;
- **the approved budget:** revenue and operating costs from the current approved annual budget for
  the months it covers (actuals as above for the others); ratios as from actuals;
- **empty:** zeros, and a 60-month life for new capital expenditure.

Each value records its source. Drafts can be edited; an approved set never changes, and a revision
is a new version of the same family (database triggers).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.budgeting.api import approved_plan
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.metrics.api import current_mapping
from fcp.modules.reporting.api import actuals_monthly, opening_net
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .drivers import DEFAULT_CAPEX_LIFE, DRIVERS, OPEX_LINES, REVENUE_LINES, Unit
from .models import AssumptionSet, AssumptionValue

READ, RUN, PUBLISH = "planning.read", "planning.run", "planning.publish"
CENT, PLACES = Decimal("0.01"), Decimal("0.0001")
HUNDRED, DAYS_A_YEAR = Decimal(100), Decimal(365)
LIMITS: dict[Unit, tuple[Decimal, Decimal]] = {
    Unit.AMOUNT: (Decimal(0), Decimal("1e12")),
    Unit.PERCENT: (Decimal(-1000), Decimal(1000)),
    Unit.DAYS: (Decimal(0), Decimal(3650)),
    Unit.MONTHS: (Decimal(1), Decimal(1200)),
}
Source = AssumptionValue.Source


def _invalid(name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={name: [message]})


def horizon(cutover: date, months: int) -> list[date]:
    first = add_months(month_start(cutover), 1)
    return [add_months(first, n) for n in range(months)]


# --- what last year looked like ----------------------------------------------------------------


@dataclass(frozen=True)
class History:
    """The 12 months up to the cut-over, by taxonomy line, in each line's natural direction, and
    the balance-sheet lines at the cut-over (net debit)."""

    months: list[date]
    pl: dict[str, dict[date, Decimal]]
    balances: dict[str, Decimal]


def history(ctx: WorkspaceContext, entity: UUID, cutover: date) -> History:
    months = [add_months(month_start(cutover), -n) for n in range(11, -1, -1)]
    mapping = current_mapping(entity)
    facts = actuals_monthly(ctx, entity, date_from=months[0], date_to=cutover).facts
    pl: dict[str, dict[date, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for fact in facts:
        line = mapping.get(fact.account_id)
        if line is None or line.statement != "PL":
            continue
        income = line.code.startswith(("REV.", "INT.INCOME"))
        pl[line.code][fact.period] += -fact.net_debit if income else fact.net_debit
    _, net = opening_net(ctx, entity, before=cutover + timedelta(days=1))
    balances: dict[str, Decimal] = defaultdict(Decimal)
    for account_id, amount in net.items():
        line = mapping.get(account_id)
        if line is not None and line.statement == "BS":
            balances[line.code] += amount
    return History(months, pl, balances)


def _total(h: History, *codes: str) -> Decimal:
    return sum((v for c in codes for v in h.pl.get(c, {}).values()), Decimal(0))


def _ratio(numerator: Decimal, denominator: Decimal, scale: Decimal) -> Decimal:
    return (numerator / denominator * scale).quantize(PLACES) if denominator else Decimal(0)


def observed(h: History) -> dict[str, Decimal]:
    """Ratios from the 12 months up to the cut-over (0 where they cannot be worked out)."""
    sales = _total(h, "REV.SALES", "REV.SERVICES")
    cogs = _total(h, "COGS")
    revenue = _total(h, *REVENUE_LINES)
    profit = revenue - cogs - _total(h, *OPEX_LINES, "DA.DEPRECIATION", "DA.AMORTISATION") \
        + _total(h, "INT.INCOME") - _total(h, "INT.EXPENSE", "FX.DIFF")  # fmt: skip
    debt = -(h.balances.get("BS.DEBT.NONCURRENT", Decimal(0))
             + h.balances.get("BS.DEBT.CURRENT", Decimal(0)))  # fmt: skip
    tax = _ratio(_total(h, "TAX.INCOME"), profit, HUNDRED) if profit > 0 else Decimal(0)
    return {
        "gross_margin": _ratio(sales - cogs, sales, HUNDRED),
        "dso": _ratio(h.balances.get("BS.AR", Decimal(0)), revenue, DAYS_A_YEAR),
        "dio": _ratio(h.balances.get("BS.INVENTORY", Decimal(0)), cogs, DAYS_A_YEAR),
        "dpo": _ratio(-h.balances.get("BS.AP", Decimal(0)), cogs, DAYS_A_YEAR),
        "tax_rate": min(max(tax, Decimal(0)), HUNDRED),
        "interest_rate": _ratio(_total(h, "INT.EXPENSE"), debt, HUNDRED)
        if debt > 0
        else Decimal(0),
    }


# --- starting a set ------------------------------------------------------------------------------


@dataclass(frozen=True)
class NewSet:
    name: str
    cutover: date
    months: int
    start_from: str
    revenue_growth: str = "0"  # % a year, actuals start only


def _clean(value: Decimal, unit: Unit) -> Decimal:
    return value.quantize(CENT if unit == Unit.AMOUNT else PLACES)


def _budget(
    ctx: WorkspaceContext, entity: UUID, months: list[date]
) -> dict[str, dict[date, Decimal]]:
    """The current approved budget by taxonomy line and month (empty if there is none)."""
    plan = approved_plan(ctx, entity, months)
    found: dict[str, dict[date, Decimal]] = defaultdict(dict)
    if plan is None:
        return found
    mapping = current_mapping(entity)
    for subject, by_month in plan.amounts.items():
        kind, _, ref = subject.partition(":")
        code = ref if kind == "line" else getattr(mapping.get(UUID(ref)), "code", "")
        for iso, amount in by_month.items():
            day = date.fromisoformat(iso)
            found[code][day] = found[code].get(day, Decimal(0)) + Decimal(amount)
    return found


Row = tuple[str, str, date, Decimal, str]  # driver, line, month, value, source


def _empty(months: list[date]) -> list[Row]:
    values: list[Row] = []
    for key, driver in DRIVERS.items():
        default = Decimal(DEFAULT_CAPEX_LIFE) if key == "capex_life" else Decimal(0)
        for line in driver.lines:
            values += [(key, line, m, default, Source.DEFAULT) for m in months]
    return values


def _month(
    *, h: History, budget: dict[str, dict[date, Decimal]], ratios: dict[str, Decimal],
    month: date, n: int, growth: Decimal,
) -> list[Row]:  # fmt: skip
    """One month of a set started from actuals (and the budget where it covers the month)."""
    values: list[Row] = []
    base = h.months[n % 12]
    for key, lines in (("revenue", REVENUE_LINES), ("opex", OPEX_LINES)):
        for line in lines:
            if month in budget.get(line, {}):
                values.append((key, line, month, budget[line][month], Source.BUDGET))
                continue
            amount = h.pl.get(line, {}).get(base, Decimal(0))
            if key == "revenue":
                amount *= (1 + growth / HUNDRED) ** (n // 12 + 1)
            values.append((key, line, month, max(amount, Decimal(0)), Source.ACTUALS))
    sales = sum((budget.get(c, {}).get(month, Decimal(0)) for c in ("REV.SALES", "REV.SERVICES")),
                Decimal(0))  # fmt: skip
    cogs = budget.get("COGS", {}).get(month)
    if sales and cogs is not None:
        values.append(("gross_margin", "", month, _ratio(sales - cogs, sales, HUNDRED),
                       Source.BUDGET))  # fmt: skip
    else:
        values.append(("gross_margin", "", month, ratios["gross_margin"], Source.ACTUALS))
    for key in ("dso", "dio", "dpo", "tax_rate", "interest_rate"):
        values.append((key, "", month, ratios[key], Source.ACTUALS))
    values.append(("capex_life", "", month, Decimal(DEFAULT_CAPEX_LIFE), Source.DEFAULT))
    for key in ("capex", "borrowing", "repayment", "dividends", "share_capital",
                "minimum_cash", "revolver_limit", "revolver_rate"):  # fmt: skip
        values.append((key, "", month, Decimal(0), Source.DEFAULT))
    return values


def _starting_values(
    ctx: WorkspaceContext, entity: UUID, data: NewSet, growth: Decimal
) -> tuple[list[Row], str]:
    months = horizon(data.cutover, data.months)
    if data.start_from == AssumptionSet.StartFrom.EMPTY:
        return _empty(months), "Started empty."
    h = history(ctx, entity, data.cutover)
    budget = _budget(ctx, entity, months) if data.start_from == "BUDGET" else {}
    if data.start_from == "BUDGET" and not budget:
        raise _invalid("start_from", "There is no approved budget for these months.")
    ratios = observed(h)
    values: list[Row] = []
    for n, month in enumerate(months):
        values += _month(h=h, budget=budget, ratios=ratios, month=month, n=n, growth=growth)
    note = f"Started from the 12 months to {data.cutover:%d/%m/%Y}"
    if growth:
        note += f", revenue {growth}% a year"
    if budget:
        note += " and the approved budget for the months it covers"
    return values, note + "."


@transaction.atomic
def create_set(ctx: WorkspaceContext, entity_id: UUID, data: NewSet) -> AssumptionSet:
    entity = get_entity(ctx, entity_id, RUN).id
    name = data.name.strip()
    if not name or len(name) > 120:
        raise _invalid("name", "Give the set a name of 1 to 120 characters.")
    if data.months not in (12, 24, 36):
        raise _invalid("months", "Choose a horizon of 12, 24 or 36 months.")
    if data.start_from not in AssumptionSet.StartFrom.values:
        raise _invalid("start_from", "Start from actuals, the budget, or empty.")
    if data.cutover != month_end(data.cutover):
        raise _invalid("cutover", "The cut-over is the last day of a month.")
    try:
        growth = Decimal(data.revenue_growth or "0")
    except InvalidOperation:
        growth = Decimal("NaN")
    if not growth.is_finite() or not Decimal(-100) < growth <= Decimal(1000):
        raise _invalid("revenue_growth", "Enter a growth between -100% and 1000% a year.")
    values, note = _starting_values(ctx, entity, data, growth)
    made = AssumptionSet.objects.create(
        tenant=ctx.tenant, legal_entity_id=entity, name=name, cutover=data.cutover,
        months=data.months, start_from=data.start_from, note=note, created_by=ctx.user,
    )  # fmt: skip
    AssumptionValue.objects.bulk_create(
        AssumptionValue(tenant=ctx.tenant, assumption_set=made, driver=key, line=line, month=month,
                        value=_clean(value, DRIVERS[key].unit), source=source)
        for key, line, month, value, source in values
    )  # fmt: skip
    _audit(ctx, "created", made, start_from=made.start_from, months=made.months,
           cutover=made.cutover.isoformat())  # fmt: skip
    return made


def _audit(ctx: WorkspaceContext, action: str, made: AssumptionSet, **changes: object) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=f"projections.assumptions.{action}",
        subject_type="assumption_set",
        subject_id=made.id,
        entity_id=made.legal_entity_id,
        changes={"name": made.name, "version": made.version, **changes},
    )


# --- reading and editing -------------------------------------------------------------------------


def _set(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID, permission: str) -> AssumptionSet:
    entity = get_entity(ctx, entity_id, permission).id
    found = AssumptionSet.objects.filter(legal_entity_id=entity, id=set_id).first()
    if found is None:
        raise NotFoundError("Assumption set not found.")
    return found


def sets(ctx: WorkspaceContext, entity_id: UUID) -> list[AssumptionSet]:
    entity = get_entity(ctx, entity_id, READ).id
    return list(
        AssumptionSet.objects.filter(legal_entity_id=entity).order_by("-created_at", "-version")
    )


@dataclass(frozen=True)
class Grid:
    assumption_set: AssumptionSet
    months: list[date]
    rows: list[
        tuple[str, str, Unit, list[Decimal], list[str]]
    ]  # driver, line, unit, values, sources


def grid(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> Grid:
    made = _set(ctx, entity_id, set_id, READ)
    months = horizon(made.cutover, made.months)
    index = {m: i for i, m in enumerate(months)}
    found: dict[tuple[str, str], tuple[list[Decimal], list[str]]] = {}
    for key, driver in DRIVERS.items():
        for line in driver.lines:
            found[(key, line)] = ([Decimal(0)] * len(months), [Source.DEFAULT] * len(months))
    for v in AssumptionValue.objects.filter(assumption_set=made):
        row = found.get((v.driver, v.line))
        if row is not None and v.month in index:
            row[0][index[v.month]] = v.value
            row[1][index[v.month]] = v.source
    rows = [(k, line, DRIVERS[k].unit, vals, srcs) for (k, line), (vals, srcs) in found.items()]
    return Grid(made, months, rows)


@dataclass(frozen=True)
class Change:
    driver: str
    line: str
    month: date
    value: str


@transaction.atomic
def set_values(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID, changes: list[Change]) -> int:
    made = _set(ctx, entity_id, set_id, RUN)
    if made.status != AssumptionSet.Status.DRAFT:
        raise ConflictError("This set is approved and never changes. Revise it as a new version.")
    months = set(horizon(made.cutover, made.months))
    for n, change in enumerate(changes):
        driver = DRIVERS.get(change.driver)
        where = f"changes[{n}]"
        cell = " ".join(p for p in (change.driver, change.line) if p) + f", {change.month:%m/%Y}"
        if driver is None or change.line not in driver.lines:
            raise _invalid(where, f"{cell}: unknown driver or line.")
        if month_start(change.month) not in months:
            raise _invalid(where, f"{cell}: the month is outside the set's horizon.")
        try:
            value = Decimal(change.value)
        except InvalidOperation:
            raise _invalid(where, f"{cell}: enter a number.") from None
        low, high = LIMITS[driver.unit]
        if driver.minimum is not None:
            low = max(low, Decimal(driver.minimum))
        if not value.is_finite() or not low <= value <= high:
            raise _invalid(where, f"{cell}: enter a value between {low} and {high}.")
        AssumptionValue.objects.update_or_create(
            assumption_set=made, driver=change.driver, line=change.line,
            month=month_start(change.month),
            defaults={"tenant": ctx.tenant, "value": _clean(value, driver.unit),
                      "source": Source.MANUAL},
        )  # fmt: skip
    _audit(ctx, "edited", made, values=len(changes))
    return len(changes)


@transaction.atomic
def rename(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID, name: str) -> AssumptionSet:
    made = _set(ctx, entity_id, set_id, RUN)
    if made.status != AssumptionSet.Status.DRAFT:
        raise ConflictError("Only a draft can be renamed.")
    clean = name.strip()
    if not clean or len(clean) > 120:
        raise _invalid("name", "Give the set a name of 1 to 120 characters.")
    made.name = clean
    made.save(update_fields=["name"])
    return made


@transaction.atomic
def approve(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> AssumptionSet:
    """Approve a draft (it then never changes); the family's earlier approved version is
    superseded."""
    made = _set(ctx, entity_id, set_id, PUBLISH)
    if made.status != AssumptionSet.Status.DRAFT:
        raise ConflictError("Only a draft can be approved.")
    now = timezone.now()
    for old in AssumptionSet.objects.filter(family_id=made.family_id,
                                            status=AssumptionSet.Status.APPROVED):  # fmt: skip
        old.status, old.superseded_at = AssumptionSet.Status.SUPERSEDED, now
        old.save(update_fields=["status", "superseded_at"])
    made.status, made.approved_by, made.approved_at = AssumptionSet.Status.APPROVED, ctx.user, now
    made.save(update_fields=["status", "approved_by", "approved_at"])
    _audit(ctx, "approved", made)
    return made


@transaction.atomic
def revise(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> AssumptionSet:
    """A new draft version with the same values, to change an approved (or any) set."""
    made = _set(ctx, entity_id, set_id, RUN)
    if AssumptionSet.objects.filter(family_id=made.family_id,
                                    status=AssumptionSet.Status.DRAFT).exists():  # fmt: skip
        raise ConflictError("This set already has a draft version; edit that one.")
    latest = AssumptionSet.objects.filter(family_id=made.family_id).order_by("-version").first()
    number = (latest.version if latest else made.version) + 1
    draft = AssumptionSet.objects.create(
        tenant=ctx.tenant, legal_entity_id=made.legal_entity_id, family_id=made.family_id,
        version=number, name=made.name, cutover=made.cutover, months=made.months,
        start_from=made.start_from, note=f"Revision of version {made.version}. {made.note}"[:500],
        supersedes=made, created_by=ctx.user,
    )  # fmt: skip
    AssumptionValue.objects.bulk_create(
        AssumptionValue(tenant=ctx.tenant, assumption_set=draft, driver=v.driver, line=v.line,
                        month=v.month, value=v.value, source=v.source)
        for v in AssumptionValue.objects.filter(assumption_set=made)
    )  # fmt: skip
    _audit(ctx, "revised", draft, from_version=made.version)
    return draft


def approved_values(
    ctx: WorkspaceContext, entity_id: UUID, set_id: UUID
) -> tuple[AssumptionSet, dict[tuple[str, str], dict[date, Decimal]]]:
    """An approved set's values by (driver, line) and month, for the projection engine (M6-3)."""
    made = _set(ctx, entity_id, set_id, READ)
    if made.status == AssumptionSet.Status.DRAFT:
        raise ConflictError("Approve the assumption set before projecting with it.")
    found: dict[tuple[str, str], dict[date, Decimal]] = defaultdict(dict)
    for v in AssumptionValue.objects.filter(assumption_set=made):
        found[(v.driver, v.line)][v.month] = v.value
    return made, found
