"""Public interface of the ``projections`` module and its HTTP routes (M6-2: assumption sets;
M6-3: projections, published through the calculation-run routes; M6-4: rolling forecasts).

Routes are entity-scoped (``/api/w/{slug}/entities/{entity_id}/...``). Values are decimal strings:
amounts in money, percentages as e.g. ``35`` for 35%, days and months as numbers.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.metrics.api import CalcRun
from fcp.modules.tenancy.api import WorkspaceContext, workspace_ctx

from . import assumptions, outlook, rolling, runs
from .drivers import DRIVERS
from .models import AssumptionSet
from .outlook import projected_plan

__all__ = ["projected_plan", "router"]

router = Router(tags=["projections"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class AssumptionSetIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    cutover: date = Field(description="The last day of the last actual month")
    months: Literal[12, 24, 36] = 24
    start_from: Literal["ACTUALS", "BUDGET", "EMPTY"] = "ACTUALS"
    revenue_growth: str = Field(
        default="0", pattern=r"^-?\d{1,4}(\.\d{1,4})?$", description="% a year (actuals start)"
    )


class AssumptionSetOut(Schema):
    id: UUID
    family_id: UUID
    version: int
    name: str
    cutover: date
    months: int
    start_from: str
    note: str
    status: str = Field(description="DRAFT, APPROVED or SUPERSEDED")
    supersedes_id: UUID | None
    created_at: datetime
    approved_at: datetime | None


def _set_out(s: AssumptionSet) -> AssumptionSetOut:
    return AssumptionSetOut(
        id=s.id, family_id=s.family_id, version=s.version, name=s.name, cutover=s.cutover,
        months=s.months, start_from=s.start_from, note=s.note, status=s.status,
        supersedes_id=s.supersedes_id, created_at=s.created_at, approved_at=s.approved_at,
    )  # fmt: skip


class GridRowOut(Schema):
    driver: str
    line: str = Field(description="Taxonomy line, or empty for a single row")
    unit: str = Field(description="AMOUNT, PERCENT, DAYS or MONTHS")
    values: list[str]
    sources: list[str] = Field(description="ACTUALS, BUDGET, DEFAULT or MANUAL per month")


class GridOut(Schema):
    assumption_set: AssumptionSetOut
    months: list[date]
    rows: list[GridRowOut]
    nature: str = Field(default="FORECAST", description="Every value is a forecast assumption")


class ChangeIn(Schema):
    driver: str = Field(max_length=20)
    line: str = Field(default="", max_length=40)
    month: date
    value: str = Field(pattern=r"^-?\d{1,13}(\.\d{1,6})?$")


class ChangesIn(Schema):
    changes: list[ChangeIn] = Field(min_length=1, max_length=2000)


class RenameIn(Schema):
    name: str = Field(min_length=1, max_length=120)


@router.get(f"{BASE}/assumption-sets", response=list[AssumptionSetOut])
@requires("planning.read")
def list_sets(request: HttpRequest, slug: str, entity_id: UUID) -> list[AssumptionSetOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_set_out(s) for s in assumptions.sets(ctx, entity_id)]


@router.post(f"{BASE}/assumption-sets", response={201: AssumptionSetOut})
@requires("planning.run")
def create_set(request: HttpRequest, slug: str, entity_id: UUID,
               payload: AssumptionSetIn) -> Status[AssumptionSetOut]:  # fmt: skip
    """Start a draft set from last year's actuals, the approved budget, or empty."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = assumptions.create_set(ctx, entity_id, assumptions.NewSet(**payload.dict()))
    return Status(201, _set_out(made))


def _grid_out(g: assumptions.Grid) -> GridOut:
    return GridOut(
        assumption_set=_set_out(g.assumption_set), months=g.months,
        rows=[GridRowOut(driver=k, line=line, unit=unit, values=[f"{v.normalize():f}"
                                                                 for v in vals],
                         sources=srcs) for k, line, unit, vals, srcs in g.rows],
    )  # fmt: skip


