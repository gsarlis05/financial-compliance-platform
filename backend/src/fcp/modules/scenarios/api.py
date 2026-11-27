"""Public interface of the ``scenarios`` module and its HTTP routes (M7-1: scenarios and their
typed overrides).

Routes are entity-scoped (``/api/w/{slug}/entities/{entity_id}/scenarios``). Reading needs
``planning.read``; changes need ``planning.run`` (archiving someone else's shared scenario also
``planning.publish``). Every figure a scenario produces is ``HYPOTHETICAL`` (runs: M7-2).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Field, Query, Router, Schema, Status

from fcp.core import reviews
from fcp.core.api.permissions import requires
from fcp.core.errors import ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.kpi.api import DEFAULT_LIBRARY
from fcp.modules.projections.api import SetInfo
from fcp.modules.tenancy.api import get_entity, workspace_ctx

from . import (
    exports,
    goal_outlooks,
    projected_kpis,
    sensitivity,
    sensitivity_runs,
    services,
    working_capital,
)
from . import runs as scenario_runs
from .models import Scenario, ScenarioOverride
from .overrides import MAX_OVERRIDES
from .runs import summary as scenario_summary

__all__ = ["OverrideType", "router", "scenario_summary"]

router = Router(tags=["scenarios"])
BASE = "/w/{slug}/entities/{uuid:entity_id}/scenarios"
OverrideType = Literal[
    "PCT_CHANGE", "ABS_CHANGE", "TIMING_SHIFT", "NEW_DEBT",
    "NEW_HIRE", "CAPEX", "ONE_OFF", "RATE_CHANGE",
]  # fmt: skip


class ScenarioIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    base_set_id: UUID = Field(description="An approved assumption set of the entity")
    description: str = Field(default="", max_length=1000)


class ScenarioRenameIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ScenarioCopyIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_set_id: UUID | None = Field(
        default=None, description="Another approved assumption set (rebase); default: the same"
    )


class ScenarioOverrideIn(Schema):
    type: OverrideType
    params: dict[str, Any] = Field(description="Parameters of the type (see the user guide)")
    rationale: str = Field(default="", max_length=1000)


class ScenarioOverrideOrderIn(Schema):
    order: list[UUID] = Field(min_length=1, max_length=MAX_OVERRIDES)


class ScenarioOverrideOut(Schema):
    id: UUID
    seq: int = Field(description="The order in which the override applies (1 first)")
    type: str
    params: dict[str, Any]
    rationale: str


class ScenarioOut(Schema):
    id: UUID
    name: str
    description: str
    status: str = Field(description="DRAFT, SHARED or ARCHIVED")
    base_set_id: UUID
    copied_from_id: UUID | None
    created_by_id: UUID
    created_at: datetime
    shared_at: datetime | None
    archived_at: datetime | None
    nature: str = Field(default="HYPOTHETICAL", description="Every scenario figure is hypothetical")


class ScenarioBaseOut(Schema):
    id: UUID
    name: str
    version: int
    status: str = Field(description="APPROVED, or SUPERSEDED when a newer version is approved")
    newer_version_approved: bool
    first_month: date
    last_month: date
    loans: list[str]


class ScenarioDetailOut(Schema):
    scenario: ScenarioOut
    base: ScenarioBaseOut
    overrides: list[ScenarioOverrideOut]


def _out(s: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=s.id, name=s.name, description=s.description, status=s.status,
        base_set_id=s.base_set_id, copied_from_id=s.copied_from_id, created_by_id=s.created_by_id,
        created_at=s.created_at, shared_at=s.shared_at, archived_at=s.archived_at,
    )  # fmt: skip


def _override_out(o: ScenarioOverride) -> ScenarioOverrideOut:
    return ScenarioOverrideOut(
        id=o.id, seq=o.seq, type=o.type, params=o.params, rationale=o.rationale
    )


def _detail_out(d: services.Detail) -> ScenarioDetailOut:
    b = d.base
    return ScenarioDetailOut(
        scenario=_out(d.scenario),
        base=_base_out(b),
        overrides=[_override_out(o) for o in d.overrides],
    )  # fmt: skip


@router.get(BASE, response=list[ScenarioOut])
@requires("planning.read")
def list_scenarios(request: HttpRequest, slug: str, entity_id: UUID) -> list[ScenarioOut]:
    """Your drafts, and every shared or archived scenario of the entity."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_out(s) for s in services.scenarios(ctx, entity_id)]


