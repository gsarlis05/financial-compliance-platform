"""Recurring obligations, loans, tax payments and holidays, and their dated flows (M3-4, M3-5).

Versions: creating gives version 1 of a new series. A change supersedes the current version and
adds the next one, and retiring supersedes it without a successor, so history is kept and a
forecast can name the exact versions it used. Flows are computed from the versions, never stored:
- an obligation's payments are COMMITTED if contractual, else EXPECTED;
- a loan's principal is COMMITTED;
- its interest is COMMITTED at a fixed rate, and EXPECTED at a variable rate, because the
  reference rate is an assumption.
"""

from dataclasses import dataclass, fields
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.core.ids import uuid7
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import Adjust, BusinessDays
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Counterparty, DebtInstrument, EntityHoliday, RecurringObligation, TaxPayment
from .schedules import (
    DayCount,
    Frequency,
    Instalment,
    Loan,
    Recurrence,
    Repayment,
    ScheduleError,
    loan_schedule,
    occurrences,
)

READ, MANAGE = "registers.commitment.read", "registers.commitment.manage"
FACILITIES = (DebtInstrument.Kind.OVERDRAFT, DebtInstrument.Kind.REVOLVER)
MAX_WINDOW_DAYS = 3 * 366


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


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def _counterparty(entity_id: UUID, counterparty_id: UUID | None, field: str) -> None:
    if (
        counterparty_id is not None
        and not Counterparty.objects.filter(legal_entity_id=entity_id, id=counterparty_id).exists()
    ):
        raise _invalid(field, "Customer or supplier not found in this legal entity.")


# --- inputs ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ObligationInput:
    name: str
    category: str
    direction: str
    amount: Decimal
    frequency: str
    start_date: date
    contractual: bool
    interval: int = 1
    day_of_month: int | None = None
    end_date: date | None = None
    adjust: str = Adjust.NONE
    counterparty_id: UUID | None = None
    note: str = ""

    def recurrence(self) -> Recurrence:
        return Recurrence(
            Frequency(self.frequency),
            self.start_date,
            self.end_date,
            self.interval,
            self.day_of_month,
            Adjust(self.adjust),
        )


@dataclass(frozen=True)
class DebtInput:
    name: str
    kind: str
    start_date: date
    rate_type: str
    day_count: str = DayCount.ACT_365
    principal: Decimal | None = None
    facility_limit: Decimal | None = None
    maturity_date: date | None = None
    payment_frequency_months: int = 1
    fixed_rate: Decimal | None = None
    reference_rate_key: str = ""
    margin: Decimal | None = None
    assumed_reference_rate: Decimal | None = None
    repayment_type: str = ""
    interest_only_periods: int = 0
    adjust: str = Adjust.MODIFIED_FOLLOWING
    lender_id: UUID | None = None
    note: str = ""


def _validate_obligation(entity_id: UUID, data: ObligationInput) -> None:
    if data.category not in RecurringObligation.Category.values:
        raise _invalid("category", "Unknown category.")
    if data.direction not in RecurringObligation.Direction.values:
        raise _invalid("direction", "Unknown direction.")
    if data.amount <= 0 or data.amount != data.amount.quantize(Decimal("0.01")):
        raise _invalid("amount", "The amount is positive, in cents.")
    try:
        data.recurrence().check()
    except (ScheduleError, ValueError) as error:
        raise _invalid("schedule", str(error)) from None
    _counterparty(entity_id, data.counterparty_id, "counterparty_id")


def _loan(data: DebtInput | DebtInstrument) -> Loan:
    principal, maturity = data.principal, data.maturity_date
    assert principal is not None  # noqa: S101 (checked before)
    assert maturity is not None  # noqa: S101 (checked before)
    annual = (
        data.fixed_rate
        if data.rate_type == "FIXED"
        else ((data.assumed_reference_rate or Decimal(0)) + (data.margin or Decimal(0)))
    )
    return Loan(
        principal,
        data.start_date,
        maturity,
        annual or Decimal(0),
        data.payment_frequency_months,
        Repayment(data.repayment_type),
        DayCount(data.day_count),
        data.interest_only_periods,
        Adjust(data.adjust),
    )


