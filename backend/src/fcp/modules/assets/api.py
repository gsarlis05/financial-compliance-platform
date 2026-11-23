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
from .allowances import RULES_NOTE, AllowanceRate, AllowanceRow, allowance_schedule
from .models import CapitalAllowanceClass
from .schedule import (
    DECLINING_BALANCE,
    FULL_MONTH,
    NEXT_MONTH,
    PRORATA_DAYS,
    STRAIGHT_LINE,
    AssetTerms,
    ScheduleRow,
    schedule,
)
from .services import (
    CONVENTION,
    MonthlyDepreciation,
    capital_allowance_plan,
    depreciation_plan,
)

__all__ = [
    "CONVENTION",
    "DECLINING_BALANCE",
    "FULL_MONTH",
    "NEXT_MONTH",
    "PRORATA_DAYS",
    "STRAIGHT_LINE",
    "AllowanceRate",
    "AllowanceRow",
    "AssetTerms",
    "MonthlyDepreciation",
    "ScheduleRow",
    "allowance_schedule",
    "capital_allowance_plan",
    "depreciation_plan",
    "router",
    "schedule",
]

router = Router(tags=["fixed assets"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
AMOUNT = r"^\d{1,12}(\.\d{1,2})?$"
Category = Literal["BUILDINGS", "MACHINERY", "VEHICLES", "IT_EQUIPMENT", "FURNITURE", "OTHER"]
Method = Literal["STRAIGHT_LINE", "DECLINING_BALANCE"]
Commencement = Literal["PRORATA_DAYS", "NEXT_MONTH", "FULL_MONTH"]
FirstYear = Literal["FULL_YEAR", "MONTHS_IN_USE", "NONE"]


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
    available_on: date | None = Field(
        default=None, description="IAS 16: when the asset is available for use (default: acquired)"
    )
    commencement: Commencement = Field(
        default="PRORATA_DAYS",
        description="PRORATA_DAYS (from the available-for-use date), NEXT_MONTH, or FULL_MONTH",
    )
    allowance_class_code: str = Field(default="", max_length=20, description="Tax allowances")


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
    available_on: date = Field(description="IAS 16 commencement (the acquisition date if not set)")
    commencement: str
    allowance_class_code: str
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
        available_on=a.available_on or a.acquired_on, commencement=a.commencement,
        allowance_class_code=a.allowance_class_code, disposed_on=a.disposed_on,
        disposal_proceeds=f"{a.disposal_proceeds:.2f}" if a.disposal_proceeds is not None else None,
        locked=a.locked_at is not None, accumulated=f"{view.accumulated:.2f}",
        book_value=f"{view.book_value:.2f}", status=view.status,
        disposal_gain=f"{view.gain:.2f}" if view.gain is not None else None,
    )  # fmt: skip


def _input(payload: AssetIn) -> services.AssetInput:
    return services.AssetInput(**payload.dict())


class AssetsAsOfQuery(Schema):
    as_of: date | None = Field(default=None, description="Defaults to today")


@router.get(f"{BASE}/fixed-assets", response=list[AssetOut])
@requires("assets.read")
def list_assets(request: HttpRequest, slug: str, entity_id: UUID,
                q: Query[AssetsAsOfQuery]) -> list[AssetOut]:  # fmt: skip
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


class AllowanceRowOut(Schema):
    tax_year: int
    rate: str = Field(description="% a year")
    allowance: str
    written_down: str = Field(description="Tax written-down value at the end of the tax year")


class ScheduleOut(Schema):
    asset_id: UUID
    convention: str
    rows: list[ScheduleRowOut]
    allowance_rules: str
    allowances: list[AllowanceRowOut] = Field(
        description="Tax capital allowances, separate from depreciation (none without a class)"
    )


@router.get(f"{BASE}/fixed-assets/{{uuid:asset_id}}/schedule", response=ScheduleOut)
@requires("assets.read")
def asset_schedule(request: HttpRequest, slug: str, entity_id: UUID,
                   asset_id: UUID) -> ScheduleOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    asset, rows, prepared = services.asset_schedule(ctx, entity_id, asset_id)
    allowances = services.asset_allowances(ctx, entity_id, asset_id)
    return ScheduleOut(asset_id=asset.id, convention=CONVENTION, allowance_rules=RULES_NOTE,
                       allowances=[AllowanceRowOut(tax_year=a.tax_year,
                                                   rate=f"{a.rate * 100:.2f}",
                                                   allowance=f"{a.allowance:.2f}",
                                                   written_down=f"{a.written_down:.2f}")
                                   for a in allowances], rows=[
        ScheduleRowOut(month=r.month, opening=f"{r.opening:.2f}",
                       depreciation=f"{r.depreciation:.2f}", closing=f"{r.closing:.2f}",
                       accumulated=f"{r.accumulated:.2f}", entry_id=prepared.get(r.month))
        for r in rows
    ])  # fmt: skip


class DepreciationRunOut(Schema):
    id: UUID
    month: date
    total: str
    assets: int
    entry_id: UUID
    entry_ref: str = Field(description="Journal and number, once posted")
    entry_status: str = Field(description="DRAFT, SUBMITTED, APPROVED, POSTED, REJECTED or VOID")
    cancelled: bool = Field(description="Its entry was voided or rejected; prepared again since")
    created_at: datetime


def _run_out(view: services.RunView) -> DepreciationRunOut:
    r = view.run
    return DepreciationRunOut(id=r.id, month=r.month, total=f"{r.total:.2f}", assets=view.assets,
                  entry_id=r.entry_id, entry_ref=view.entry_ref, entry_status=view.entry_status,
                  cancelled=r.cancelled_at is not None, created_at=r.created_at)  # fmt: skip


class PrepareIn(Schema):
    month: date = Field(description="Any day of the month to depreciate")


@router.get(f"{BASE}/depreciation-runs", response=list[DepreciationRunOut])
@requires("assets.read")
def list_runs(request: HttpRequest, slug: str, entity_id: UUID) -> list[DepreciationRunOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_run_out(v) for v in services.runs(ctx, entity_id)]


@router.post(f"{BASE}/depreciation-runs", response={201: DepreciationRunOut})
@requires("assets.manage")
def prepare_depreciation(request: HttpRequest, slug: str, entity_id: UUID,
                         payload: PrepareIn) -> Status[DepreciationRunOut]:  # fmt: skip
    """Prepare the month's depreciation as one draft journal entry. It still needs the normal
    approval and posting; nothing is posted here."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _run_out(services.prepare_month(ctx, entity_id, payload.month)))


# --- tax capital allowances (M6F-3, #148) -------------------------------------------------------


class AllowanceClassIn(Schema):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    annual_rate: str = Field(pattern=r"^\d{1,3}(\.\d{1,2})?$", description="% a year")
    first_year: FirstYear
    effective_from: date = Field(description="First day of the first tax year the rate applies")
    source: str = Field(min_length=1, max_length=500, description="Law and article, or adviser")


class AllowanceClassOut(Schema):
    id: UUID
    code: str
    name: str
    annual_rate: str = Field(description="% a year")
    first_year: str
    effective_from: date
    source: str
    created_at: datetime


def _class_out(c: CapitalAllowanceClass) -> AllowanceClassOut:
    return AllowanceClassOut(id=c.id, code=c.code, name=c.name,
                             annual_rate=f"{c.annual_rate * 100:.2f}", first_year=c.first_year,
                             effective_from=c.effective_from, source=c.source,
                             created_at=c.created_at)  # fmt: skip


@router.get(f"{BASE}/capital-allowance-classes", response=list[AllowanceClassOut])
@requires("assets.read")
def list_allowance_classes(request: HttpRequest, slug: str,
                           entity_id: UUID) -> list[AllowanceClassOut]:  # fmt: skip
    """The entity's capital allowance classes and their rates by tax year (none built in)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_class_out(c) for c in services.allowance_classes(ctx, entity_id)]


@router.post(f"{BASE}/capital-allowance-classes", response={201: AllowanceClassOut})
@requires("assets.manage")
def add_allowance_class(request: HttpRequest, slug: str, entity_id: UUID,
                        payload: AllowanceClassIn) -> Status[AllowanceClassOut]:  # fmt: skip
    """A class, or a new rate for a class from a later tax year; never changed afterwards."""
    ctx = workspace_ctx(request, slug, entity_id)
    data = services.NewAllowanceClass(**payload.model_dump())
    made = services.add_allowance_class(ctx, entity_id, data)
    return Status(201, _class_out(made))


class AllowanceClassChoiceIn(Schema):
    allowance_class_code: str = Field(max_length=20, description="Blank: no capital allowances")


@router.put(f"{BASE}/fixed-assets/{{uuid:asset_id}}/allowance-class", response=AssetOut)
@requires("assets.manage")
def set_allowance_class(request: HttpRequest, slug: str, entity_id: UUID, asset_id: UUID,
                        payload: AllowanceClassChoiceIn) -> AssetOut:  # fmt: skip
    """Set or change the asset's allowance class, also after depreciation was prepared."""
    ctx = workspace_ctx(request, slug, entity_id)
    services.set_allowance_class(ctx, entity_id, asset_id, payload.allowance_class_code)
    return _one(request, slug, entity_id, asset_id)


# --- the register against the ledger (V1-4) -----------------------------------------------------


class ReconciliationQuery(Schema):
    as_of: date


class ReconciliationRowOut(Schema):
    account_id: UUID
    account_code: str
    account_name: str
    kind: str = Field(description="COST or ACCUMULATED (depreciation)")
    register: str = Field(description="What the account should hold: cost a debit, accumulated "
                                      "depreciation a credit")  # fmt: skip
    ledger: str
    difference: str = Field(description="Ledger minus register")


class ReconciliationOut(Schema):
    as_of: date
    rows: list[ReconciliationRowOut]
    agrees: bool
    unposted_runs: list[DepreciationRunOut] = Field(
        description="Prepared depreciation not posted yet: it explains a difference until it is"
    )


@router.get(f"{BASE}/fixed-assets/reconciliation", response=ReconciliationOut)
@requires("assets.read")
def reconciliation(request: HttpRequest, slug: str, entity_id: UUID,
                   q: Query[ReconciliationQuery]) -> ReconciliationOut:  # fmt: skip
    """The register's cost and accumulated depreciation against the ledger, per account."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.reconcile(ctx, entity_id, q.as_of)
    return ReconciliationOut(
        as_of=found.as_of,
        rows=[ReconciliationRowOut(account_id=r.account_id, account_code=r.account_code,
                                   account_name=r.account_name, kind=r.kind,
                                   register=f"{r.register:.2f}", ledger=f"{r.ledger:.2f}",
                                   difference=f"{r.difference:.2f}") for r in found.rows],
        agrees=found.agrees,
        unposted_runs=[_run_out(v) for v in found.unposted_runs],
    )  # fmt: skip
