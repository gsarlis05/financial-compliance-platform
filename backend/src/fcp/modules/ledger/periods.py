"""Fiscal years and periods (backlog M1-7; locking and unlock workflow in M1-9).

Status rules (doc 05 §5):
- OPEN -> SOFT_CLOSED (ledger.period.manage), SOFT_CLOSED -> OPEN (ledger.period.manage)
- OPEN or SOFT_CLOSED -> LOCKED (ledger.period.lock)
- LOCKED -> anything else only through the dual-approved unlock workflow (M1-9)
"""

import calendar
from datetime import date, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import FiscalYear, Period

_TRANSITIONS: dict[tuple[str, str], str] = {
    (Period.Status.OPEN, Period.Status.SOFT_CLOSED): "ledger.period.manage",
    (Period.Status.SOFT_CLOSED, Period.Status.OPEN): "ledger.period.manage",
    (Period.Status.OPEN, Period.Status.LOCKED): "ledger.period.lock",
    (Period.Status.SOFT_CLOSED, Period.Status.LOCKED): "ledger.period.lock",
}


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    return date(day.year + index // 12, index % 12 + 1, 1)


@transaction.atomic
def create_fiscal_year(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    start_date: date,
    months: int = 12,
    adjustment_period: bool = True,
    name: str | None = None,
) -> FiscalYear:
    """Create a fiscal year of monthly periods, plus an optional adjustment period (13) dated
    on the year-end for audit and closing adjustments."""
    entity = get_entity(ctx, entity_id, "ledger.period.manage")
    if start_date.day != 1:
        raise ValidationFailedError(
            "A fiscal year starts on the first day of a month.",
            field_errors={"start_date": ["must be the 1st of a month"]},
        )
    if not 1 <= months <= 18:
        raise ValidationFailedError(
            "A fiscal year has between 1 and 18 months (first or transitional years may differ).",
            field_errors={"months": ["out of range"]},
        )
    end_date = _month_end(_add_months(start_date, months - 1))
    label = name or (str(start_date.year) if start_date.month == 1 else f"{start_date:%Y-%m}")
    try:
        with transaction.atomic():
            year = FiscalYear.objects.create(
                tenant=ctx.tenant, legal_entity=entity, name=label, start_date=start_date,
                end_date=end_date, created_by=ctx.user,
            )  # fmt: skip
    except IntegrityError as exc:
        if "ledger_fiscal_year_no_overlap" in str(exc):
            raise ConflictError("This fiscal year overlaps an existing one.") from None
        raise
    for n in range(months):
        month_start = _add_months(start_date, n)
        Period.objects.create(
            tenant=ctx.tenant, legal_entity=entity, fiscal_year=year, number=n + 1,
            start_date=month_start, end_date=_month_end(month_start),
        )  # fmt: skip
    if adjustment_period:
        Period.objects.create(
            tenant=ctx.tenant, legal_entity=entity, fiscal_year=year, number=months + 1,
            start_date=end_date, end_date=end_date, is_adjustment=True,
        )  # fmt: skip
    audit(
        tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="ledger.fiscal_year.created",
        subject_type="fiscal_year", subject_id=year.id, entity_id=entity.id,
        changes={"name": label, "start_date": start_date, "end_date": end_date,
                 "months": months, "adjustment_period": adjustment_period},
    )  # fmt: skip
    return year


def list_fiscal_years(ctx: WorkspaceContext, entity_id: UUID) -> list[FiscalYear]:
    entity = get_entity(ctx, entity_id, "ledger.period.read")
    return list(
        FiscalYear.objects.filter(legal_entity=entity)
        .prefetch_related("periods")
        .order_by("start_date")
    )


def get_period(ctx: WorkspaceContext, entity_id: UUID, period_id: UUID) -> Period:
    entity = get_entity(ctx, entity_id, "ledger.period.read")
    period: Period | None = Period.objects.filter(legal_entity=entity, id=period_id).first()
    if period is None:
        raise NotFoundError("Period not found.")
    return period


def period_for_date(entity_id: UUID, day: date, *, adjustment: bool = False) -> Period | None:
    """The regular (or adjustment) period containing ``day`` (current RLS context)."""
    return (
        Period.objects.filter(
            legal_entity_id=entity_id,
            start_date__lte=day,
            end_date__gte=day,
            is_adjustment=adjustment,
        )
        .select_related("fiscal_year")
        .first()
    )


@transaction.atomic
def change_status(
    ctx: WorkspaceContext, entity_id: UUID, period_id: UUID, new_status: str
) -> Period:
    get_entity(ctx, entity_id, "ledger.period.read")
    period = (
        Period.objects.select_for_update().filter(legal_entity_id=entity_id, id=period_id).first()
    )
    if period is None:
        raise NotFoundError("Period not found.")
    if new_status == period.status:
        return period
    permission = _TRANSITIONS.get((period.status, new_status))
    if permission is None:
        if period.status == Period.Status.LOCKED:
            raise ConflictError(
                "This period is locked. Request an unlock, which needs two approvers."
            )
        raise ValidationFailedError(
            f"A period cannot move from {period.status} to {new_status}.",
            field_errors={"status": ["invalid transition"]},
        )
    ctx.authorize(permission, entity_id)
    before = period.status
    period.status = new_status
    period.status_changed_at = timezone.now()
    period.status_changed_by = ctx.user
    period.save(update_fields=["status", "status_changed_at", "status_changed_by"])
    audit(
        tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="ledger.period.status_changed",
        subject_type="period", subject_id=period.id, entity_id=entity_id,
        changes={"from": before, "to": new_status, "number": period.number,
                 "fiscal_year_id": period.fiscal_year_id},
    )  # fmt: skip
    return period


def first_open_period_on_or_after(entity_id: UUID, day: date) -> Period | None:
    return (
        Period.objects.filter(
            legal_entity_id=entity_id,
            is_adjustment=False,
            status=Period.Status.OPEN,
            end_date__gte=day,
        )
        .order_by("start_date")
        .first()
    )


def next_day(day: date) -> date:
    return day + timedelta(days=1)
