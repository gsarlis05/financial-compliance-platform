"""Public interface of the ``cashflow`` module and its HTTP routes (M3-7: 13-week forecast).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``. Every amount carries its
nature (doc 10 P2), and every forecast is a reproducible calculation run (ADR-0017).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest
from django.utils import timezone
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.metrics.api import Nature
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .engine import KIND
from .services import Forecast, prepare, run_forecast

__all__ = ["KIND", "Forecast", "prepare", "router", "run_forecast"]

router = Router(tags=["cashflow"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
AMOUNT = r"^\d{1,15}(\.\d{1,2})?$"
SIGNED = r"^-?\d{1,15}(\.\d{1,2})?$"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class RunIn(Schema):
    as_of: date | None = Field(None, description="Defaults to today")


class FlowOut(Schema):
    direction: Literal["IN", "OUT"]
    category: str
    nature: Nature
    amount: str


class WeekOut(Schema):
    index: int
    label: str
    start: date
    end: date
    opening: str
    opening_nature: Nature
    inflows: str
    outflows: str
    net: str
    closing: str
    minimum: str
    headroom: str
    undrawn_facilities: str
    liquidity: str
    shortfall: bool
    nature: Nature = Field(description="Totals mix natures, so they are FORECAST")
    flows: list[FlowOut]


class ShortfallOut(Schema):
    date: date
    balance: str


class ForecastOut(Schema):
    run_id: UUID
    status: str
    as_of: date
    actuals_watermark: int
    stale: bool
    is_published: bool
    created_at: datetime
    output_hash: str
    opening_cash: str
    opening_accounts: dict[str, str]
    overdue: str
    beyond_horizon: str
    first_shortfall: ShortfallOut | None
    warnings: list[dict[str, Any]]
    weeks: list[WeekOut]


def _out(f: Forecast) -> ForecastOut:
    weeks = []
    for w in f.weeks:
        a = w.amounts
        weeks.append(
            WeekOut(
                index=w.index,
                label=w.label,
                start=w.start,
                end=w.end,
                opening=_money(a.get("opening", Decimal(0))),
                opening_nature=Nature.ACTUAL if w.index == 1 else Nature.FORECAST,
                inflows=_money(a.get("inflows", Decimal(0))),
                outflows=_money(a.get("outflows", Decimal(0))),
                net=_money(a.get("net", Decimal(0))),
                closing=_money(a.get("closing", Decimal(0))),
                minimum=_money(a.get("minimum", Decimal(0))),
                headroom=_money(a.get("headroom", Decimal(0))),
                undrawn_facilities=_money(a.get("undrawn_facilities", Decimal(0))),
                liquidity=_money(a.get("liquidity", Decimal(0))),
                shortfall=a.get("shortfall", Decimal(0)) > 0,
                nature=Nature.FORECAST,
                flows=[
                    FlowOut(direction=d, category=c, nature=Nature(n), amount=_money(v))  # type: ignore[arg-type]
                    for d, c, n, v in w.flows
                ],
            )
        )
    return ForecastOut(
        run_id=f.run.id,
        status=f.run.status,
        as_of=f.run.as_of_date,
        actuals_watermark=f.run.actuals_watermark,
        stale=f.run.stale,
        is_published=f.run.is_published,
        created_at=f.run.created_at,
        output_hash=f.run.output_hash,
        opening_cash=_money(sum(f.opening_accounts.values(), Decimal(0))),
        opening_accounts={k: _money(v) for k, v in f.opening_accounts.items()},
        overdue=_money(f.overdue),
        beyond_horizon=_money(f.beyond_horizon),
        first_shortfall=ShortfallOut(
            date=f.first_shortfall[0], balance=_money(f.first_shortfall[1])
        )
        if f.first_shortfall
        else None,
        warnings=f.warnings,
        weeks=weeks,
    )


@router.post(f"{BASE}/cash-forecasts", response={201: ForecastOut})
@requires("planning.run")
def create_forecast(
    request: HttpRequest, slug: str, entity_id: UUID, body: RunIn
) -> Status[ForecastOut]:
    """Run the 13-week forecast now (a new, reproducible calculation run)."""
    ctx = workspace_ctx(request, slug, entity_id)
    run = run_forecast(ctx, entity_id, body.as_of or timezone.localdate())
    return Status(201, _out(services.forecast_of(run)))


@router.get(f"{BASE}/cash-forecasts/latest", response=ForecastOut)
@requires("planning.read")
def latest_forecast(request: HttpRequest, slug: str, entity_id: UUID) -> ForecastOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.latest(ctx, entity_id))


@router.get(f"{BASE}/cash-forecasts/{{uuid:run_id}}", response=ForecastOut)
@requires("planning.read")
def get_forecast(request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID) -> ForecastOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.forecast(ctx, entity_id, run_id))


class SettingsIO(Schema):
    minimum_cash: str = Field("0.00", pattern=AMOUNT)
    unreconciled_warning_days: int = Field(7, ge=0, le=365)
    payables_policy: Literal["DUE_DATE", "WEEKDAY"] = "DUE_DATE"
    payables_weekday: int = Field(4, ge=0, le=6, description="0 Monday … 6 Sunday")


def _settings_out(s: services.SettingsView) -> SettingsIO:
    return SettingsIO(
        minimum_cash=_money(s.minimum_cash),
        unreconciled_warning_days=s.unreconciled_warning_days,
        payables_policy=s.payables_policy,  # type: ignore[arg-type]
        payables_weekday=s.payables_weekday,
    )


@router.get(f"{BASE}/cash-forecast-settings", response=SettingsIO)
@requires("planning.read")
def get_settings(request: HttpRequest, slug: str, entity_id: UUID) -> SettingsIO:
    ctx = workspace_ctx(request, slug, entity_id)
    return _settings_out(services.get_settings(ctx, entity_id))


@router.put(f"{BASE}/cash-forecast-settings", response=SettingsIO)
@requires("planning.run")
def put_settings(request: HttpRequest, slug: str, entity_id: UUID, body: SettingsIO) -> SettingsIO:
    ctx = workspace_ctx(request, slug, entity_id)
    return _settings_out(
        services.save_settings(
            ctx,
            entity_id,
            services.SettingsView(
                Decimal(body.minimum_cash),
                body.unreconciled_warning_days,
                body.payables_policy,
                body.payables_weekday,
            ),
        )
    )


class ManualIn(Schema):
    day: date
    amount: str = Field(pattern=SIGNED, description="Receipts positive, payments negative")
    category: Literal[
        "CUSTOMERS", "SUPPLIERS", "PAYROLL", "RENT", "TAX", "FINANCING", "CAPEX", "GRANT", "OTHER"
    ]
    reason: str = Field(min_length=1, max_length=300)


class ManualOut(Schema):
    id: UUID
    day: date
    amount: str
    category: str
    reason: str
    nature: Literal["EXPECTED"] = "EXPECTED"


@router.get(f"{BASE}/cash-items", response=list[ManualOut])
@requires("planning.read")
def list_manual(request: HttpRequest, slug: str, entity_id: UUID) -> list[ManualOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        ManualOut(id=m.id, day=m.day, amount=_money(m.amount), category=m.category, reason=m.reason)
        for m in services.manual_items(ctx, entity_id)
    ]


@router.post(f"{BASE}/cash-items", response={201: ManualOut})
@requires("planning.run")
def add_manual(
    request: HttpRequest, slug: str, entity_id: UUID, body: ManualIn
) -> Status[ManualOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    m = services.add_manual_item(
        ctx, entity_id, body.day, Decimal(body.amount), body.category, body.reason
    )
    return Status(
        201,
        ManualOut(
            id=m.id, day=m.day, amount=_money(m.amount), category=m.category, reason=m.reason
        ),
    )


@router.delete(f"{BASE}/cash-items/{{uuid:item_id}}", response={204: None})
@requires("planning.run")
def remove_manual(request: HttpRequest, slug: str, entity_id: UUID, item_id: UUID) -> Status[None]:
    ctx = workspace_ctx(request, slug, entity_id)
    services.remove_manual_item(ctx, entity_id, item_id)
    return Status(204, None)
