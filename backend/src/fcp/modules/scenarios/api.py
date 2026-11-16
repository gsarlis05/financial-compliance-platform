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

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.projections.api import SetInfo
from fcp.modules.tenancy.api import workspace_ctx

from . import runs as scenario_runs
from . import services
from .models import Scenario, ScenarioOverride
from .overrides import MAX_OVERRIDES

__all__ = ["OverrideType", "router"]

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
    engine_status: str = Field(default="PENDING_PROFESSIONAL_REVIEW",
                               description="The projection engine is not yet validated "
                               "by a professional")  # fmt: skip


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