@router.post(BASE, response={201: ScenarioOut})
@requires("planning.run")
def create_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                    payload: ScenarioIn) -> Status[ScenarioOut]:  # fmt: skip
    """Start a draft scenario on an approved assumption set."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _out(services.create(ctx, entity_id, **payload.dict())))


@router.get(f"{BASE}/{{uuid:scenario_id}}", response=ScenarioDetailOut)
@requires("planning.read")
def get_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                 scenario_id: UUID) -> ScenarioDetailOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail_out(services.detail(ctx, entity_id, scenario_id))


@router.patch(f"{BASE}/{{uuid:scenario_id}}", response=ScenarioOut)
@requires("planning.run")
def rename_scenario(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                    payload: ScenarioRenameIn) -> ScenarioOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.rename(ctx, entity_id, scenario_id, **payload.dict()))


@router.post(f"{BASE}/{{uuid:scenario_id}}/overrides", response={201: ScenarioOverrideOut})
@requires("planning.run")
def add_override(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                 payload: ScenarioOverrideIn) -> Status[ScenarioOverrideOut]:  # fmt: skip
    """Add an override at the end of the list (it applies after the others)."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.add_override(ctx, entity_id, scenario_id, kind=payload.type,
                                 params=payload.params, rationale=payload.rationale)  # fmt: skip
    return Status(201, _override_out(made))


@router.put(
    f"{BASE}/{{uuid:scenario_id}}/overrides/{{uuid:override_id}}", response=ScenarioOverrideOut
)
@requires("planning.run")
def change_override(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                    override_id: UUID,
                    payload: ScenarioOverrideIn) -> ScenarioOverrideOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _override_out(services.change_override(
        ctx, entity_id, scenario_id, override_id, kind=payload.type, params=payload.params,
        rationale=payload.rationale))  # fmt: skip


@router.delete(f"{BASE}/{{uuid:scenario_id}}/overrides/{{uuid:override_id}}",
               response={204: None})  # fmt: skip
@requires("planning.run")
def remove_override(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                    override_id: UUID) -> Status[None]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    services.remove_override(ctx, entity_id, scenario_id, override_id)
    return Status(204, None)


@router.put(f"{BASE}/{{uuid:scenario_id}}/overrides", response=list[ScenarioOverrideOut])
@requires("planning.run")
def reorder_overrides(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                      payload: ScenarioOverrideOrderIn) -> list[ScenarioOverrideOut]:  # fmt: skip
    """Put the overrides in a new order: list every override's id once."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_override_out(o) for o in services.reorder(ctx, entity_id, scenario_id,
                                                       payload.order)]  # fmt: skip


@router.post(f"{BASE}/{{uuid:scenario_id}}/share", response=ScenarioOut)
@requires("planning.run")
def share_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                   scenario_id: UUID) -> ScenarioOut:  # fmt: skip
    """Make a draft visible to everyone who can read plans; it then never changes."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.share(ctx, entity_id, scenario_id))


@router.post(f"{BASE}/{{uuid:scenario_id}}/archive", response=ScenarioOut)
@requires("planning.run")
def archive_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                     scenario_id: UUID) -> ScenarioOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.archive(ctx, entity_id, scenario_id))