def _validate_debt(entity_id: UUID, data: DebtInput) -> None:  # noqa: PLR0912 (one rule per check)
    if data.kind not in DebtInstrument.Kind.values:
        raise _invalid("kind", "Unknown kind.")
    if data.rate_type == DebtInstrument.RateType.FIXED:
        if data.fixed_rate is None:
            raise _invalid("fixed_rate", "A fixed-rate loan needs its rate.")
    elif data.rate_type == DebtInstrument.RateType.VARIABLE:
        if data.margin is None or data.assumed_reference_rate is None:
            raise _invalid(
                "margin", "A variable-rate loan needs its margin and an assumed reference rate."
            )
        if not data.reference_rate_key:
            raise _invalid("reference_rate_key", "Name the reference rate (e.g. EURIBOR_3M).")
    else:
        raise _invalid("rate_type", "Unknown rate type.")
    if data.day_count not in DayCount.__members__.values():
        raise _invalid("day_count", "Unknown day count.")
    _counterparty(entity_id, data.lender_id, "lender_id")
    if data.kind in FACILITIES:
        if data.facility_limit is None or data.facility_limit <= 0:
            raise _invalid("facility_limit", "A facility needs its limit.")
        if data.principal is not None or data.maturity_date is not None or data.repayment_type:
            raise _invalid(
                "principal",
                "A facility has a limit only: no principal, maturity or repayment schedule.",
            )
        return
    if data.principal is None or data.maturity_date is None:
        raise _invalid("principal", "A loan needs its principal and maturity date.")
    if data.repayment_type not in Repayment.__members__.values():
        raise _invalid("repayment_type", "Unknown repayment type.")
    try:
        loan_schedule(_loan(data))
    except (ScheduleError, ValueError) as error:
        raise _invalid("schedule", str(error)) from None


# --- versions -------------------------------------------------------------------------------------


def _current[V: (RecurringObligation, DebtInstrument, TaxPayment)](
    model: type[V], entity_id: UUID, series_id: UUID, *, lock: bool = False
) -> V:
    qs = model.objects.filter(
        legal_entity_id=entity_id, series_id=series_id, superseded_at__isnull=True
    )
    found = (qs.select_for_update() if lock else qs).first()
    if found is None:
        raise NotFoundError("Not found (or retired).")
    return found


def _values(data: object) -> dict[str, Any]:
    return {f.name: getattr(data, f.name) for f in fields(data)}  # type: ignore[arg-type]


def _save_version[V: (RecurringObligation, DebtInstrument, TaxPayment)](
    ctx: WorkspaceContext,
    model: type[V],
    entity_id: UUID,
    values: dict[str, Any],
    series_id: UUID | None,
) -> V:
    version = 1
    if series_id is not None:
        current = _current(model, entity_id, series_id, lock=True)
        current.superseded_at = timezone.now()
        current.save(update_fields=["superseded_at"])
        version = current.version + 1
    try:
        with transaction.atomic():
            return model.objects.create(
                tenant=ctx.tenant,
                legal_entity_id=entity_id,
                series_id=series_id or uuid7(),
                version=version,
                created_by=ctx.user,
                **values,
            )
    except IntegrityError:
        raise ConflictError("This was changed at the same time; reload and try again.") from None


def _log_values(values: dict[str, Any]) -> dict[str, Any]:
    return {k: (str(v) if isinstance(v, (Decimal, date, UUID)) else v) for k, v in values.items()}


@transaction.atomic
def save_obligation(
    ctx: WorkspaceContext, entity_id: UUID, data: ObligationInput, series_id: UUID | None = None
) -> RecurringObligation:
    """Create (``series_id`` None) or change an obligation; a change adds a new version."""
    entity = get_entity(ctx, entity_id, MANAGE)
    _validate_obligation(entity.id, data)
    values = _values(data)
    obligation = _save_version(ctx, RecurringObligation, entity.id, values, series_id)
    _audit(
        ctx,
        entity.id,
        "recurring_obligation",
        obligation.series_id,
        "registers.obligation.saved",
        {"version": obligation.version, **_log_values(values)},
    )
    return obligation


@transaction.atomic
def save_debt(
    ctx: WorkspaceContext, entity_id: UUID, data: DebtInput, series_id: UUID | None = None
) -> DebtInstrument:
    entity = get_entity(ctx, entity_id, MANAGE)
    _validate_debt(entity.id, data)
    values = _values(data)
    debt = _save_version(ctx, DebtInstrument, entity.id, values, series_id)
    _audit(
        ctx,
        entity.id,
        "debt_instrument",
        debt.series_id,
        "registers.debt.saved",
        {"version": debt.version, **_log_values(values)},
    )
    return debt


