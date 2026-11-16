"""Public interface of the ``registers`` module and its HTTP routes (backlog M2-2; M3-4: recurring
obligations, loans, facilities and holidays).

All routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

import csv
import io
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.core.export import safe_text
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import workspace_ctx

from . import behaviour, commitments, services
from .commitments import CommitmentFlow
from .models import Allocation, Counterparty, DebtInstrument, RecurringObligation, TaxPayment

__all__ = [
    "Behaviour",
    "CommitmentFlow",
    "Counterparty",
    "DebtInstrument",
    "OpenItem",
    "business_days",
    "commitment_flows_between",
    "facilities",
    "open_items",
    "payment_behaviour",
    "router",
]

OpenItem = services.OpenItem
open_items = services.open_items
commitment_flows_between = commitments.flows
facilities = commitments.facilities
business_days = commitments.business_days
Behaviour = behaviour.Behaviour
payment_behaviour = behaviour.payment_behaviour

router = Router(tags=["registers"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
AMOUNT = r"^\d{1,15}(\.\d{1,2})?$"
Side = Literal["RECEIVABLE", "PAYABLE"]


class CounterpartyIn(Schema):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    kind: Counterparty.Kind
    vat_no: str = Field(default="", max_length=30)
    email: str = Field(default="", max_length=320)
    payment_terms_days: int = Field(default=30, ge=0, le=365)


class CounterpartyPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    days_late_override: int | None = Field(default=None, ge=-60, le=365)
    vat_no: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=320)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    status: Counterparty.Status | None = None


class CounterpartyOut(Schema):
    id: UUID
    code: str
    name: str
    kind: str
    vat_no: str
    email: str
    payment_terms_days: int
    status: str
    days_late_override: int | None


class CounterpartyFilter(Schema):
    kind: Counterparty.Kind | None = None
    status: Counterparty.Status | None = None


@router.get(f"{BASE}/counterparties", response=list[CounterpartyOut])
@requires("registers.counterparty.read")
def list_counterparties(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[CounterpartyFilter]
) -> list[Counterparty]:
    ctx = workspace_ctx(request, slug, entity_id)
    return services.list_counterparties(ctx, entity_id, kind=q.kind, status=q.status)


@router.post(f"{BASE}/counterparties", response={201: CounterpartyOut})
@requires("registers.counterparty.manage")
def create_counterparty(
    request: HttpRequest, slug: str, entity_id: UUID, payload: CounterpartyIn
) -> Status[Counterparty]:
    ctx = workspace_ctx(request, slug, entity_id)
    data = services.CounterpartyInput(**payload.dict())
    return Status(201, services.create_counterparty(ctx, entity_id, data))


@router.get(f"{BASE}/counterparties/{{uuid:counterparty_id}}", response=CounterpartyOut)
@requires("registers.counterparty.read")
def get_counterparty(
    request: HttpRequest, slug: str, entity_id: UUID, counterparty_id: UUID
) -> Counterparty:
    ctx = workspace_ctx(request, slug, entity_id)
    return services.get_counterparty(ctx, entity_id, counterparty_id)


@router.patch(f"{BASE}/counterparties/{{uuid:counterparty_id}}", response=CounterpartyOut)
@requires("registers.counterparty.manage")
def update_counterparty(
    request: HttpRequest, slug: str, entity_id: UUID, counterparty_id: UUID,
    payload: CounterpartyPatch,
) -> Counterparty:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    changes = payload.dict(exclude_unset=True)
    return services.update_counterparty(ctx, entity_id, counterparty_id, changes)


# --- open items and allocations ------------------------------------------------------------------


class OpenItemQuery(Schema):
    as_of: date
    counterparty_id: UUID | None = None
    side: Side | None = None
    include_settled: bool = False


class OpenItemOut(Schema):
    line_id: UUID
    entry_id: UUID
    entry_ref: str
    side: str
    kind: str
    account_code: str
    counterparty_id: UUID
    counterparty_code: str
    accounting_date: date
    due_date: date
    days_overdue: int
    reference: str
    description: str
    amount: str
    allocated: str
    open_amount: str
    status: str
    disputed: bool
    note: str


def _item_out(item: services.OpenItem, as_of: date) -> OpenItemOut:
    return OpenItemOut(
        line_id=item.line_id, entry_id=item.entry_id, entry_ref=item.entry_ref, side=item.side,
        kind=item.kind, account_code=item.account_code, counterparty_id=item.counterparty_id,
        counterparty_code=item.counterparty_code, accounting_date=item.accounting_date,
        due_date=item.due_date, days_overdue=item.days_overdue(as_of), reference=item.reference,
        description=item.description, amount=f"{item.amount:.2f}",
        allocated=f"{item.allocated:.2f}", open_amount=f"{item.open_amount:.2f}",
        status=item.status, disputed=item.disputed, note=item.note,
    )  # fmt: skip


@router.get(f"{BASE}/open-items", response=list[OpenItemOut])
@requires("registers.counterparty.read")
def list_open_items(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[OpenItemQuery]
) -> list[OpenItemOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    items = services.open_items(ctx, entity_id, as_of=q.as_of, counterparty_id=q.counterparty_id,
                                side=q.side, include_settled=q.include_settled)  # fmt: skip
    return [_item_out(i, q.as_of) for i in items]


class AllocationIn(Schema):
    invoice_line_id: UUID
    payment_line_id: UUID
    amount: str = Field(pattern=AMOUNT, description='Decimal string, e.g. "120.50"')


class AllocationOut(Schema):
    id: UUID
    debit_line_id: UUID
    credit_line_id: UUID
    amount: str
    allocated_on: date


def _allocation_out(a: Allocation) -> AllocationOut:
    return AllocationOut(id=a.id, debit_line_id=a.debit_line_id, credit_line_id=a.credit_line_id,
                         amount=f"{a.amount:.2f}", allocated_on=a.allocated_on)  # fmt: skip


@router.post(f"{BASE}/allocations", response={201: AllocationOut})
@requires("registers.allocation.manage")
def create_allocation(
    request: HttpRequest, slug: str, entity_id: UUID, payload: AllocationIn
) -> Status[AllocationOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    allocation = services.allocate(
        ctx, entity_id, invoice_line_id=payload.invoice_line_id,
        payment_line_id=payload.payment_line_id, amount=Decimal(payload.amount),
    )  # fmt: skip
    return Status(201, _allocation_out(allocation))


@router.get(f"{BASE}/open-items/{{uuid:line_id}}/allocations", response=list[AllocationOut])
@requires("registers.counterparty.read")
def list_allocations(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID
) -> list[AllocationOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_allocation_out(a) for a in services.list_allocations(ctx, entity_id, line_id)]


@router.delete(f"{BASE}/allocations/{{uuid:allocation_id}}", response={204: None})
@requires("registers.allocation.manage")
def delete_allocation(
    request: HttpRequest, slug: str, entity_id: UUID, allocation_id: UUID
) -> Status[None]:
    ctx = workspace_ctx(request, slug, entity_id)
    services.unallocate(ctx, entity_id, allocation_id)
    return Status(204, None)


class AutoAllocateIn(Schema):
    as_of: date


@router.post(
    f"{BASE}/counterparties/{{uuid:counterparty_id}}/auto-allocate",
    response=list[AllocationOut],
)
@requires("registers.allocation.manage")
def auto_allocate(
    request: HttpRequest, slug: str, entity_id: UUID, counterparty_id: UUID,
    payload: AutoAllocateIn,
) -> list[AllocationOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    created = services.auto_allocate(ctx, entity_id, counterparty_id, as_of=payload.as_of)
    return [_allocation_out(a) for a in created]


class FlagIn(Schema):
    disputed: bool
    note: str = Field(default="", max_length=500)


class FlagOut(Schema):
    line_id: UUID
    disputed: bool
    note: str


@router.put(f"{BASE}/open-items/{{uuid:line_id}}/flag", response=FlagOut)
@requires("registers.allocation.manage")
def set_flag(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID, payload: FlagIn
) -> FlagOut:
    ctx = workspace_ctx(request, slug, entity_id)
    flag = services.set_flag(ctx, entity_id, line_id, disputed=payload.disputed, note=payload.note)
    return FlagOut(line_id=flag.line_id, disputed=flag.disputed, note=flag.note)


# --- ageing --------------------------------------------------------------------------------------


class AgeingQuery(Schema):
    as_of: date
    side: Side = "RECEIVABLE"


class AgeingRowOut(Schema):
    counterparty_id: UUID
    counterparty_code: str
    counterparty_name: str
    buckets: dict[str, str]
    unapplied: str
    total: str


class AgeingOut(Schema):
    as_of: date
    side: str
    rows: list[AgeingRowOut]
    totals: dict[str, str]
    unapplied: str
    total: str
    control_balance: str
    reconciles: bool


@router.get(f"{BASE}/reports/ageing", response=AgeingOut)
@requires("registers.counterparty.read")
def ageing(request: HttpRequest, slug: str, entity_id: UUID, q: Query[AgeingQuery]) -> AgeingOut:
    ctx = workspace_ctx(request, slug, entity_id)
    report = services.ageing(ctx, entity_id, as_of=q.as_of, side=q.side)
    return AgeingOut(
        as_of=report.as_of, side=report.side,
        rows=[
            AgeingRowOut(counterparty_id=r.counterparty_id, counterparty_code=r.counterparty_code,
                         counterparty_name=r.counterparty_name,
                         buckets={k: f"{v:.2f}" for k, v in r.buckets.items()},
                         unapplied=f"{r.unapplied:.2f}", total=f"{r.total:.2f}")
            for r in report.rows
        ],
        totals={k: f"{v:.2f}" for k, v in report.totals.items()},
        unapplied=f"{report.unapplied:.2f}", total=f"{report.total:.2f}",
        control_balance=f"{report.control_balance:.2f}", reconciles=report.reconciles,
    )  # fmt: skip


@router.get(f"{BASE}/reports/ageing.csv")
@requires("reports.export")
def ageing_csv(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[AgeingQuery]
) -> HttpResponse:
    ctx = workspace_ctx(request, slug, entity_id)
    report = services.ageing(ctx, entity_id, as_of=q.as_of, side=q.side)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["code", "name", *services.BUCKETS, "unapplied", "total"])
    for r in report.rows:
        writer.writerow([safe_text(r.counterparty_code), safe_text(r.counterparty_name),
                         *(f"{r.buckets[b]:.2f}" for b in services.BUCKETS),
                         f"{r.unapplied:.2f}", f"{r.total:.2f}"])  # fmt: skip
    filename = f"ageing-{q.side.lower()}-{q.as_of.isoformat()}.csv"
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="reports.exported",
          subject_type="report", subject_id="ageing", entity_id=entity_id,
          changes={"format": "csv", "filename": filename})  # fmt: skip
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --- commitments: recurring obligations, loans, facilities, holidays (M3-4) -----------------------

RATE = r"^0(\.\d{1,6})?$"  # an annual rate as a fraction: 0.05 is 5%
Frequency = Literal["WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY"]
AdjustName = Literal["NONE", "FOLLOWING", "MODIFIED_FOLLOWING", "PRECEDING"]


class ObligationIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    category: RecurringObligation.Category
    direction: RecurringObligation.Direction
    amount: str = Field(pattern=AMOUNT)
    frequency: Frequency
    interval: int = Field(default=1, ge=1, le=52)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    start_date: date
    end_date: date | None = None
    adjust: AdjustName = "NONE"
    contractual: bool
    counterparty_id: UUID | None = None
    note: str = Field(default="", max_length=500)


class ObligationOut(Schema):
    id: UUID
    series_id: UUID
    version: int
    name: str
    category: str
    direction: str
    amount: str
    currency: str
    frequency: str
    interval: int
    day_of_month: int | None
    start_date: date
    end_date: date | None
    adjust: str
    contractual: bool
    nature: Literal["COMMITTED", "EXPECTED"]
    counterparty_id: UUID | None
    note: str
    superseded_at: datetime | None
    created_at: datetime


class DebtIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    kind: DebtInstrument.Kind
    principal: str | None = Field(default=None, pattern=AMOUNT)
    facility_limit: str | None = Field(default=None, pattern=AMOUNT)
    start_date: date
    maturity_date: date | None = None
    payment_frequency_months: Literal[1, 3, 6, 12] = 1
    rate_type: DebtInstrument.RateType
    fixed_rate: str | None = Field(default=None, pattern=RATE)
    reference_rate_key: str = Field(default="", max_length=40)
    margin: str | None = Field(default=None, pattern=RATE)
    assumed_reference_rate: str | None = Field(default=None, pattern=RATE)
    day_count: Literal["ACT_360", "ACT_365", "30_360"] = "ACT_365"
    repayment_type: Literal["", "ANNUITY", "LINEAR", "BULLET", "IO_THEN_ANNUITY"] = ""
    interest_only_periods: int = Field(default=0, ge=0, le=599)
    adjust: AdjustName = "MODIFIED_FOLLOWING"
    lender_id: UUID | None = None
    note: str = Field(default="", max_length=500)


class DebtOut(Schema):
    id: UUID
    series_id: UUID
    version: int
    name: str
    kind: str
    principal: str | None
    facility_limit: str | None
    start_date: date
    maturity_date: date | None
    payment_frequency_months: int
    rate_type: str
    fixed_rate: str | None
    reference_rate_key: str
    margin: str | None
    assumed_reference_rate: str | None
    day_count: str
    repayment_type: str
    interest_only_periods: int
    adjust: str
    lender_id: UUID | None
    note: str
    superseded_at: datetime | None
    created_at: datetime


class InstalmentOut(Schema):
    number: int
    period_start: date
    period_end: date
    due: date
    opening: str
    interest: str
    principal: str
    payment: str
    closing: str


class HolidayIn(Schema):
    day: date
    name: str = Field(min_length=1, max_length=100)


class HolidayOut(Schema):
    id: UUID
    day: date
    name: str


class FlowsQuery(Schema):
    date_from: date
    date_to: date


class CommitmentFlowOut(Schema):
    due: date
    scheduled: date
    amount: str
    nature: Literal["COMMITTED", "EXPECTED"]
    source: str
    component: str
    category: str
    name: str
    series_id: UUID
    version_id: UUID


def _dec(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _text(value: Decimal | None, places: int = 2) -> str | None:
    return None if value is None else f"{value:.{places}f}"


def _obligation_out(o: RecurringObligation) -> ObligationOut:
    return ObligationOut(
        id=o.id, series_id=o.series_id, version=o.version, name=o.name, category=o.category,
        direction=o.direction, amount=f"{o.amount:.2f}", currency=o.currency,
        frequency=o.frequency, interval=o.interval, day_of_month=o.day_of_month,
        start_date=o.start_date, end_date=o.end_date, adjust=o.adjust,
        contractual=o.contractual, nature="COMMITTED" if o.contractual else "EXPECTED",
        counterparty_id=o.counterparty_id, note=o.note, superseded_at=o.superseded_at,
        created_at=o.created_at,
    )  # fmt: skip


def _debt_out(d: DebtInstrument) -> DebtOut:
    return DebtOut(
        id=d.id, series_id=d.series_id, version=d.version, name=d.name, kind=d.kind,
        principal=_text(d.principal), facility_limit=_text(d.facility_limit),
        start_date=d.start_date, maturity_date=d.maturity_date,
        payment_frequency_months=d.payment_frequency_months, rate_type=d.rate_type,
        fixed_rate=_text(d.fixed_rate, 6), reference_rate_key=d.reference_rate_key,
        margin=_text(d.margin, 6), assumed_reference_rate=_text(d.assumed_reference_rate, 6),
        day_count=d.day_count, repayment_type=d.repayment_type,
        interest_only_periods=d.interest_only_periods, adjust=d.adjust, lender_id=d.lender_id,
        note=d.note, superseded_at=d.superseded_at, created_at=d.created_at,
    )  # fmt: skip


def _obligation_input(body: ObligationIn) -> commitments.ObligationInput:
    return commitments.ObligationInput(**{**body.dict(), "amount": Decimal(body.amount)})


def _debt_input(body: DebtIn) -> commitments.DebtInput:
    return commitments.DebtInput(**{
        **body.dict(), "principal": _dec(body.principal),
        "facility_limit": _dec(body.facility_limit), "fixed_rate": _dec(body.fixed_rate),
        "margin": _dec(body.margin), "assumed_reference_rate": _dec(body.assumed_reference_rate),
    })  # fmt: skip


@router.get(f"{BASE}/obligations", response=list[ObligationOut])
@requires("registers.commitment.read")
def list_obligations(request: HttpRequest, slug: str, entity_id: UUID) -> list[ObligationOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_obligation_out(o) for o in
            commitments.current_versions(ctx, entity_id, RecurringObligation)]  # fmt: skip


@router.post(f"{BASE}/obligations", response={201: ObligationOut})
@requires("registers.commitment.manage")
def create_obligation(request: HttpRequest, slug: str, entity_id: UUID,
                      body: ObligationIn) -> Status[ObligationOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    saved = commitments.save_obligation(ctx, entity_id, _obligation_input(body))
    return Status(201, _obligation_out(saved))


@router.put(f"{BASE}/obligations/{{uuid:series_id}}", response=ObligationOut)
@requires("registers.commitment.manage")
def change_obligation(request: HttpRequest, slug: str, entity_id: UUID, series_id: UUID,
                      body: ObligationIn) -> ObligationOut:  # fmt: skip
    """Adds a new version; the previous one is kept in the history."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _obligation_out(commitments.save_obligation(ctx, entity_id, _obligation_input(body),
                                                       series_id))  # fmt: skip


