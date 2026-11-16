"""Public interface of the ``reporting`` module: the read gateway to historical figures.

ADR-0007: planning and CFO modules (``metrics``, ``cashflow``, ``budgeting``, ...) never import the
ledger; they read actuals only through this module. M2-6 adds account balances; M2-7 adds the
``reporting.actuals`` read model (monthly facts and daily cash).
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.http import HttpRequest
from ninja import Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.core.errors import ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger.api import (
    DimensionTotal,
    account_list,
    dimension_list,
    fiscal_year_list,
    posted_dimension_totals,
    trial_balance_rows,
    unposted_entries,
)
from fcp.modules.tenancy.api import WorkspaceContext, get_entity, workspace_ctx

from . import actuals
from .actuals import Actuals, Drift, Fact, WatermarkError

__all__ = [
    "AccountActivity",
    "AccountRef",
    "Actuals",
    "DimensionTotal",
    "DimensionValueRef",
    "Fact",
    "FiscalYearRef",
    "WatermarkError",
    "account_activity",
    "accounts",
    "actuals_monthly",
    "balances_before",
    "cash_daily",
    "current_watermark",
    "dimension_actuals",
    "dimension_values",
    "fiscal_year_start",
    "fiscal_years",
    "opening_net",
    "posted_since",
    "router",
    "unposted_count",
]

router = Router(tags=["reporting"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


@dataclass(frozen=True)
class AccountRef:
    id: UUID
    code: str
    name: str
    name_el: str
    type: str
    normal_side: str
    is_postable: bool
    status: str


@dataclass(frozen=True)
class AccountActivity:
    account_id: UUID
    debit_total: Decimal
    credit_total: Decimal

    @property
    def has_activity(self) -> bool:
        return bool(self.debit_total or self.credit_total)

    @property
    def net_debit(self) -> Decimal:
        return self.debit_total - self.credit_total


def accounts(ctx: WorkspaceContext, entity_id: UUID) -> list[AccountRef]:
    """The entity's chart of accounts (requires ``ledger.account.read``)."""
    return [
        AccountRef(a.id, a.code, a.name, a.name_el, a.type, a.normal_side, a.is_postable, a.status)
        for a in account_list(ctx, entity_id)
    ]


@dataclass(frozen=True)
class FiscalYearRef:
    id: UUID
    name: str
    start_date: date
    end_date: date
    status: str


def fiscal_years(ctx: WorkspaceContext, entity_id: UUID) -> list[FiscalYearRef]:
    """The entity's fiscal years, earliest first (requires ``ledger.period.read``)."""
    return [
        FiscalYearRef(y.id, y.name, y.start_date, y.end_date, y.status)
        for y in fiscal_year_list(ctx, entity_id)
    ]


@dataclass(frozen=True)
class DimensionValueRef:
    id: UUID
    dimension_id: UUID
    dimension_code: str
    dimension_kind: str
    code: str
    name: str
    status: str


def dimension_values(ctx: WorkspaceContext, entity_id: UUID) -> list[DimensionValueRef]:
    """Every value of every dimension of the entity (requires ``ledger.account.read``)."""
    return [
        DimensionValueRef(v.id, d.id, d.code, d.kind, v.code, v.name, v.status)
        for d in dimension_list(ctx, entity_id)
        for v in sorted(d.values.all(), key=lambda v: v.code)
    ]


def dimension_actuals(  # noqa: PLR0913 (keyword-only filters)
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    date_from: date,
    date_to: date,
    value_ids: list[UUID],
    watermark: int | None = None,
    permission: str = "reports.read",
) -> list[DimensionTotal]:
    """Monthly posted totals per account for lines tagged with these dimension values (closing
    entries excluded), for department and project actuals (M4-3)."""
    return posted_dimension_totals(ctx, entity_id, date_from=date_from, date_to=date_to,
                                   value_ids=value_ids, watermark=watermark,
                                   permission=permission)  # fmt: skip


def unposted_count(ctx: WorkspaceContext, entity_id: UUID, *, date_from: date,
                   date_to: date) -> int:  # fmt: skip
    """How many entries dated in the range are not posted (they are not in any actuals)."""
    return unposted_entries(ctx, entity_id, date_from=date_from, date_to=date_to)


def account_activity(
    ctx: WorkspaceContext, entity_id: UUID, *, as_of: date
) -> dict[UUID, AccountActivity]:
    """Posted totals per postable account up to ``as_of`` (requires ``reports.read``)."""
    return {
        r.account_id: AccountActivity(r.account_id, r.debit_total, r.credit_total)
        for r in trial_balance_rows(ctx, entity_id, as_of=as_of)
    }


# --- reporting.actuals (M2-7) ---------------------------------------------------------------------


# With ``watermark``, these return the actuals exactly as they were at that ledger watermark
# (``WatermarkError`` if it was never reached): calculation runs pin it to be reproducible.


def current_watermark(ctx: WorkspaceContext, entity_id: UUID,
                      permission: str = "reports.read") -> int:  # fmt: skip
    """The highest posting sequence included in the actuals now (refreshing them first).
    ``budget.department`` lets a department owner pin their department's actuals."""
    if permission not in ("reports.read", "budget.department"):
        raise ValueError(f"unsupported permission {permission!r}")
    get_entity(ctx, entity_id, permission)
    return actuals.refresh(ctx.tenant.id)


def posted_since(ctx: WorkspaceContext, entity_id: UUID, watermark: int) -> bool:
    """Whether the entity's actuals changed after ``watermark`` (requires ``reports.read``)."""
    entity = get_entity(ctx, entity_id, "reports.read")
    return actuals.posted_since(entity.id, ctx.tenant.id, watermark)