@dataclass(frozen=True)
class TaxInput:
    kind: str
    period_label: str
    due_date: date
    amount: Decimal
    nature: str
    reference: str = ""
    paid_on: date | None = None
    note: str = ""


def _validate_tax(data: TaxInput) -> None:
    if data.kind not in TaxPayment.Kind.values:
        raise _invalid("kind", "Unknown tax kind.")
    if data.nature not in TaxPayment.Nature.values:
        raise _invalid("nature", "Committed (assessed or returned) or expected (estimated).")
    if data.amount <= 0 or data.amount != data.amount.quantize(Decimal("0.01")):
        raise _invalid("amount", "The amount is positive, in cents.")
    if not data.period_label.strip():
        raise _invalid("period_label", "Name the period, e.g. 2026-Q3.")


@transaction.atomic
def save_tax_payment(
    ctx: WorkspaceContext, entity_id: UUID, data: TaxInput, series_id: UUID | None = None
) -> TaxPayment:
    """Create or change a tax payment (a change, including marking it paid, adds a version)."""
    entity = get_entity(ctx, entity_id, MANAGE)
    _validate_tax(data)
    values = _values(data)
    values["period_label"] = data.period_label.strip()
    payment = _save_version(ctx, TaxPayment, entity.id, values, series_id)
    _audit(
        ctx,
        entity.id,
        "tax_payment",
        payment.series_id,
        "registers.tax_payment.saved",
        {"version": payment.version, **_log_values(values)},
    )
    return payment


@transaction.atomic
def retire[V: (RecurringObligation, DebtInstrument, TaxPayment)](
    ctx: WorkspaceContext, entity_id: UUID, model: type[V], series_id: UUID
) -> V:
    entity = get_entity(ctx, entity_id, MANAGE)
    current = _current(model, entity.id, series_id, lock=True)
    current.superseded_at = timezone.now()
    current.save(update_fields=["superseded_at"])
    _audit(
        ctx,
        entity.id,
        model._meta.db_table.removeprefix("registers_"),
        series_id,
        "registers.commitment.retired",
        {"version": current.version},
    )
    return current


def current_versions[V: (RecurringObligation, DebtInstrument, TaxPayment)](
    ctx: WorkspaceContext, entity_id: UUID, model: type[V]
) -> list[V]:
    entity = get_entity(ctx, entity_id, READ)
    first = "due_date" if model is TaxPayment else "name"
    return list(
        model.objects.filter(legal_entity=entity, superseded_at__isnull=True).order_by(
            first, "series_id"
        )
    )


def history[V: (RecurringObligation, DebtInstrument, TaxPayment)](
    ctx: WorkspaceContext, entity_id: UUID, model: type[V], series_id: UUID
) -> list[V]:
    entity = get_entity(ctx, entity_id, READ)
    versions = list(
        model.objects.filter(legal_entity=entity, series_id=series_id).order_by("version")
    )
    if not versions:
        raise NotFoundError("Not found.")
    return versions


def schedule(ctx: WorkspaceContext, entity_id: UUID, series_id: UUID) -> list[Instalment]:
    """The current version's instalments (a facility has none)."""
    entity = get_entity(ctx, entity_id, READ)
    debt = _current(DebtInstrument, entity.id, series_id)
    if debt.kind in FACILITIES:
        return []
    return loan_schedule(_loan(debt), business_days(ctx, entity.id))


# --- holidays -------------------------------------------------------------------------------------


def holidays(ctx: WorkspaceContext, entity_id: UUID) -> list[EntityHoliday]:
    entity = get_entity(ctx, entity_id, READ)
    return list(EntityHoliday.objects.filter(legal_entity=entity).order_by("day"))


def business_days(ctx: WorkspaceContext, entity_id: UUID) -> BusinessDays:
    return BusinessDays(frozenset(h.day for h in holidays(ctx, entity_id)))


@transaction.atomic
def add_holiday(ctx: WorkspaceContext, entity_id: UUID, day: date, name: str) -> EntityHoliday:
    entity = get_entity(ctx, entity_id, MANAGE)
    if EntityHoliday.objects.filter(legal_entity=entity, day=day).exists():
        raise ConflictError(f"{day.isoformat()} is already a holiday.")
    holiday = EntityHoliday.objects.create(
        tenant=ctx.tenant, legal_entity=entity, day=day, name=name.strip(), created_by=ctx.user
    )
    _audit(
        ctx,
        entity.id,
        "holiday",
        holiday.id,
        "registers.holiday.added",
        {"day": day.isoformat(), "name": holiday.name},
    )
    return holiday


