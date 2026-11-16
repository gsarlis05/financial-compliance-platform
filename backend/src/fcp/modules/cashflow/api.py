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
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.metrics.api import Nature
from fcp.modules.tenancy.api import workspace_ctx

from . import services, tracking, whatif
from .engine import KIND
from .services import Forecast, prepare, run_forecast
from .services import latest as latest_cash_forecast

__all__ = ["KIND", "Forecast", "latest_cash_forecast", "prepare", "router", "run_forecast"]

router = Router(tags=["cashflow"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
AMOUNT = r"^\d{1,15}(\.\d{1,2})?$"
SIGNED = r"^-?\d{1,15}(\.\d{1,2})?$"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class RunIn(Schema):
    as_of: date | None = Field(None, description="Defaults to today")


class ForecastFlowOut(Schema):
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
    flows: list[ForecastFlowOut]


class ShortfallOut(Schema):
    date: date
    balance: str


class ForecastOut(Schema):
    run_id: UUID
    status: str
    as_of: date
    actuals_watermark: int
    stale: bool
    stale_reasons: list[str] = Field(
        default_factory=list, description="Why it is out of date (checked now)"
    )
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
                    ForecastFlowOut(direction=d, category=c, nature=Nature(n), amount=_money(v))  # type: ignore[arg-type]
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
    """The latest forecast, with whether it is out of date now (new postings, changed inputs or
    a passed as-of date)."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.latest(ctx, entity_id)
    out = _out(found)
    fresh = tracking.freshness(ctx, entity_id, found.run)
    out.stale, out.stale_reasons = fresh.stale, list(fresh.reasons)
    return out


@router.post(f"{BASE}/cash-forecasts/refresh", response={200: ForecastOut, 204: None})
@requires("planning.run")
def refresh_forecast(request: HttpRequest, slug: str, entity_id: UUID) -> Any:
    """Re-run now if the latest forecast is out of date (204 when it is current)."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = tracking.refresh(ctx, entity_id, trigger="USER")
    if made is None:
        return Status(204, None)
    return Status(200, _out(services.forecast_of(made)))


class ForecastHistoryOut(Schema):
    run_id: UUID
    as_of: date
    created_at: datetime
    status: str
    stale: bool
    trigger: str
    supersedes_id: UUID | None
    actuals_watermark: int
    opening_cash: str
    closing_week_13: str
    first_shortfall: date | None


class HistoryQuery(Schema):
    limit: int = Field(20, ge=1, le=100)


@router.get(f"{BASE}/cash-forecasts/history", response=list[ForecastHistoryOut])
@requires("planning.read")
def forecast_history(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[HistoryQuery]
) -> list[ForecastHistoryOut]:
    """Earlier forecasts, newest first: every run is kept (doc 10 §3.4)."""
    ctx = workspace_ctx(request, slug, entity_id)
    rows = []
    for f in tracking.history(ctx, entity_id, q.limit):
        row = tracking.summary(f)
        rows.append(
            ForecastHistoryOut(
                **{
                    **row,
                    "opening_cash": _money(row["opening_cash"]),
                    "closing_week_13": _money(row["closing_week_13"]),
                }
            )
        )
    return rows


class AccuracyQuery(Schema):
    as_of: date | None = Field(None, description="Defaults to today")
    weeks: int = Field(13, ge=1, le=52)


class ComparisonOut(Schema):
    horizon_weeks: int
    run_id: UUID
    forecast: str
    error: str
    ape_percent: str | None = Field(description="Not meaningful (null) when the actual is 0")


class AccuracyWeekOut(Schema):
    label: str
    start: date
    actual: str
    comparisons: list[ComparisonOut]


class AccuracyOut(Schema):
    weeks: list[AccuracyWeekOut]
    mape_percent: dict[str, str | None] = Field(description="By horizon in weeks")
    samples: dict[str, int]
    note: str


@router.get(f"{BASE}/cash-forecasts/accuracy", response=AccuracyOut)
@requires("planning.read")
def forecast_accuracy(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[AccuracyQuery]
) -> AccuracyOut:
    """For each full week, the net cash movement forecast 1, 4 and 13 weeks earlier against the
    actual movement on the cash accounts (reported, not gated)."""
    ctx = workspace_ctx(request, slug, entity_id)
    result = tracking.accuracy(ctx, entity_id, q.as_of or timezone.localdate(), q.weeks)
    pct = Decimal("0.01")
    return AccuracyOut(
        weeks=[
            AccuracyWeekOut(
                label=w.label,
                start=w.start,
                actual=_money(w.actual),
                comparisons=[
                    ComparisonOut(
                        horizon_weeks=c.horizon,
                        run_id=c.run_id,
                        forecast=_money(c.forecast),
                        error=_money(c.error),
                        ape_percent=None if c.ape is None else f"{(c.ape * 100).quantize(pct)}",
                    )
                    for c in w.comparisons
                ],
            )
            for w in result.weeks
        ],
        mape_percent={str(h): None if v is None else f"{v}" for h, v in result.mape.items()},
        samples={str(h): n for h, n in result.samples.items()},
        note="Net cash movement in total; actual bank movements are not yet categorised.",
    )


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


class OverrideIn(Schema):
    type: Literal["TIMING_SHIFT", "PCT_CHANGE", "ONE_OFF"]
    party: str = Field("", max_length=30, description="Customer or supplier code")
    category: str = Field("", max_length=20)
    days: int = Field(0, ge=-365, le=365)
    percent: str = Field("0", pattern=r"^-?\d{1,4}(\.\d{1,2})?$")
    day: date | None = None
    amount: str = Field("0", pattern=SIGNED)
    reason: str = Field("", max_length=200)


class WhatIfIn(Schema):
    overrides: list[OverrideIn] = Field(min_length=1, max_length=whatif.MAX_OVERRIDES)


class WhatIfWeekOut(Schema):
    label: str
    start: date
    base_closing: str
    what_if_closing: str
    delta: str
    base_net: str
    what_if_net: str
    base_shortfall: bool
    what_if_shortfall: bool


class WhatIfOut(Schema):
    run_id: UUID
    as_of: date
    nature: Nature = Field(Nature.HYPOTHETICAL, description="A what-if is never saved")
    saved: bool = False
    matched: list[int] = Field(description="Flows each override changed or added")
    base_first_shortfall: ShortfallOut | None
    what_if_first_shortfall: ShortfallOut | None
    hypothetical_total: str
    weeks: list[WhatIfWeekOut]


def _shortfall(value: tuple[date, Decimal] | None) -> ShortfallOut | None:
    return None if value is None else ShortfallOut(date=value[0], balance=_money(value[1]))


@router.post(f"{BASE}/cash-forecasts/{{uuid:run_id}}/what-if", response=WhatIfOut)
@requires("planning.read")
def forecast_what_if(
    request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID, body: WhatIfIn
) -> WhatIfOut:
    """The forecast under hypothetical changes, week by week against the base. Computed on
    request and never saved: the base run is unchanged (AC-CW7)."""
    ctx = workspace_ctx(request, slug, entity_id)
    run = services.forecast(ctx, entity_id, run_id).run
    overrides = [
        whatif.Override(
            o.type,
            o.party.strip(),
            o.category.strip(),
            o.days,
            Decimal(o.percent),
            o.day,
            Decimal(o.amount),
            o.reason,
        )
        for o in body.overrides
    ]
    result = whatif.what_if(ctx, run, overrides)
    weeks = [
        WhatIfWeekOut(
            label=b.label,
            start=b.start,
            base_closing=_money(b.closing),
            what_if_closing=_money(w.closing),
            delta=_money(w.closing - b.closing),
            base_net=_money(b.net),
            what_if_net=_money(w.net),
            base_shortfall=b.shortfall,
            what_if_shortfall=w.shortfall,
        )
        for b, w in zip(result.base.weeks, result.scenario.weeks, strict=True)
    ]
    return WhatIfOut(
        run_id=run.id,
        nature=Nature.HYPOTHETICAL,
        saved=False,
        as_of=run.as_of_date,
        matched=result.matched,
        base_first_shortfall=_shortfall(result.base.first_shortfall),
        what_if_first_shortfall=_shortfall(result.scenario.first_shortfall),
        hypothetical_total=_money(result.scenario.hypothetical),
        weeks=weeks,
    )
