"""Public interface of the ``registers`` module and its HTTP routes (backlog M2-2).

All routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.core.export import safe_text
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import Allocation, Counterparty

__all__ = ["Counterparty", "router"]

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
