"""Preparing, running and reading the 13-week cash forecast; settings and manual items (M3-7).

``prepare`` collects every input except the ledger balances into the run's references (a
snapshot):
- open receivables, dated at their due date plus the customer's days late (M3-6);
- open payables, dated by the payables policy;
- recurring obligation, loan and tax flows (M3-4, M3-5) with their version IDs;
- manual items, facility limits and settings;
- data-quality warnings.

Re-running a run therefore sees exactly what it saw, whatever changes later (doc 10 P4, ADR-0017).

Choices made here (doc 10 §3.2):
- Receivables and payables are COMMITTED; their dates are expected.
- Disputed open items are left out, with a warning.
- Obligation and loan payments dated before the as-of date are taken as already paid.
- Unpaid tax payments that are overdue stay in, in the first week, flagged.
- Manual items dated before the as-of date are left out, with a warning.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.banking.api import reconciliation_status
from fcp.modules.calendar.api import weekly_buckets
from fcp.modules.metrics.api import (
    CalcRun,
    calc_results,
    current_mapping,
    execute,
    get_calc_run,
    list_calc_runs,
)
from fcp.modules.registers.api import (
    commitment_flows_between,
    facilities,
    open_items,
    payment_behaviour,
)
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .engine import KIND
from .models import ForecastSettings, ManualCashItem

ZERO = Decimal(0)
CASH_LINE = "BS.CASH"
MANAGE = "planning.run"
MANUAL_CATEGORIES = (
    "CUSTOMERS",
    "SUPPLIERS",
    "PAYROLL",
    "RENT",
    "TAX",
    "FINANCING",
    "CAPEX",
    "GRANT",
    "OTHER",
)


def _audit(
    ctx: WorkspaceContext,
    entity_id: UUID,
    subject_type: str,
    subject_id: object,
    action: str,
    changes: dict[str, Any],
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        entity_id=entity_id,
        changes=changes,
    )


# --- settings and manual items --------------------------------------------------------------------


@dataclass(frozen=True)
class SettingsView:
    minimum_cash: Decimal = ZERO
    unreconciled_warning_days: int = 7
    payables_policy: str = ForecastSettings.PayablesPolicy.DUE_DATE
    payables_weekday: int = 4


def get_settings(ctx: WorkspaceContext, entity_id: UUID) -> SettingsView:
    entity = get_entity(ctx, entity_id, "planning.read")
    found = ForecastSettings.objects.filter(legal_entity=entity).first()
    if found is None:
        return SettingsView()
    return SettingsView(
        found.minimum_cash,
        found.unreconciled_warning_days,
        found.payables_policy,
        found.payables_weekday,
    )


@transaction.atomic
def save_settings(ctx: WorkspaceContext, entity_id: UUID, data: SettingsView) -> SettingsView:
    entity = get_entity(ctx, entity_id, MANAGE)
    if data.minimum_cash < 0 or data.minimum_cash != data.minimum_cash.quantize(Decimal("0.01")):
        raise ValidationFailedError(
            "The minimum cash is zero or more, in cents.",
            field_errors={"minimum_cash": ["invalid"]},
        )
    if data.payables_policy not in ForecastSettings.PayablesPolicy.values:
        raise ValidationFailedError(
            "Unknown payables policy.", field_errors={"payables_policy": ["invalid"]}
        )
    ForecastSettings.objects.update_or_create(
        legal_entity=entity,
        defaults={
            "tenant": ctx.tenant,
            "minimum_cash": data.minimum_cash,
            "unreconciled_warning_days": data.unreconciled_warning_days,
            "payables_policy": data.payables_policy,
            "payables_weekday": data.payables_weekday,
            "updated_by": ctx.user,
        },
    )
    _audit(
        ctx,
        entity.id,
        "cash_forecast_settings",
        entity.id,
        "cashflow.settings.saved",
        {
            "minimum_cash": str(data.minimum_cash),
            "unreconciled_warning_days": data.unreconciled_warning_days,
            "payables_policy": data.payables_policy,
            "payables_weekday": data.payables_weekday,
        },
    )
    return get_settings(ctx, entity.id)


def manual_items(ctx: WorkspaceContext, entity_id: UUID) -> list[ManualCashItem]:
    entity = get_entity(ctx, entity_id, "planning.read")
    return list(ManualCashItem.objects.filter(legal_entity=entity).order_by("day", "id"))


@transaction.atomic
def add_manual_item(
    ctx: WorkspaceContext, entity_id: UUID, day: date, amount: Decimal, category: str, reason: str
) -> ManualCashItem:
    entity = get_entity(ctx, entity_id, MANAGE)
    if not amount or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailedError(
            "The amount is not zero, in cents (receipts positive).",
            field_errors={"amount": ["invalid"]},
        )
    if category not in MANUAL_CATEGORIES:
        raise ValidationFailedError("Unknown category.", field_errors={"category": ["invalid"]})
    if not reason.strip():
        raise ValidationFailedError(
            "Give the reason for a manual item.", field_errors={"reason": ["required"]}
        )
    item = ManualCashItem.objects.create(
        tenant=ctx.tenant,
        legal_entity=entity,
        day=day,
        amount=amount,
        category=category,
        reason=reason.strip(),
        created_by=ctx.user,
    )
    _audit(
        ctx,
        entity.id,
        "cash_manual_item",
        item.id,
        "cashflow.manual_item.added",
        {
            "day": day.isoformat(),
            "amount": str(amount),
            "category": category,
            "reason": item.reason,
        },
    )
    return item


@transaction.atomic
def remove_manual_item(ctx: WorkspaceContext, entity_id: UUID, item_id: UUID) -> None:
    entity = get_entity(ctx, entity_id, MANAGE)
    item = ManualCashItem.objects.filter(legal_entity=entity, id=item_id).first()
    if item is None:
        raise NotFoundError("Manual item not found.")
    _audit(
        ctx,
        entity.id,
        "cash_manual_item",
        item.id,
        "cashflow.manual_item.removed",
        {"day": item.day.isoformat(), "amount": str(item.amount), "reason": item.reason},
    )
    item.delete()


# --- preparing the inputs -------------------------------------------------------------------------


def payables_date(due: date, settings: SettingsView) -> date:
    """When a supplier invoice is paid: on its due date, or on the last payment weekday on or
    before it."""
    if settings.payables_policy == ForecastSettings.PayablesPolicy.WEEKDAY:
        return due - timedelta(days=(due.weekday() - settings.payables_weekday) % 7)
    return due


def _flow(  # noqa: PLR0913 (one argument per field)
    day: date,
    amount: Decimal,
    nature: str,
    category: str,
    source: str,
    ref: str,
    *,
    party: str = "",
) -> dict[str, str]:
    """One flow as stored in a run's inputs; ``party`` is the customer or supplier code."""
    flow = {
        "day": day.isoformat(),
        "amount": f"{amount:.2f}",
        "nature": nature,
        "category": category,
        "source": source,
        "ref": ref,
    }
    if party:
        flow["party"] = party
    return flow