def actuals_monthly(ctx: WorkspaceContext, entity_id: UUID, *, date_from: date,
                    date_to: date, watermark: int | None = None) -> Actuals:  # fmt: skip
    """Monthly debit/credit totals per account, with the watermark they include."""
    entity = get_entity(ctx, entity_id, "reports.read")
    return actuals.monthly(entity.id, ctx.tenant.id, date_from=date_from, date_to=date_to,
                           watermark=watermark)  # fmt: skip


def cash_daily(ctx: WorkspaceContext, entity_id: UUID, *, account_ids: list[UUID], date_from: date,
               date_to: date, watermark: int | None = None) -> Actuals:  # fmt: skip
    """Daily movements of the given (cash) accounts, with the watermark they include."""
    entity = get_entity(ctx, entity_id, "reports.read")
    return actuals.daily(entity.id, ctx.tenant.id, account_ids=account_ids,
                         date_from=date_from, date_to=date_to, watermark=watermark)  # fmt: skip


def opening_net(ctx: WorkspaceContext, entity_id: UUID, *, before: date,
                watermark: int | None = None) -> tuple[int, dict[UUID, Decimal]]:  # fmt: skip
    """Net debit balance per account from everything dated before ``before``."""
    entity = get_entity(ctx, entity_id, "reports.read")
    return actuals.net_before(entity.id, ctx.tenant.id, before=before, watermark=watermark)


def balances_before(
    ctx: WorkspaceContext, entity_id: UUID, cutoffs: list[date]
) -> tuple[int, actuals.Balances, actuals.Balances]:
    """Net debit balance per account from everything dated before each cut-off (one query), and
    the part of it from year-end closing entries."""
    entity = get_entity(ctx, entity_id, "reports.read")
    return actuals.net_before_many(entity.id, ctx.tenant.id, cutoffs=cutoffs)


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def fiscal_year_start(ctx: WorkspaceContext, entity_id: UUID, day: date) -> date:
    """First day of the fiscal year containing ``day``. Outside the fiscal years created so far,
    the nearest one is extended by whole years (statements may compare with a year never set up)."""
    years = fiscal_year_list(ctx, entity_id)
    if not years:
        raise ValidationFailedError(
            "Create a fiscal year before producing statements.",
            field_errors={"date_to": ["no fiscal year"]},
        )
    for year in years:
        if year.start_date <= day <= year.end_date:
            return year.start_date
    anchor = years[0].start_date if day < years[0].start_date else years[-1].start_date
    start = anchor
    while start > day:
        start = _shift_years(start, -1)
    while _shift_years(start, 1) <= day:
        start = _shift_years(start, 1)
    return start


class MonthlyQuery(Schema):
    date_from: date
    date_to: date


class FactOut(Schema):
    account_id: UUID
    account_code: str
    month: date
    debit: str
    credit: str
    net_debit: str


class MonthlyOut(Schema):
    watermark: int
    facts: list[FactOut]


@router.get(f"{BASE}/actuals/monthly", response=MonthlyOut)
@requires("reports.read")
def monthly_actuals(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[MonthlyQuery]
) -> MonthlyOut:
    ctx = workspace_ctx(request, slug, entity_id)
    result = actuals_monthly(ctx, entity_id, date_from=q.date_from, date_to=q.date_to)
    codes = {a.id: a.code for a in accounts(ctx, entity_id)}
    return MonthlyOut(
        watermark=result.watermark,
        facts=[FactOut(account_id=f.account_id, account_code=codes.get(f.account_id, "?"),
                       month=f.period, debit=f"{f.debit_total:.2f}", credit=f"{f.credit_total:.2f}",
                       net_debit=f"{f.net_debit:.2f}") for f in result.facts],
    )  # fmt: skip


class DriftOut(Schema):
    grain: str
    entity_id: UUID
    account_id: UUID
    period: date
    ledger_debit: str
    ledger_credit: str
    facts_debit: str
    facts_credit: str


class VerifyOut(Schema):
    watermark: int
    ok: bool
    checked_at: datetime
    drifts: list[DriftOut]


def _verify_out(watermark: int, drifts: list[Drift]) -> VerifyOut:
    return VerifyOut(
        watermark=watermark, ok=not drifts, checked_at=datetime.now().astimezone(),
        drifts=[DriftOut(grain=d.grain, entity_id=d.entity_id, account_id=d.account_id,
                         period=d.period, ledger_debit=f"{d.ledger[0]:.2f}",
                         ledger_credit=f"{d.ledger[1]:.2f}", facts_debit=f"{d.facts[0]:.2f}",
                         facts_credit=f"{d.facts[1]:.2f}") for d in drifts[:100]],
    )  # fmt: skip


@router.get("/w/{slug}/actuals/verify", response=VerifyOut)
@requires("admin.integrity.read")
def verify_actuals(request: HttpRequest, slug: str) -> VerifyOut:
    ctx = workspace_ctx(request, slug)
    return _verify_out(*actuals.verify(ctx.tenant.id))


@router.post("/w/{slug}/actuals/rebuild", response={200: VerifyOut})
@requires("admin.integrity.read")
def rebuild_actuals(request: HttpRequest, slug: str) -> Status[VerifyOut]:
    """Recompute the read model from the ledger, then verify it (safe: facts are derived)."""
    ctx = workspace_ctx(request, slug)
    watermark = actuals.rebuild(ctx.tenant.id)
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="reporting.actuals.rebuilt",
        subject_type="actuals",
        subject_id=ctx.tenant.id,
        changes={"watermark": watermark},
    )
    return Status(200, _verify_out(*actuals.verify(ctx.tenant.id)))