@transaction.atomic
def remove_holiday(ctx: WorkspaceContext, entity_id: UUID, holiday_id: UUID) -> None:
    entity = get_entity(ctx, entity_id, MANAGE)
    holiday = EntityHoliday.objects.filter(legal_entity=entity, id=holiday_id).first()
    if holiday is None:
        raise NotFoundError("Holiday not found.")
    _audit(
        ctx,
        entity.id,
        "holiday",
        holiday.id,
        "registers.holiday.removed",
        {"day": holiday.day.isoformat(), "name": holiday.name},
    )
    holiday.delete()


# --- flows for forecasting ------------------------------------------------------------------------


@dataclass(frozen=True)
class CommitmentFlow:
    """One dated cash flow: inflows positive, outflows negative."""

    due: date
    scheduled: date
    amount: Decimal
    nature: str  # COMMITTED | EXPECTED
    source: str  # OBLIGATION | DEBT | TAX
    component: str  # PAYMENT | PRINCIPAL | INTEREST
    category: str  # obligation category, debt kind or tax kind
    name: str
    series_id: UUID
    version_id: UUID  # the exact version (for lineage and pinning)


def _window(date_from: date, date_to: date) -> None:
    if date_to < date_from or (date_to - date_from).days > MAX_WINDOW_DAYS:
        raise _invalid("date_to", "The period runs forwards and spans at most three years.")


def flows(
    ctx: WorkspaceContext, entity_id: UUID, date_from: date, date_to: date
) -> list[CommitmentFlow]:
    """Every obligation and loan flow due from ``date_from`` to ``date_to`` (current versions),
    in date order."""
    _window(date_from, date_to)
    calendar = business_days(ctx, entity_id)
    found: list[CommitmentFlow] = []
    for o in current_versions(ctx, entity_id, RecurringObligation):
        rule = Recurrence(
            Frequency(o.frequency),
            o.start_date,
            o.end_date,
            o.interval,
            o.day_of_month,
            Adjust(o.adjust),
        )
        sign = 1 if o.direction == RecurringObligation.Direction.INFLOW else -1
        nature = "COMMITTED" if o.contractual else "EXPECTED"
        found += [
            CommitmentFlow(
                x.due,
                x.scheduled,
                sign * o.amount,
                nature,
                "OBLIGATION",
                "PAYMENT",
                o.category,
                o.name,
                o.series_id,
                o.id,
            )
            for x in occurrences(rule, date_from, date_to, calendar)
        ]
    for d in current_versions(ctx, entity_id, DebtInstrument):
        if d.kind in FACILITIES:
            continue
        interest_nature = "COMMITTED" if d.rate_type == "FIXED" else "EXPECTED"
        for row in loan_schedule(_loan(d), calendar):
            if not date_from <= row.due <= date_to:
                continue
            for component, amount, nature in (
                ("PRINCIPAL", row.principal, "COMMITTED"),
                ("INTEREST", row.interest, interest_nature),
            ):
                if amount:
                    found.append(
                        CommitmentFlow(
                            row.due,
                            row.period_end,
                            -amount,
                            nature,
                            "DEBT",
                            component,
                            d.kind,
                            d.name,
                            d.series_id,
                            d.id,
                        )
                    )
    for t in current_versions(ctx, entity_id, TaxPayment):
        if t.paid_on is None and date_from <= t.due_date <= date_to:
            found.append(
                CommitmentFlow(
                    t.due_date,
                    t.due_date,
                    -t.amount,
                    t.nature,
                    "TAX",
                    "PAYMENT",
                    t.kind,
                    f"{t.kind} {t.period_label}",
                    t.series_id,
                    t.id,
                )
            )
    return sorted(found, key=lambda f: (f.due, f.source, f.name, f.component, str(f.version_id)))


def facilities(ctx: WorkspaceContext, entity_id: UUID) -> list[DebtInstrument]:
    """Current overdraft and revolving facilities (their limits count towards liquidity)."""
    return [d for d in current_versions(ctx, entity_id, DebtInstrument) if d.kind in FACILITIES]