def _cash_accounts(entity_id: UUID, warnings: list[dict[str, Any]]) -> list[str]:
    cash = sorted(
        str(a) for a, line in current_mapping(entity_id).items() if line.code == CASH_LINE
    )
    if not cash:
        warnings.append(
            {
                "code": "no_cash_accounts",
                "message": "No account is mapped to cash (BS.CASH): the opening cash is 0.",
            }
        )
    return cash


def _reconciliation_warnings(
    ctx: WorkspaceContext, entity_id: UUID, as_of: date, settings: SettingsView
) -> list[dict[str, Any]]:
    warnings = []
    for bank in reconciliation_status(ctx, entity_id):
        last = bank.last_reconciled
        days = None if last is None else (as_of - last).days
        if days is None or days > settings.unreconciled_warning_days:
            when = (
                "never reconciled"
                if days is None
                else (f"last reconciled {days} days before the as-of date")
            )
            warnings.append(
                {
                    "code": "unreconciled",
                    "account": bank.name,
                    "last_reconciled": last.isoformat() if last else None,
                    "message": f"{bank.name}: {when}",
                }
            )
    return warnings


def _open_item_flows(
    ctx: WorkspaceContext,
    entity_id: UUID,
    as_of: date,
    settings: SettingsView,
    days_late: dict[UUID, int],
    warnings: list[dict[str, Any]],
) -> list[dict[str, str]]:
    flows = []
    disputed: dict[str, list[Decimal]] = {"RECEIVABLE": [], "PAYABLE": []}
    for item in open_items(ctx, entity_id, as_of=as_of):
        if item.kind != "INVOICE" or item.open_amount <= 0:
            continue  # unapplied payments are cash already received or paid
        if item.disputed:
            disputed[item.side].append(item.open_amount)
        elif item.side == "RECEIVABLE":
            day = item.due_date + timedelta(days=days_late.get(item.counterparty_id, 0))
            flows.append(
                _flow(
                    day,
                    item.open_amount,
                    "COMMITTED",
                    "CUSTOMERS",
                    "RECEIVABLE",
                    f"open_item:{item.line_id}",
                    party=item.counterparty_code,
                )
            )
        else:
            flows.append(
                _flow(
                    payables_date(item.due_date, settings),
                    -item.open_amount,
                    "COMMITTED",
                    "SUPPLIERS",
                    "PAYABLE",
                    f"open_item:{item.line_id}",
                    party=item.counterparty_code,
                )
            )
    for side, amounts in disputed.items():
        if amounts:
            total = sum(amounts, ZERO)
            warnings.append(
                {
                    "code": "disputed_excluded",
                    "side": side,
                    "count": len(amounts),
                    "amount": f"{total:.2f}",
                    "message": f"{len(amounts)} disputed {side.lower()} item(s), "
                    f"{total:.2f}, are left out of the forecast.",
                }
            )
    return flows