@router.post(f"{BASE}/{{uuid:scenario_id}}/copy", response={201: ScenarioOut})
@requires("planning.run")
def copy_scenario(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                  payload: ScenarioCopyIn) -> Status[ScenarioOut]:  # fmt: skip
    """A new draft with the same overrides, optionally on another approved base."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.copy(ctx, entity_id, scenario_id, name=payload.name,
                         base_set_id=payload.base_set_id)  # fmt: skip
    return Status(201, _out(made))


# --- runs, comparison and promotion (M7-2) -------------------------------------------------------


class ScenarioColumnOut(Schema):
    start: date
    end: date
    nature: str = Field(description="ACTUAL (the opening balance sheet) or HYPOTHETICAL")


class ScenarioRowOut(Schema):
    key: str = Field(description="Statement line, e.g. PL.REVENUE, BS.CASH, CF.OPERATING")
    base: list[str | None] = Field(description="The base (FORECAST) per column")
    scenario: list[str | None] = Field(description="The scenario (HYPOTHETICAL) per column")
    difference: list[str | None]
    overrides: list[list[str]] = Field(description="Per column: ids of the overrides that "
                                       "changed the value")  # fmt: skip


class ScenarioEffectOut(Schema):
    override_id: str | None = Field(description="None for the total row")
    seq: int | None
    type: str
    label: str
    changes: dict[str, str] = Field(
        description="Change in revenue, EBITDA, net income and net cash flow over the horizon, "
        "and in cash and debt at its end"
    )


class ScenarioLiquidityOut(Schema):
    lowest_cash: str
    lowest_cash_month: date | None
    first_negative_month: date | None
    months_below_minimum: int
    peak_facility: str
    closing_debt: str


class ScenarioComparisonOut(Schema):
    scenario: ScenarioOut
    base: ScenarioBaseOut
    watermark: int = Field(description="The comparison includes every posting up to this number")
    granularity: str
    columns: list[ScenarioColumnOut]
    rows: list[ScenarioRowOut]
    effects: list[ScenarioEffectOut] = Field(description="What changed and why")
    liquidity: dict[str, ScenarioLiquidityOut] = Field(description="base and scenario")
    valid: bool = Field(description="All eight projection invariants hold for the scenario")
    failures: list[str]
    notes: list[str]
    nature: str = "HYPOTHETICAL"
    engine_status: str = Field(default_factory=reviews.engine_status,
                               description="The projection engine's review status "
                               "(fcp.core.reviews)")  # fmt: skip


class ScenarioRunOut(Schema):
    id: UUID
    status: str
    created_at: datetime
    as_of_date: date
    actuals_watermark: int
    output_hash: str | None
    stale: bool


class ScenarioPromoteIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class ScenarioPromotedOut(Schema):
    assumption_set_id: UUID
    name: str
    status: str


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _base_out(b: SetInfo) -> ScenarioBaseOut:
    return ScenarioBaseOut(
        id=b.id, name=b.name, version=b.version, status=b.status,
        newer_version_approved=b.status == "SUPERSEDED", first_month=b.months[0],
        last_month=b.months[-1], loans=sorted(b.loan_codes),
    )  # fmt: skip


def _liquidity_out(x: scenario_runs.Liquidity) -> ScenarioLiquidityOut:
    return ScenarioLiquidityOut(
        lowest_cash=f"{x.lowest_cash:.2f}", lowest_cash_month=x.lowest_cash_month,
        first_negative_month=x.first_negative_month, months_below_minimum=x.months_below_minimum,
        peak_facility=f"{x.peak_facility:.2f}", closing_debt=f"{x.closing_debt:.2f}",
    )  # fmt: skip


@router.get(f"{BASE}/{{uuid:scenario_id}}/comparison", response=ScenarioComparisonOut)
@requires("planning.run")
def compare_scenario(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                     granularity: Literal["MONTH", "QUARTER", "YEAR"] = "MONTH",
                     ) -> ScenarioComparisonOut:  # fmt: skip
    """Run the scenario now and compare it with its base (not stored)."""
    ctx = workspace_ctx(request, slug, entity_id)
    c = scenario_runs.compare(ctx, entity_id, scenario_id, granularity)
    return ScenarioComparisonOut(
        scenario=_out(c.scenario), base=_base_out(c.base), watermark=c.watermark,
        granularity=granularity,
        columns=[ScenarioColumnOut(start=x.start, end=x.end, nature=x.nature) for x in c.columns],
        rows=[ScenarioRowOut(
            key=r.key, base=[_amount(v) for v in r.base],
            scenario=[_amount(v) for v in r.scenario],
            difference=[None if b is None or s is None else _amount(s - b)
                        for b, s in zip(r.base, r.scenario, strict=True)],
            overrides=r.overrides) for r in c.rows],
        effects=[ScenarioEffectOut(override_id=e.override_id, seq=e.seq, type=e.type,
                                   label=e.label,
                                   changes={k: f"{v:.2f}" for k, v in e.changes.items()})
                 for e in c.effects],
        liquidity={k: _liquidity_out(v) for k, v in c.liquidity.items()},
        valid=c.valid, failures=c.failures, notes=c.notes,
    )  # fmt: skip


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ScenarioExportQuery(Schema):
    granularity: Literal["MONTH", "QUARTER", "YEAR"] = "MONTH"
    lang: Literal["en", "el"] = "en"


@router.get(f"{BASE}/{{uuid:scenario_id}}/comparison/export")
@requires("reports.export")
def export_comparison(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                      query: Query[ScenarioExportQuery]) -> HttpResponse:  # fmt: skip
    """The comparison as XLSX: base, scenario and difference per period, a nature row above the
    figures and the change by override; audited."""
    ctx = workspace_ctx(request, slug, entity_id)
    entity = get_entity(ctx, entity_id, "reports.export")
    c = scenario_runs.compare(ctx, entity_id, scenario_id, query.granularity)
    content = exports.to_xlsx(c, entity.legal_name, query.granularity, query.lang,
                              generated=timezone.now())  # fmt: skip
    filename = f"scenario-comparison-{query.granularity.lower()}.xlsx"
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="reports.exported",
          subject_type="report", subject_id="scenario_comparison", entity_id=entity_id,
          changes={"format": "xlsx", "filename": filename, "scenario_id": str(scenario_id),
                   "watermark": c.watermark})  # fmt: skip
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _run_out(r: Any) -> ScenarioRunOut:
    return ScenarioRunOut(
        id=r.id, status=r.status, created_at=r.created_at, as_of_date=r.as_of_date,
        actuals_watermark=r.actuals_watermark,
        output_hash=r.output_hash or None, stale=r.stale,
    )  # fmt: skip


@router.post(f"{BASE}/{{uuid:scenario_id}}/runs", response={201: ScenarioRunOut})
@requires("planning.run")
def save_scenario_run(request: HttpRequest, slug: str, entity_id: UUID,
                      scenario_id: UUID) -> Status[ScenarioRunOut]:  # fmt: skip
    """Record the scenario's run (a calculation run of kind SCENARIO; never published). Its
    values are read through the calculation-run routes."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _run_out(scenario_runs.save(ctx, entity_id, scenario_id)))