@router.get(f"{BASE}/assumption-sets/{{uuid:set_id}}", response=GridOut)
@requires("planning.read")
def get_set(request: HttpRequest, slug: str, entity_id: UUID, set_id: UUID) -> GridOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _grid_out(assumptions.grid(ctx, entity_id, set_id))


@router.put(f"{BASE}/assumption-sets/{{uuid:set_id}}/values", response=GridOut)
@requires("planning.run")
def set_values(request: HttpRequest, slug: str, entity_id: UUID, set_id: UUID,
               payload: ChangesIn) -> GridOut:  # fmt: skip
    """Change values of a draft set (each becomes MANUAL)."""
    ctx = workspace_ctx(request, slug, entity_id)
    assumptions.set_values(ctx, entity_id, set_id, [
        assumptions.Change(c.driver, c.line, c.month, c.value) for c in payload.changes
    ])  # fmt: skip
    return _grid_out(assumptions.grid(ctx, entity_id, set_id))


@router.patch(f"{BASE}/assumption-sets/{{uuid:set_id}}", response=AssumptionSetOut)
@requires("planning.run")
def rename_set(request: HttpRequest, slug: str, entity_id: UUID, set_id: UUID,
               payload: RenameIn) -> AssumptionSetOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _set_out(assumptions.rename(ctx, entity_id, set_id, payload.name))


@router.post(f"{BASE}/assumption-sets/{{uuid:set_id}}/approve", response=AssumptionSetOut)
@requires("planning.publish")
def approve_set(request: HttpRequest, slug: str, entity_id: UUID,
                set_id: UUID) -> AssumptionSetOut:  # fmt: skip
    """Approve a draft: it never changes again; the family's earlier approved version is
    superseded."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _set_out(assumptions.approve(ctx, entity_id, set_id))


@router.post(f"{BASE}/assumption-sets/{{uuid:set_id}}/revise", response={201: AssumptionSetOut})
@requires("planning.run")
def revise_set(request: HttpRequest, slug: str, entity_id: UUID,
               set_id: UUID) -> Status[AssumptionSetOut]:  # fmt: skip
    """A new draft version with the same values."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _set_out(assumptions.revise(ctx, entity_id, set_id)))


class DriverOut(Schema):
    key: str
    unit: str
    lines: list[str]


@router.get(f"{BASE}/assumption-drivers", response=list[DriverOut])
@requires("planning.read")
def list_drivers(request: HttpRequest, slug: str, entity_id: UUID) -> list[DriverOut]:
    workspace_ctx(request, slug, entity_id)
    return [DriverOut(key=d.key, unit=d.unit, lines=list(d.lines)) for d in DRIVERS.values()]


# --- projections (M6-3) ---------------------------------------------------------------------------


class ProjectionIn(Schema):
    assumption_set_id: UUID


class ProjectionRunOut(Schema):
    id: UUID
    status: str = Field(description="VALID, INVALID (an invariant failed) or FAILED")
    as_of_date: date = Field(description="The cut-over")
    assumption_set_id: UUID | None
    actuals_watermark: int
    input_hash: str
    output_hash: str
    invariants: dict[str, bool]
    error: str
    stale: bool
    is_published: bool
    created_at: datetime


def _projection_out(run: CalcRun) -> ProjectionRunOut:
    set_id = run.input_refs.get("assumption_set_id")
    return ProjectionRunOut(
        id=run.id, status=run.status, as_of_date=run.as_of_date,
        assumption_set_id=UUID(set_id) if set_id else None,
        actuals_watermark=run.actuals_watermark, input_hash=run.input_hash,
        output_hash=run.output_hash, invariants=run.invariant_results, error=run.error,
        stale=run.stale, is_published=run.is_published, created_at=run.created_at,
    )  # fmt: skip