def _commitment_flows(
    ctx: WorkspaceContext, entity_id: UUID, as_of: date, end: date
) -> list[dict[str, str]]:
    flows = []
    for f in commitment_flows_between(ctx, entity_id, as_of - timedelta(days=365), end):
        if f.source != "TAX" and f.due < as_of:
            continue  # scheduled payments before the as-of date are taken as paid
        if f.source == "DEBT":
            category, ref = f"DEBT_{f.component}", f"debt:{f.version_id}:{f.component.lower()}"
        elif f.source == "TAX":
            category, ref = "TAX", f"tax:{f.version_id}"
        else:
            category, ref = f.category, f"obligation:{f.version_id}"
        flows.append(_flow(f.due, f.amount, f.nature, category, f.source, ref))
    return flows


def _manual_flows(
    ctx: WorkspaceContext, entity_id: UUID, as_of: date, end: date, warnings: list[dict[str, Any]]
) -> list[dict[str, str]]:
    items = manual_items(ctx, entity_id)
    past = [m for m in items if m.day < as_of]
    if past:
        warnings.append(
            {
                "code": "manual_items_past",
                "count": len(past),
                "message": f"{len(past)} manual item(s) are dated before the as-of "
                "date and are left out.",
            }
        )
    return [
        _flow(m.day, m.amount, "EXPECTED", m.category, "MANUAL", f"manual:{m.id}")
        for m in items
        if as_of <= m.day <= end
    ]