@router.get(f"{BASE}/{{uuid:scenario_id}}/runs", response=list[ScenarioRunOut])
@requires("planning.read")
def list_scenario_runs(request: HttpRequest, slug: str, entity_id: UUID,
                       scenario_id: UUID) -> list[ScenarioRunOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return [_run_out(r) for r in scenario_runs.runs(ctx, entity_id, scenario_id)]


@router.post(f"{BASE}/{{uuid:scenario_id}}/promote", response={201: ScenarioPromotedOut})
@requires("planning.run")
def promote_scenario(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                     payload: ScenarioPromoteIn) -> Status[ScenarioPromotedOut]:  # fmt: skip
    """Create an assumption-set draft from the scenario; it needs the normal approval."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = scenario_runs.promote(ctx, entity_id, scenario_id, name=payload.name)
    return Status(201, ScenarioPromotedOut(assumption_set_id=made.id, name=made.name,
                                           status=made.status))  # fmt: skip


# --- sensitivity and tornado (M7-3) --------------------------------------------------------------

SENSITIVITY = "/w/{slug}/entities/{uuid:entity_id}/sensitivity"
Output = Literal["MIN_CASH", "CLOSING_CASH", "FIRST_SHORTFALL", "EBITDA", "NET_INCOME"]


class SensitivityBaseIn(Schema):
    base_set_id: UUID | None = Field(default=None, description="An approved assumption set")
    scenario_id: UUID | None = Field(default=None, description="Or a shared scenario")
    output: Output = "MIN_CASH"
    year: int | None = Field(
        default=None, ge=2000, le=2100, description="EBITDA and NET_INCOME: a year of the horizon"
    )


class OneVariableIn(SensitivityBaseIn):
    driver: str = Field(max_length=40, description="e.g. revenue, opex:OPEX.RENT, dso")
    unit: Literal["PERCENT", "DAYS"] = "PERCENT"
    low: str = Field(pattern=r"^-?\d{1,4}(\.\d{1,4})?$", description="% or days")
    high: str = Field(pattern=r"^-?\d{1,4}(\.\d{1,4})?$")
    steps: int = Field(default=5, ge=2, le=11)


class TornadoIn(SensitivityBaseIn):
    drivers: list[str] = Field(default_factory=list, max_length=25,
                               description="Empty: every driver the base uses")  # fmt: skip
    percent: str = Field(default="10", pattern=r"^\d{1,3}(\.\d{1,4})?$",
                         description="The shock, down and up")  # fmt: skip


class MeasureOut(Schema):
    value: str = Field(description="Money, or a number of months for FIRST_SHORTFALL")
    month: date | None = Field(description="The month of the lowest cash or first shortfall")


class SensitivityPointOut(Schema):
    shock: str = Field(description="% or days")
    result: MeasureOut
    change: str = Field(description="Against the base")


class TornadoBarOut(Schema):
    driver: str
    label: str
    low: MeasureOut
    high: MeasureOut
    swing: str


class SensitivityOut(Schema):
    kind: str
    output: str
    year: int | None
    base_label: str
    base: MeasureOut
    points: list[SensitivityPointOut]
    bars: list[TornadoBarOut] = Field(description="Ranked by swing, largest first")
    input_hash: str
    watermark: int
    cached: bool
    nature: str = "HYPOTHETICAL"
    engine_status: str = Field(default_factory=reviews.engine_status)


def _measure(m: sensitivity.Measure, output: str) -> MeasureOut:
    value = f"{m.value:.0f}" if output == "FIRST_SHORTFALL" else f"{m.value:.2f}"
    return MeasureOut(value=value, month=m.month)


def _analysis_out(a: sensitivity_runs.Analysis) -> SensitivityOut:
    o = a.output
    return SensitivityOut(
        kind=a.kind, output=o, year=a.year, base_label=a.base_label, base=_measure(a.base_value, o),
        points=[SensitivityPointOut(shock=f"{p.shock.normalize():f}", result=_measure(p.result, o),
                                    change=f"{p.result.value - a.base_value.value:.2f}")
                for p in a.points],
        bars=[TornadoBarOut(driver=b.driver, label=b.label, low=_measure(b.low, o),
                            high=_measure(b.high, o), swing=f"{b.swing:.2f}") for b in a.bars],
        input_hash=a.input_hash, watermark=a.watermark, cached=a.cached,
    )  # fmt: skip


@router.post(f"{SENSITIVITY}/one-variable", response=SensitivityOut)
@requires("planning.run")
def sensitivity_one_variable(request: HttpRequest, slug: str, entity_id: UUID,
                             payload: OneVariableIn) -> SensitivityOut:  # fmt: skip
    """One driver over a range (up to 11 steps): the output at each step. Not stored."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _analysis_out(sensitivity_runs.one_variable(
        ctx, entity_id, set_id=payload.base_set_id, scenario_id=payload.scenario_id,
        driver=payload.driver, unit=payload.unit, low=Decimal(payload.low),
        high=Decimal(payload.high), steps=payload.steps, output=payload.output, year=payload.year,
    ))  # fmt: skip


