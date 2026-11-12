"""Public interface of the ``assets`` module and its HTTP routes (M6-1: fixed assets).

Routes are entity-scoped (``/api/w/{slug}/entities/{entity_id}/...``). Amounts are decimal
strings; months are the first day of the month.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .services import CONVENTION, MonthlyDepreciation, depreciation_plan

__all__ = ["CONVENTION", "MonthlyDepreciation", "depreciation_plan", "router"]

router = Router(tags=["fixed assets"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
AMOUNT = r"^\d{1,12}(\.\d{1,2})?$"
Category = Literal["BUILDINGS", "MACHINERY", "VEHICLES", "IT_EQUIPMENT", "FURNITURE", "OTHER"]
Method = Literal["STRAIGHT_LINE", "DECLINING_BALANCE"]


class AssetIn(Schema):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    category: Category
    asset_account_id: UUID = Field(description="Where the cost is (e.g. 1010)")
    accumulated_account_id: UUID = Field(description="Accumulated depreciation (e.g. 1019)")
    expense_account_id: UUID = Field(description="Depreciation expense (e.g. 6600)")
    acquired_on: date
    cost: str = Field(pattern=AMOUNT)
    residual_value: str = Field(default="0", pattern=AMOUNT)
    useful_life_months: int = Field(ge=1, le=1200)
    method: Method = "STRAIGHT_LINE"
    annual_rate: str | None = Field(
        default=None, pattern=r"^\d{1,3}(\.\d{1,4})?$", description="Declining balance: % a year"
    )


class AssetOut(Schema):
    id: UUID
    code: str
    name: str
    category: str
    asset_account_id: UUID
    accumulated_account_id: UUID
    expense_account_id: UUID
    acquired_on: date
    cost: str
    residual_value: str
    useful_life_months: int
    method: str
    annual_rate: str | None = Field(description="Declining balance: % a year")
    disposed_on: date | None
    disposal_proceeds: str | None
    locked: bool = Field(description="Depreciation was prepared; the terms can no longer change")
    accumulated: str = Field(description="Accumulated depreciation at the date asked for")
    book_value: str
    status: str = Field(description="ACTIVE, FULLY_DEPRECIATED or DISPOSED")
    disposal_gain: str | None = Field(description="Proceeds - book value; negative is a loss")


def _out(view: services.AssetView) -> AssetOut:
    a = view.asset
    return AssetOut(
        id=a.id, code=a.code, name=a.name, category=a.category,
        asset_account_id=a.asset_account_id, accumulated_account_id=a.accumulated_account_id,
        expense_account_id=a.expense_account_id, acquired_on=a.acquired_on,
        cost=f"{a.cost:.2f}", residual_value=f"{a.residual_value:.2f}",
        useful_life_months=a.useful_life_months, method=a.method,
        annual_rate=f"{a.annual_rate * 100:.2f}" if a.annual_rate is not None else None,
        disposed_on=a.disposed_on,
        disposal_proceeds=f"{a.disposal_proceeds:.2f}" if a.disposal_proceeds is not None else None,
        locked=a.locked_at is not None, accumulated=f"{view.accumulated:.2f}",
        book_value=f"{view.book_value:.2f}", status=view.status,
        disposal_gain=f"{view.gain:.2f}" if view.gain is not None else None,
    )  # fmt: skip


def _input(payload: AssetIn) -> services.AssetInput:
    return services.AssetInput(**payload.dict())


class AsOfQuery(Schema):
    as_of: date | None = Field(default=None, description="Defaults to today")


@router.get(f"{BASE}/fixed-assets", response=list[AssetOut])
@requires("assets.read")
def list_assets(request: HttpRequest, slug: str, entity_id: UUID,
                q: Query[AsOfQuery]) -> list[AssetOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    day = q.as_of or timezone.localdate()
    return [_out(v) for v in services.assets(ctx, entity_id, as_of=day)]


def _one(request: HttpRequest, slug: str, entity_id: UUID, asset_id: UUID) -> AssetOut:
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.assets(ctx, entity_id, as_of=timezone.localdate())
    return _out(next(v for v in found if v.asset.id == asset_id))


@router.post(f"{BASE}/fixed-assets", response={201: AssetOut})
@requires("assets.manage")
def create_asset(request: HttpRequest, slug: str, entity_id: UUID,
                 payload: AssetIn) -> Status[AssetOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    asset = services.create_asset(ctx, entity_id, _input(payload))
    return Status(201, _one(request, slug, entity_id, asset.id))


@router.put(f"{BASE}/fixed-assets/{{uuid:asset_id}}", response=AssetOut)
@requires("assets.manage")
def correct_asset(request: HttpRequest, slug: str, entity_id: UUID, asset_id: UUID,
                  payload: AssetIn) -> AssetOut:  # fmt: skip
    """Correct the terms; refused once depreciation has been prepared for the asset."""
    ctx = workspace_ctx(request, slug, entity_id)
    services.correct_asset(ctx, entity_id, asset_id, _input(payload))
    return _one(request, slug, entity_id, asset_id)


class DisposalIn(Schema):
    disposed_on: date
    proceeds: str = Field(default="0", pattern=AMOUNT)


@router.post(f"{BASE}/fixed-assets/{{uuid:asset_id}}/dispose", response=AssetOut)
@requires("assets.manage")
def dispose_asset(request: HttpRequest, slug: str, entity_id: UUID, asset_id: UUID,
                  payload: DisposalIn) -> AssetOut:  # fmt: skip
    """Record the disposal (once). Depreciation stops from its month; book it in the ledger."""
    ctx = workspace_ctx(request, slug, entity_id)
    services.dispose(ctx, entity_id, asset_id, on=payload.disposed_on, proceeds=payload.proceeds)
    return _one(request, slug, entity_id, asset_id)


class ScheduleRowOut(Schema):
    month: date
    opening: str
    depreciation: str
    closing: str
    accumulated: str
    entry_id: UUID | None = Field(description="The draft or posted entry, once prepared")


class ScheduleOut(Schema):
    asset_id: UUID
    convention: str
    rows: list[ScheduleRowOut]


@router.get(f"{BASE}/fixed-assets/{{uuid:asset_id}}/schedule", response=ScheduleOut)
@requires("assets.read")
def asset_schedule(request: HttpRequest, slug: str, entity_id: UUID,
                   asset_id: UUID) -> ScheduleOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    asset, rows, prepared = services.asset_schedule(ctx, entity_id, asset_id)
    return ScheduleOut(asset_id=asset.id, convention=CONVENTION, rows=[
        ScheduleRowOut(month=r.month, opening=f"{r.opening:.2f}",
                       depreciation=f"{r.depreciation:.2f}", closing=f"{r.closing:.2f}",
                       accumulated=f"{r.accumulated:.2f}", entry_id=prepared.get(r.month))
        for r in rows
    ])  # fmt: skip


class RunOut(Schema):
    id: UUID
    month: date
    total: str
    assets: int
    entry_id: UUID
    entry_ref: str = Field(description="Journal and number, once posted")
    entry_status: str = Field(description="DRAFT, SUBMITTED, APPROVED, POSTED, REJECTED or VOID")
    cancelled: bool = Field(description="Its entry was voided or rejected; prepared again since")
    created_at: datetime


def _run_out(view: services.RunView) -> RunOut:
    r = view.run
    return RunOut(id=r.id, month=r.month, total=f"{r.total:.2f}", assets=view.assets,
                  entry_id=r.entry_id, entry_ref=view.entry_ref, entry_status=view.entry_status,
                  cancelled=r.cancelled_at is not None, created_at=r.created_at)  # fmt: skip


class PrepareIn(Schema):
    month: date = Field(description="Any day of the month to depreciate")


@router.get(f"{BASE}/depreciation-runs", response=list[RunOut])
@requires("assets.read")
def list_runs(request: HttpRequest, slug: str, entity_id: UUID) -> list[RunOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_run_out(v) for v in services.runs(ctx, entity_id)]


@router.post(f"{BASE}/depreciation-runs", response={201: RunOut})
@requires("assets.manage")
def prepare_depreciation(request: HttpRequest, slug: str, entity_id: UUID,
                         payload: PrepareIn) -> Status[RunOut]:  # fmt: skip
    """Prepare the month's depreciation as one draft journal entry. It still needs the normal
    approval and posting; nothing is posted here."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _run_out(services.prepare_month(ctx, entity_id, payload.month)))