def prepare(
    ctx: WorkspaceContext,
    entity_id: UUID,
    as_of: date,
    weeks: int = 13,
    permission: str = MANAGE,
) -> dict[str, Any]:
    """The run's inputs (everything except the ledger balances). ``permission`` is
    ``planning.read`` when only checking whether a forecast is current."""
    entity = get_entity(ctx, entity_id, permission)
    settings = get_settings(ctx, entity.id)
    end = weekly_buckets(as_of, weeks)[-1].end
    warnings: list[dict[str, Any]] = []
    cash = _cash_accounts(entity.id, warnings)
    warnings += _reconciliation_warnings(ctx, entity.id, as_of, settings)
    behaviour = payment_behaviour(ctx, entity.id, as_of)
    flows = _open_item_flows(
        ctx,
        entity.id,
        as_of,
        settings,
        {b.counterparty_id: b.days_late for b in behaviour},
        warnings,
    )
    flows += _commitment_flows(ctx, entity.id, as_of, end)
    flows += _manual_flows(ctx, entity.id, as_of, end, warnings)
    limits = sum((d.facility_limit or ZERO for d in facilities(ctx, entity.id)), ZERO)
    return {
        "weeks": weeks,
        "cash_accounts": cash,
        "minimum_cash": f"{settings.minimum_cash:.2f}",
        "facility_limits": f"{limits:.2f}",
        "settings": {
            "payables_policy": settings.payables_policy,
            "payables_weekday": settings.payables_weekday,
            "unreconciled_warning_days": settings.unreconciled_warning_days,
        },
        "days_late": {b.counterparty_code: b.days_late for b in behaviour},
        "flows": sorted(flows, key=lambda f: (f["day"], f["source"], f["ref"])),
        "warnings": warnings,
    }


def run_forecast(
    ctx: WorkspaceContext,
    entity_id: UUID,
    as_of: date,
    trigger: str = CalcRun.Trigger.USER,
    supersedes: CalcRun | None = None,
) -> CalcRun:
    """Prepare and run the 13-week forecast (a new calculation run)."""
    with transaction.atomic():
        refs = prepare(ctx, entity_id, as_of)
        return execute(
            ctx, entity_id, KIND, as_of=as_of, refs=refs, trigger=trigger, supersedes=supersedes
        )


# --- reading a forecast ---------------------------------------------------------------------------


@dataclass
class Week:
    index: int
    start: date
    end: date
    label: str
    amounts: dict[str, Decimal] = field(default_factory=dict)
    flows: list[tuple[str, str, str, Decimal]] = field(default_factory=list)  # dir, cat, nature


@dataclass(frozen=True)
class Forecast:
    run: CalcRun
    weeks: list[Week]
    opening_accounts: dict[str, Decimal]
    overdue: Decimal
    beyond_horizon: Decimal
    first_shortfall: tuple[date, Decimal] | None
    warnings: list[dict[str, Any]]


def forecast_of(run: CalcRun) -> Forecast:
    if run.kind != KIND:
        raise NotFoundError("Not a cash forecast.")
    weeks: dict[date, Week] = {}
    accounts: dict[str, Decimal] = {}
    overdue = beyond = ZERO
    first: tuple[date, Decimal] | None = None
    for r in calc_results(run):
        value = r.value if r.value is not None else ZERO
        if r.granularity == "WEEK":
            week = weeks.setdefault(r.period_start, Week(0, r.period_start, r.period_end, ""))
            if r.series_key == "cash.flow":
                week.flows.append((r.dimensions[0], r.dimensions[1], r.nature, value))
            else:
                week.amounts[r.series_key.removeprefix("cash.")] = value
        elif r.series_key == "cash.opening_account":
            accounts[r.dimensions[0]] = value
        elif r.series_key == "cash.overdue":
            overdue = value
        elif r.series_key == "cash.beyond_horizon":
            beyond = value
        elif r.series_key == "cash.first_shortfall":
            first = (r.period_start, value)
    ordered = [weeks[k] for k in sorted(weeks)]
    for i, w in enumerate(ordered, start=1):
        w.index = i
        w.label = f"{w.start.isocalendar()[0]}-W{w.start.isocalendar()[1]:02d}"
    return Forecast(
        run, ordered, accounts, overdue, beyond, first, list(run.input_refs.get("warnings", []))
    )


def latest(ctx: WorkspaceContext, entity_id: UUID) -> Forecast:
    runs = [
        r for r in list_calc_runs(ctx, entity_id, KIND, 20) if r.status != CalcRun.Status.FAILED
    ]
    if not runs:
        raise NotFoundError("No cash forecast yet: run one first.")
    return forecast_of(runs[0])


def forecast(ctx: WorkspaceContext, entity_id: UUID, run_id: UUID) -> Forecast:
    return forecast_of(get_calc_run(ctx, entity_id, run_id))