@router.post(f"{SENSITIVITY}/tornado", response=SensitivityOut)
@requires("planning.run")
def sensitivity_tornado(request: HttpRequest, slug: str, entity_id: UUID,
                        payload: TornadoIn) -> SensitivityOut:  # fmt: skip
    """Each driver shocked down and up on its own, ranked by the swing of the output."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _analysis_out(sensitivity_runs.tornado(
        ctx, entity_id, set_id=payload.base_set_id, scenario_id=payload.scenario_id,
        drivers=payload.drivers, percent=Decimal(payload.percent), output=payload.output,
        year=payload.year,
    ))  # fmt: skip


# --- working capital (M7-4) ----------------------------------------------------------------------

WORKING_CAPITAL = "/w/{slug}/entities/{uuid:entity_id}/working-capital"


class WorkingCapitalMonthOut(Schema):
    month: date
    receivables: str
    inventory: str
    payables: str
    net: str = Field(description="Receivables + inventory - payables")
    change: str = Field(description="Against the month before (the cut-over for the first)")
    cash_effect: str = Field(description="Working-capital lines of the cash flow statement")
    dso: str
    dio: str
    dpo: str
    ccc: str = Field(description="Cash conversion cycle: DSO + DIO - DPO")


class WorkingCapitalOut(Schema):
    base_label: str
    nature: str = Field(description="FORECAST (assumption set) or HYPOTHETICAL (scenario)")
    watermark: int
    cutover: date
    observed: dict[str, str] = Field(description="DSO, DIO and DPO over the 12 months to the "
                                     "cut-over")  # fmt: skip
    observed_ccc: str
    months: list[WorkingCapitalMonthOut]
    engine_status: str = Field(default_factory=reviews.engine_status)


class DaysWorthIn(Schema):
    base_set_id: UUID | None = None
    scenario_id: UUID | None = None
    driver: Literal["dso", "dio", "dpo"]
    days: int = Field(ge=-365, le=365, description="e.g. -10: customers pay 10 days sooner")


class DaysWorthOut(Schema):
    driver: str
    days: int
    closing_cash_change: str = Field(description="At the end of the horizon")
    lowest_cash_change: str
    net_working_capital_change: str = Field(description="Negative: cash released")
    by_month: list[dict[str, str]] = Field(description="The cash difference by month")
    nature: str = "HYPOTHETICAL"
    engine_status: str = Field(default_factory=reviews.engine_status)


def _days(value: Decimal) -> str:
    return f"{value.normalize():f}"


@router.get(WORKING_CAPITAL, response=WorkingCapitalOut)
@requires("planning.run")
def working_capital_view(request: HttpRequest, slug: str, entity_id: UUID,
                         base_set_id: UUID | None = None,
                         scenario_id: UUID | None = None) -> WorkingCapitalOut:  # fmt: skip
    """Receivables, stock and payables by month, the days that drive them and the cash
    conversion cycle, next to the days observed over the last 12 months (computed now)."""
    ctx = workspace_ctx(request, slug, entity_id)
    v = working_capital.view(ctx, entity_id, set_id=base_set_id, scenario_id=scenario_id)
    return WorkingCapitalOut(
        base_label=v.base_label, nature=v.nature, watermark=v.watermark, cutover=v.cutover,
        observed={k: _days(x) for k, x in v.observed.items()}, observed_ccc=_days(v.observed_ccc),
        months=[WorkingCapitalMonthOut(
            month=m.month, receivables=f"{m.receivables:.2f}", inventory=f"{m.inventory:.2f}",
            payables=f"{m.payables:.2f}", net=f"{m.net:.2f}", change=f"{m.change:.2f}",
            cash_effect=f"{m.cash_effect:.2f}", dso=_days(m.dso), dio=_days(m.dio),
            dpo=_days(m.dpo), ccc=_days(m.ccc)) for m in v.months],
    )  # fmt: skip


@router.post(f"{WORKING_CAPITAL}/days-worth", response=DaysWorthOut)
@requires("planning.run")
def working_capital_days_worth(request: HttpRequest, slug: str, entity_id: UUID,
                               payload: DaysWorthIn) -> DaysWorthOut:  # fmt: skip
    """What N days are worth: the cash released by changing DSO, DIO or DPO by N days."""
    ctx = workspace_ctx(request, slug, entity_id)
    d = working_capital.days_worth(ctx, entity_id, set_id=payload.base_set_id,
                                   scenario_id=payload.scenario_id, driver=payload.driver,
                                   days=payload.days)  # fmt: skip
    return DaysWorthOut(
        driver=d.driver, days=d.days, closing_cash_change=f"{d.closing_cash_change:.2f}",
        lowest_cash_change=f"{d.lowest_cash_change:.2f}",
        net_working_capital_change=f"{d.net_working_capital_change:.2f}",
        by_month=[{"month": m.isoformat(), "cash_change": f"{v:.2f}"} for m, v in d.by_month],
    )  # fmt: skip


# --- goals against scenarios (M7-5) ---------------------------------------------------------------


class GoalOutlookOut(Schema):
    label: str = Field(description="Base, or the scenario's name")
    applicable: bool
    reason: str
    status: str = Field(description="ON_TRACK, AT_RISK, OFF_TRACK or UNDETERMINED")
    method: str = Field(description="e.g. PROJECTION, BUDGET, SCENARIO")
    note: str = Field(description="How the likely outcome was projected, in words")
    nature: str = Field(description="Of the likely outcome: FORECAST, BUDGET or HYPOTHETICAL")
    projected: str | None = Field(description="The likely outcome")
    gap: str | None = Field(description="Target - likely outcome")


def _number(value: Decimal | None) -> str | None:
    return None if value is None else f"{value.normalize():f}"


@router.get("/w/{slug}/entities/{uuid:entity_id}/goals/{uuid:goal_id}/scenario-outlooks",
            response=list[GoalOutlookOut])  # fmt: skip
@requires("planning.run")
def goal_scenario_outlooks(request: HttpRequest, slug: str, entity_id: UUID, goal_id: UUID,
                           scenario_ids: str = "") -> list[GoalOutlookOut]:  # fmt: skip
    """The goal against its base and up to three shared scenarios (comma-separated ids), side by
    side, computed now. Nothing is stored and the goal never changes."""
    ctx = workspace_ctx(request, slug, entity_id)
    try:
        ids = [UUID(x.strip()) for x in scenario_ids.split(",") if x.strip()]
    except ValueError:
        message = "scenario_ids: scenario ids separated by commas."
        raise ValidationFailedError(message, field_errors={"scenario_ids": [message]}) from None
    return [
        GoalOutlookOut(label=o.label, applicable=o.applicable, reason=o.reason, status=o.status,
                       method=o.method, note=o.note, nature=o.nature,
                       projected=_number(o.projected), gap=_number(o.gap))
        for o in goal_outlooks.goal_outlooks(ctx, entity_id, goal_id, ids)
    ]  # fmt: skip


# --- KPIs on projected and scenario figures (M7-6) ---------------------------------------------


class ProjectedKpiOut(Schema):
    key: str
    name: str
    display: str = Field(description="percent, ratio, times, days or months")
    value: str | None
    nm_reason: str
    base_value: str | None = Field(default=None, description="For a scenario: its base's value")


class ProjectedKpisOut(Schema):
    label: str
    nature: str = Field(description="FORECAST (assumption set) or HYPOTHETICAL (scenario)")
    library: str
    year: int
    start: date
    end: date
    kpis: list[ProjectedKpiOut]
    engine_status: str = Field(default_factory=reviews.engine_status)


@router.get("/w/{slug}/entities/{uuid:entity_id}/projected-kpis", response=ProjectedKpisOut)
@requires("planning.run")
def projected_kpis_view(request: HttpRequest, slug: str, entity_id: UUID, year: int,
                        base_set_id: UUID | None = None,
                        scenario_id: UUID | None = None) -> ProjectedKpisOut:  # fmt: skip
    """The KPI library on a projected year of an approved set, or of a shared scenario next to
    its base (computed now; not stored)."""
    ctx = workspace_ctx(request, slug, entity_id)
    r = projected_kpis.projected_kpis(ctx, entity_id, set_id=base_set_id,
                                      scenario_id=scenario_id, year=year)  # fmt: skip
    base = {k.key: k for k in r.base or []}
    return ProjectedKpisOut(
        label=r.label, nature=r.nature, library=DEFAULT_LIBRARY, year=r.year, start=r.start,
        end=r.end,
        kpis=[ProjectedKpiOut(
            key=k.key, name=k.name, display=k.display, value=_number(k.value),
            nm_reason=k.nm_reason,
            base_value=_number(base[k.key].value) if k.key in base else None) for k in r.values],
    )  # fmt: skip