@router.get(f"{BASE}/projections", response=list[ProjectionRunOut])
@requires("planning.read")
def list_projections(request: HttpRequest, slug: str, entity_id: UUID) -> list[ProjectionRunOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_projection_out(r) for r in runs.projections(ctx, entity_id)]


@router.post(f"{BASE}/projections", response={201: ProjectionRunOut})
@requires("planning.run")
def run_projection(request: HttpRequest, slug: str, entity_id: UUID,
                   payload: ProjectionIn) -> Status[ProjectionRunOut]:  # fmt: skip
    """Project the three statements from an approved assumption set. A run that fails an
    invariant is INVALID and cannot be published; publish a VALID one through
    ``/calc-runs/{id}/publish``."""
    ctx = workspace_ctx(request, slug, entity_id)
    run = runs.run_projection(ctx, entity_id, payload.assumption_set_id)
    return Status(201, _projection_out(run))


def _cents(value: Decimal | None) -> str | None:
    """Every projected value is a whole number of cents (doc 10 §2.4)."""
    return None if value is None else str(value.quantize(Decimal("0.01")))


class ProjectionStatementsQuery(Schema):
    granularity: Literal["MONTH", "QUARTER", "YEAR"] = "MONTH"


class ColumnOut(Schema):
    start: date
    end: date
    nature: str = Field(description="ACTUAL for the opening balance sheet, FORECAST otherwise")


class ProjectionStatementsOut(Schema):
    projection: ProjectionRunOut
    columns: list[ColumnOut]
    rows: dict[str, list[str | None]] = Field(description="Series key: a decimal string per column")
    failures: list[str] = Field(description="Failed invariants, as invariant@where")


@router.get(f"{BASE}/projections/{{uuid:run_id}}", response=ProjectionStatementsOut)
@requires("planning.read")
def get_projection(request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID,
                   query: Query[ProjectionStatementsQuery]) -> ProjectionStatementsOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    found = runs.statements(ctx, entity_id, run_id, query.granularity)
    return ProjectionStatementsOut(
        projection=_projection_out(found.run),
        columns=[ColumnOut(start=c.start, end=c.end, nature=c.nature) for c in found.columns],
        rows={k: [_cents(v) for v in vs] for k, vs in found.rows.items()},
        failures=found.failures,
    )  # fmt: skip


# --- rolling forecasts (M6-4) ---------------------------------------------------------------------


class RollingIn(Schema):
    assumption_set_id: UUID = Field(description="Any version; its family's approved one is used")
    horizon: Literal[12, 24] = 12
    active: bool = True


class RollingOut(Schema):
    configured: bool
    family_id: UUID | None = None
    assumption_set_id: UUID | None = Field(None, description="The approved version in use")
    horizon: int | None = None
    active: bool = False
    latest: ProjectionRunOut | None = None
    stale: bool = False
    stale_reasons: list[str] = Field(default_factory=list)
    history: list[ProjectionRunOut] = Field(default_factory=list)


def _rolling_out(ctx: WorkspaceContext, entity_id: UUID) -> RollingOut:
    found = rolling.setting(ctx, entity_id)
    if found is None:
        return RollingOut(configured=False, assumption_set_id=None)
    done = [r for r in rolling.runs_of(ctx, entity_id, found, 50) if r.status in rolling.FINISHED]
    latest = done[0] if done else None
    fresh = rolling.freshness(ctx, entity_id, found, latest) if latest else None
    current = rolling.approved_version(found.legal_entity_id, found.family_id)
    return RollingOut(
        configured=True, family_id=found.family_id,
        assumption_set_id=current.id if current else None, horizon=found.horizon,
        active=found.active, latest=_projection_out(latest) if latest else None,
        stale=fresh.stale if fresh else True,
        stale_reasons=list(fresh.reasons) if fresh else ["not run yet"],
        history=[_projection_out(r) for r in done],
    )  # fmt: skip