@router.post(f"{BASE}/obligations/{{uuid:series_id}}/retire", response=ObligationOut)
@requires("registers.commitment.manage")
def retire_obligation(request: HttpRequest, slug: str, entity_id: UUID,
                      series_id: UUID) -> ObligationOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _obligation_out(commitments.retire(ctx, entity_id, RecurringObligation, series_id))


@router.get(f"{BASE}/obligations/{{uuid:series_id}}/history", response=list[ObligationOut])
@requires("registers.commitment.read")
def obligation_history(request: HttpRequest, slug: str, entity_id: UUID,
                       series_id: UUID) -> list[ObligationOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return [_obligation_out(o) for o in
            commitments.history(ctx, entity_id, RecurringObligation, series_id)]  # fmt: skip


@router.get(f"{BASE}/debt-instruments", response=list[DebtOut])
@requires("registers.commitment.read")
def list_debt(request: HttpRequest, slug: str, entity_id: UUID) -> list[DebtOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_debt_out(d) for d in commitments.current_versions(ctx, entity_id, DebtInstrument)]


@router.post(f"{BASE}/debt-instruments", response={201: DebtOut})
@requires("registers.commitment.manage")
def create_debt(request: HttpRequest, slug: str, entity_id: UUID,
                body: DebtIn) -> Status[DebtOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _debt_out(commitments.save_debt(ctx, entity_id, _debt_input(body))))


@router.put(f"{BASE}/debt-instruments/{{uuid:series_id}}", response=DebtOut)
@requires("registers.commitment.manage")
def change_debt(request: HttpRequest, slug: str, entity_id: UUID, series_id: UUID,
                body: DebtIn) -> DebtOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _debt_out(commitments.save_debt(ctx, entity_id, _debt_input(body), series_id))


@router.post(f"{BASE}/debt-instruments/{{uuid:series_id}}/retire", response=DebtOut)
@requires("registers.commitment.manage")
def retire_debt(request: HttpRequest, slug: str, entity_id: UUID, series_id: UUID) -> DebtOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _debt_out(commitments.retire(ctx, entity_id, DebtInstrument, series_id))


@router.get(f"{BASE}/debt-instruments/{{uuid:series_id}}/history", response=list[DebtOut])
@requires("registers.commitment.read")
def debt_history(request: HttpRequest, slug: str, entity_id: UUID,
                 series_id: UUID) -> list[DebtOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return [_debt_out(d) for d in commitments.history(ctx, entity_id, DebtInstrument, series_id)]


@router.get(f"{BASE}/debt-instruments/{{uuid:series_id}}/schedule", response=list[InstalmentOut])
@requires("registers.commitment.read")
def debt_schedule(request: HttpRequest, slug: str, entity_id: UUID,
                  series_id: UUID) -> list[InstalmentOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return [InstalmentOut(number=r.number, period_start=r.period_start, period_end=r.period_end,
                          due=r.due, opening=f"{r.opening:.2f}", interest=f"{r.interest:.2f}",
                          principal=f"{r.principal:.2f}", payment=f"{r.payment:.2f}",
                          closing=f"{r.closing:.2f}")
            for r in commitments.schedule(ctx, entity_id, series_id)]  # fmt: skip


@router.get(f"{BASE}/commitment-flows", response=list[CommitmentFlowOut])
@requires("registers.commitment.read")
def commitment_flows(request: HttpRequest, slug: str, entity_id: UUID,
                     q: Query[FlowsQuery]) -> list[CommitmentFlowOut]:  # fmt: skip
    """The dated flows of all current obligations and loans in a period (inflows positive)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [CommitmentFlowOut(due=f.due, scheduled=f.scheduled, amount=f"{f.amount:.2f}",
                    nature=f.nature, source=f.source, component=f.component,  # type: ignore[arg-type]
                    category=f.category, name=f.name, series_id=f.series_id,
                    version_id=f.version_id)
            for f in commitments.flows(ctx, entity_id, q.date_from, q.date_to)]  # fmt: skip


@router.get(f"{BASE}/holidays", response=list[HolidayOut])
@requires("registers.commitment.read")
def list_holidays(request: HttpRequest, slug: str, entity_id: UUID) -> list[HolidayOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [HolidayOut(id=h.id, day=h.day, name=h.name)
            for h in commitments.holidays(ctx, entity_id)]  # fmt: skip


@router.post(f"{BASE}/holidays", response={201: HolidayOut})
@requires("registers.commitment.manage")
def add_holiday(request: HttpRequest, slug: str, entity_id: UUID,
                body: HolidayIn) -> Status[HolidayOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    h = commitments.add_holiday(ctx, entity_id, body.day, body.name)
    return Status(201, HolidayOut(id=h.id, day=h.day, name=h.name))


@router.delete(f"{BASE}/holidays/{{uuid:holiday_id}}", response={204: None})
@requires("registers.commitment.manage")
def remove_holiday(request: HttpRequest, slug: str, entity_id: UUID,
                   holiday_id: UUID) -> Status[None]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    commitments.remove_holiday(ctx, entity_id, holiday_id)
    return Status(204, None)


# --- tax payment calendar (M3-5) ------------------------------------------------------------------


class TaxPaymentIn(Schema):
    kind: TaxPayment.Kind
    period_label: str = Field(min_length=1, max_length=40)
    due_date: date
    amount: str = Field(pattern=AMOUNT)
    nature: TaxPayment.Nature
    reference: str = Field(default="", max_length=100)
    paid_on: date | None = None
    note: str = Field(default="", max_length=500)


class TaxPaymentOut(Schema):
    id: UUID
    series_id: UUID
    version: int
    kind: str
    period_label: str
    due_date: date
    amount: str
    nature: Literal["COMMITTED", "EXPECTED"]
    reference: str
    paid_on: date | None
    note: str
    superseded_at: datetime | None
    created_at: datetime


def _tax_out(t: TaxPayment) -> TaxPaymentOut:
    return TaxPaymentOut(
        id=t.id,
        series_id=t.series_id,
        version=t.version,
        kind=t.kind,
        period_label=t.period_label,
        due_date=t.due_date,
        amount=f"{t.amount:.2f}",
        nature=t.nature,  # type: ignore[arg-type]
        reference=t.reference,
        paid_on=t.paid_on,
        note=t.note,
        superseded_at=t.superseded_at,
        created_at=t.created_at,
    )


def _tax_input(body: TaxPaymentIn) -> commitments.TaxInput:
    return commitments.TaxInput(**{**body.dict(), "amount": Decimal(body.amount)})


@router.get(f"{BASE}/tax-payments", response=list[TaxPaymentOut])
@requires("registers.commitment.read")
def list_tax_payments(request: HttpRequest, slug: str, entity_id: UUID) -> list[TaxPaymentOut]:
    """Entered by hand: no tax due dates are built in until verified (decision #93)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_tax_out(t) for t in commitments.current_versions(ctx, entity_id, TaxPayment)]


@router.post(f"{BASE}/tax-payments", response={201: TaxPaymentOut})
@requires("registers.commitment.manage")
def create_tax_payment(
    request: HttpRequest, slug: str, entity_id: UUID, body: TaxPaymentIn
) -> Status[TaxPaymentOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _tax_out(commitments.save_tax_payment(ctx, entity_id, _tax_input(body))))


@router.put(f"{BASE}/tax-payments/{{uuid:series_id}}", response=TaxPaymentOut)
@requires("registers.commitment.manage")
def change_tax_payment(
    request: HttpRequest, slug: str, entity_id: UUID, series_id: UUID, body: TaxPaymentIn
) -> TaxPaymentOut:
    """Adds a new version (for example with the assessed amount, or the date it was paid)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _tax_out(commitments.save_tax_payment(ctx, entity_id, _tax_input(body), series_id))


@router.post(f"{BASE}/tax-payments/{{uuid:series_id}}/retire", response=TaxPaymentOut)
@requires("registers.commitment.manage")
def retire_tax_payment(
    request: HttpRequest, slug: str, entity_id: UUID, series_id: UUID
) -> TaxPaymentOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _tax_out(commitments.retire(ctx, entity_id, TaxPayment, series_id))


@router.get(f"{BASE}/tax-payments/{{uuid:series_id}}/history", response=list[TaxPaymentOut])
@requires("registers.commitment.read")
def tax_payment_history(
    request: HttpRequest, slug: str, entity_id: UUID, series_id: UUID
) -> list[TaxPaymentOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_tax_out(t) for t in commitments.history(ctx, entity_id, TaxPayment, series_id)]


# --- payment behaviour (M3-6) ---------------------------------------------------------------------


class BehaviourQuery(Schema):
    as_of: date


class BehaviourOut(Schema):
    counterparty_id: UUID
    counterparty_code: str
    observed_days_late: int | None
    sample: int
    override: int | None
    days_late: int = Field(description="Used by the forecast: override, else observed, else 0")
    note: str


@router.get(f"{BASE}/payment-behaviour", response=list[BehaviourOut])
@requires("registers.counterparty.read")
def get_payment_behaviour(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[BehaviourQuery]
) -> list[BehaviourOut]:
    """How late each customer pays, from invoices settled in the 12 months before ``as_of``."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        BehaviourOut(counterparty_id=b.counterparty_id, counterparty_code=b.counterparty_code,
                     observed_days_late=b.observed_days_late, sample=b.sample,
                     override=b.override, days_late=b.days_late, note=b.note)
        for b in behaviour.payment_behaviour(ctx, entity_id, q.as_of)
    ]  # fmt: skip
