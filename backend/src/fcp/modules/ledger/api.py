"""Public interface of the ``ledger`` module and its HTTP routes.

All routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import date
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import accounts, periods
from .models import Account, FiscalYear, Period

__all__ = ["Account", "FiscalYear", "Period", "router"]

router = Router(tags=["ledger"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class AccountIn(Schema):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    name_el: str = Field(default="", max_length=200)
    type: Account.Type
    parent_code: str | None = Field(default=None, max_length=20)
    is_postable: bool = True
    currency: str = Field(default="", pattern=r"^([A-Z]{3})?$")


class AccountPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_el: str | None = Field(default=None, max_length=200)
    status: Account.Status | None = None


class AccountOut(Schema):
    id: UUID
    code: str
    name: str
    name_el: str
    type: str
    normal_side: str
    parent_id: UUID | None
    is_postable: bool
    status: str
    currency: str


class TemplateIn(Schema):
    template: Literal["cy_business", "personal"]


class PeriodOut(Schema):
    id: UUID
    number: int
    start_date: date
    end_date: date
    is_adjustment: bool
    status: str


class FiscalYearIn(Schema):
    start_date: date
    months: int = Field(default=12, ge=1, le=18)
    adjustment_period: bool = True
    name: str | None = Field(default=None, max_length=40)


class FiscalYearOut(Schema):
    id: UUID
    name: str
    start_date: date
    end_date: date
    status: str
    periods: list[PeriodOut]


class PeriodStatusIn(Schema):
    status: Literal["OPEN", "SOFT_CLOSED", "LOCKED"]


def _fy_out(year: FiscalYear) -> FiscalYearOut:
    return FiscalYearOut(
        id=year.id,
        name=year.name,
        start_date=year.start_date,
        end_date=year.end_date,
        status=year.status,
        periods=[PeriodOut.from_orm(p) for p in sorted(year.periods.all(), key=lambda p: p.number)],
    )


# --- chart of accounts ---------------------------------------------------------------------------


@router.get(f"{BASE}/accounts", response=list[AccountOut])
@requires("ledger.account.read")
def list_accounts(request: HttpRequest, slug: str, entity_id: UUID) -> list[Account]:
    return accounts.list_accounts(workspace_ctx(request, slug, entity_id), entity_id)


@router.post(f"{BASE}/accounts", response={201: AccountOut})
@requires("ledger.account.manage")
def create_account(
    request: HttpRequest, slug: str, entity_id: UUID, payload: AccountIn
) -> Status[Account]:
    ctx = workspace_ctx(request, slug, entity_id)
    data = accounts.AccountInput(**payload.dict())
    return Status(201, accounts.create_account(ctx, entity_id, data))


@router.get(f"{BASE}/accounts/{{uuid:account_id}}", response=AccountOut)
@requires("ledger.account.read")
def get_account(request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID) -> Account:
    return accounts.get_account(workspace_ctx(request, slug, entity_id), entity_id, account_id)


@router.patch(f"{BASE}/accounts/{{uuid:account_id}}", response=AccountOut)
@requires("ledger.account.manage")
def update_account(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, payload: AccountPatch
) -> Account:
    ctx = workspace_ctx(request, slug, entity_id)
    return accounts.update_account(ctx, entity_id, account_id, **payload.dict(exclude_unset=True))


@router.post(f"{BASE}/accounts/apply-template", response={201: list[AccountOut]})
@requires("ledger.account.manage")
def apply_template(
    request: HttpRequest, slug: str, entity_id: UUID, payload: TemplateIn
) -> Status[list[Account]]:
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, accounts.apply_template(ctx, entity_id, payload.template))


# --- fiscal years and periods ----------------------------------------------------------------


@router.get(f"{BASE}/fiscal-years", response=list[FiscalYearOut])
@requires("ledger.period.read")
def list_fiscal_years(request: HttpRequest, slug: str, entity_id: UUID) -> list[FiscalYearOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_fy_out(y) for y in periods.list_fiscal_years(ctx, entity_id)]


@router.post(f"{BASE}/fiscal-years", response={201: FiscalYearOut})
@requires("ledger.period.manage")
def create_fiscal_year(
    request: HttpRequest, slug: str, entity_id: UUID, payload: FiscalYearIn
) -> Status[FiscalYearOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    year = periods.create_fiscal_year(ctx, entity_id, **payload.dict())
    return Status(201, _fy_out(year))


@router.post(f"{BASE}/periods/{{uuid:period_id}}/status", response=PeriodOut)
@requires("ledger.period.read")
def change_period_status(
    request: HttpRequest, slug: str, entity_id: UUID, period_id: UUID, payload: PeriodStatusIn
) -> Period:
    # The transition-specific permission (manage or lock) is enforced by the service.
    ctx = workspace_ctx(request, slug, entity_id)
    return periods.change_status(ctx, entity_id, period_id, payload.status)