@router.get(f"{BASE}/rolling-forecast", response=RollingOut)
@requires("planning.read")
def get_rolling(request: HttpRequest, slug: str, entity_id: UUID) -> RollingOut:
    """The setting, the latest run, whether it is stale and why, and the earlier runs."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _rolling_out(ctx, entity_id)


@router.put(f"{BASE}/rolling-forecast", response=RollingOut)
@requires("planning.run")
def put_rolling(request: HttpRequest, slug: str, entity_id: UUID,
                payload: RollingIn) -> RollingOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    rolling.configure(ctx, entity_id, payload.assumption_set_id, payload.horizon, payload.active)
    return _rolling_out(ctx, entity_id)


@router.post(f"{BASE}/rolling-forecast/refresh", response=RollingOut)
@requires("planning.run")
def refresh_rolling(request: HttpRequest, slug: str, entity_id: UUID) -> RollingOut:
    """Re-run now if the latest run is stale (the scheduled job does the same every hour)."""
    ctx = workspace_ctx(request, slug, entity_id)
    rolling.refresh(ctx, entity_id, trigger=CalcRun.Trigger.USER)
    return _rolling_out(ctx, entity_id)


class ForecastComparisonOut(Schema):
    months_before: int
    run_id: UUID
    forecast: str
    error: str
    error_pct: str | None = Field(description="|error| / |actual| in %; null when actual is 0")


class AccuracyMonthOut(Schema):
    month: date
    actual: dict[str, str]
    comparisons: dict[str, list[ForecastComparisonOut]]


@router.get(f"{BASE}/rolling-forecast/accuracy", response=list[AccuracyMonthOut])
@requires("planning.read")
def rolling_accuracy(request: HttpRequest, slug: str, entity_id: UUID) -> list[AccuracyMonthOut]:
    """For each of the last 12 closed months: revenue, EBITDA and closing cash as forecast 1, 3
    and 6 months earlier, against the actual."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        AccuracyMonthOut(
            month=m.month,
            actual={k: str(v.quantize(Decimal("0.01"))) for k, v in m.actual.items()},
            comparisons={k: [ForecastComparisonOut(months_before=c.horizon, run_id=c.run_id,
                                           forecast=str(c.forecast.quantize(Decimal("0.01"))),
                                           error=str(c.error.quantize(Decimal("0.01"))),
                                           error_pct=None if c.pct is None else str(c.pct))
                             for c in cs] for k, cs in m.comparisons.items()},
        )
        for m in rolling.accuracy(ctx, entity_id)
    ]  # fmt: skip


# --- the full-year outlook (M6-5) -----------------------------------------------------------------


class OutlookQuery(Schema):
    day: date = Field(description="Any day of the fiscal year to show")


class OutlookColumnOut(Schema):
    start: date
    end: date
    granularity: str = Field(description="MONTH, QUARTER or YEAR")
    nature: str = Field(description="ACTUAL, FORECAST, ACTUAL+FORECAST, or empty (not shown)")


class OutlookOut(Schema):
    year_start: date
    cutover: date | None = Field(description="The last actual month end (the divider)")
    projection_id: UUID | None
    note: str
    columns: list[OutlookColumnOut]
    rows: dict[str, list[str | None]] = Field(description="12 months, 4 quarters, the year")


@router.get(f"{BASE}/outlook", response=OutlookOut)
@requires("planning.read")
def get_outlook(request: HttpRequest, slug: str, entity_id: UUID,
                query: Query[OutlookQuery]) -> OutlookOut:  # fmt: skip
    """Actual months from the books and forecast months from the latest published projection,
    each column with its nature; quarters and the year are sums of their months."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = outlook.outlook(ctx, entity_id, query.day)
    return OutlookOut(
        year_start=found.year_start, cutover=found.cutover,
        projection_id=found.run.id if found.run else None, note=found.note,
        columns=[OutlookColumnOut(start=c.start, end=c.end, granularity=c.granularity,
                                  nature=c.nature) for c in found.columns],
        rows={k: [_cents(v) for v in vs] for k, vs in found.rows.items()},
    )  # fmt: skip
