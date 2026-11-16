"""Public interface of the ``goals`` module and its HTTP routes (M4-6: goals and evaluations).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``. Values are exact decimal
strings (ratios unrounded; displays round them). Every figure of an evaluation is a calculation
result with a nature and can be explained (``calc-runs/{run}/results/{result}/explain``).
"""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.metrics.api import canonical_decimal
from fcp.modules.tenancy.api import active_members, workspace_ctx

from . import services
from .engine import cut_over, method_note
from .models import Goal, GoalEvaluation, GoalVersion
from .services import GoalView, on_evaluation
from .services import list_goals as goal_views

__all__ = ["Goal", "GoalEvaluation", "GoalView", "goal_views", "on_evaluation", "router"]

router = Router(tags=["goals"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
NUMBER = r"^-?\d{1,16}(\.\d{1,12})?$"


def _amount(value: Decimal | None) -> str | None:
    return None if value is None else canonical_decimal(value)


class GoalMetricOut(Schema):
    key: str
    ref: str = Field(description="The definition version, e.g. CORE@1.0:DSO")
    name: str
    name_el: str
    kind: str = Field(description="ADDITIVE, RATIO or BALANCE")
    formula: str
    direction: str
    unit: str
    display: str
    convention: str


@router.get(f"{BASE}/goal-metrics", response=list[GoalMetricOut])
@requires("planning.read")
def goal_metrics(request: HttpRequest, slug: str, entity_id: UUID) -> list[GoalMetricOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [GoalMetricOut(**m.__dict__) for m in services.available_metrics(ctx, entity_id)]


class GoalOwnerOut(Schema):
    user_id: UUID
    display_name: str
    email: str


@router.get(f"{BASE}/goal-owners", response=list[GoalOwnerOut])
@requires("goal.manage")
def goal_owners(request: HttpRequest, slug: str, entity_id: UUID) -> list[GoalOwnerOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [GoalOwnerOut(**m.__dict__) for m in active_members(ctx)]


class GoalVersionOut(Schema):
    id: UUID
    number: int
    target_type: str
    target_input: str = Field(description="As entered; a change as a fraction (0.15 = +15%)")
    target_value: str = Field(description="The value to reach, in the metric's unit")
    direction: str = Field(description="AT_LEAST or AT_MOST")
    materiality: str = Field(description="A fraction of |target| (0.05 = 5%)")
    owner_id: UUID
    driver: str
    baseline_value: str | None
    baseline_nm_reason: str
    baseline_from: date
    baseline_to: date
    baseline_run_id: UUID
    reason: str
    created_at: datetime
    superseded_at: datetime | None


class GoalLatestOut(Schema):
    run_id: UUID
    as_of: date
    status: str
    projected: str | None
    gap: str | None
    breach_date: date | None
    method: str
    created_at: datetime


class GoalOut(Schema):
    id: UUID
    name: str
    metric: str
    metric_name: str
    metric_kind: str
    metric_ref: str
    unit: str
    display: str
    period_start: date
    period_end: date
    status: str
    current: GoalVersionOut
    versions: list[GoalVersionOut]
    latest: GoalLatestOut | None


def _version_out(v: GoalVersion) -> GoalVersionOut:
    return GoalVersionOut(
        id=v.id, number=v.number, target_type=v.target_type,
        target_input=canonical_decimal(v.target_input),
        target_value=canonical_decimal(v.target_value), direction=v.direction,
        materiality=canonical_decimal(v.materiality), owner_id=v.owner_id, driver=v.driver,
        baseline_value=_amount(v.baseline_value), baseline_nm_reason=v.baseline_nm_reason,
        baseline_from=v.baseline_from, baseline_to=v.baseline_to,
        baseline_run_id=v.baseline_run_id, reason=v.reason, created_at=v.created_at,
        superseded_at=v.superseded_at,
    )  # fmt: skip


def _latest_out(e: GoalEvaluation | None) -> GoalLatestOut | None:
    if e is None:
        return None
    return GoalLatestOut(run_id=e.run_id, as_of=e.as_of, status=e.status,
                         projected=_amount(e.projected), gap=_amount(e.gap),
                         breach_date=e.breach_date, method=e.method,
                         created_at=e.created_at)  # fmt: skip


def _goal_out(view: services.GoalView) -> GoalOut:
    g = view.goal
    return GoalOut(
        id=g.id, name=g.name, metric=g.metric, metric_name=g.metric_name,
        metric_kind=g.metric_kind, metric_ref=g.metric_ref, unit=g.unit, display=g.display,
        period_start=g.period_start, period_end=g.period_end, status=g.status,
        current=_version_out(view.current), versions=[_version_out(v) for v in view.versions],
        latest=_latest_out(view.latest),
    )  # fmt: skip


class GoalListQuery(Schema):
    include_retired: bool = False


@router.get(f"{BASE}/goals", response=list[GoalOut])
@requires("planning.read")
def list_goals(request: HttpRequest, slug: str, entity_id: UUID,
               q: Query[GoalListQuery]) -> list[GoalOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.list_goals(ctx, entity_id, include_retired=q.include_retired)
    return [_goal_out(v) for v in found]


class GoalIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    metric: str = Field(max_length=60, description="A key from goal-metrics")
    period_start: date = Field(description="The first day of a month")
    period_end: date = Field(description="The last day of a month: the target date")
    target_type: str = Field(description="ABSOLUTE, CHANGE_PCT, MAINTAIN_MIN or MAINTAIN_MAX")
    target: str = Field(pattern=NUMBER, description="Ratios and changes as fractions (0.2 = 20%)")
    materiality: str = Field("0.05", pattern=NUMBER)
    owner_id: UUID | None = None
    driver: str = Field("", max_length=40, description="Taxonomy key for the goal-seek")


@router.post(f"{BASE}/goals", response={201: GoalOut})
@requires("goal.manage")
def create_goal(request: HttpRequest, slug: str, entity_id: UUID,
                payload: GoalIn) -> Status[GoalOut]:  # fmt: skip
    """Create a goal; its baseline is computed now, as a calculation run, and frozen (AC-GO1)."""
    ctx = workspace_ctx(request, slug, entity_id)
    view = services.create(ctx, entity_id, services.GoalInput(
        name=payload.name, metric=payload.metric, period_start=payload.period_start,
        period_end=payload.period_end, target_type=payload.target_type,
        target=Decimal(payload.target), materiality=Decimal(payload.materiality),
        owner_id=payload.owner_id, driver=payload.driver,
    ))  # fmt: skip
    return Status(201, _goal_out(view))


@router.get(f"{BASE}/goals/{{uuid:goal_id}}", response=GoalOut)
@requires("planning.read")
def get_goal(request: HttpRequest, slug: str, entity_id: UUID, goal_id: UUID) -> GoalOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _goal_out(services.get_goal(ctx, entity_id, goal_id))


class GoalRevisionIn(Schema):
    target_type: str
    target: str = Field(pattern=NUMBER)
    reason: str = Field(min_length=1, max_length=500)
    materiality: str = Field("0.05", pattern=NUMBER)
    owner_id: UUID | None = None
    driver: str = Field("", max_length=40)


@router.post(f"{BASE}/goals/{{uuid:goal_id}}/versions", response={201: GoalOut})
@requires("goal.manage")
def revise_goal(request: HttpRequest, slug: str, entity_id: UUID, goal_id: UUID,
                payload: GoalRevisionIn) -> Status[GoalOut]:  # fmt: skip
    """A new target is a new version, with a reason; the baseline is unchanged."""
    ctx = workspace_ctx(request, slug, entity_id)
    view = services.revise(ctx, entity_id, goal_id, services.RevisionInput(
        target_type=payload.target_type, target=Decimal(payload.target), reason=payload.reason,
        materiality=Decimal(payload.materiality), owner_id=payload.owner_id,
        driver=payload.driver,
    ))  # fmt: skip
    return Status(201, _goal_out(view))


@router.post(f"{BASE}/goals/{{uuid:goal_id}}/retire", response=GoalOut)
@requires("goal.manage")
def retire_goal(request: HttpRequest, slug: str, entity_id: UUID, goal_id: UUID) -> GoalOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _goal_out(services.retire(ctx, entity_id, goal_id))


class GoalFigureOut(Schema):
    result_id: UUID = Field(description="For calc-runs/{run}/results/{result}/explain")
    key: str = Field(description="e.g. goal.projected, goal.required.run_rate, goal.trend")
    dimensions: list[str]
    period_start: date
    period_end: date
    granularity: str
    nature: str
    value: str | None
    unit: str
    nm_reason: str


class GoalHistoryOut(Schema):
    as_of: date
    status: str
    projected: str | None
    gap: str | None
    created_at: datetime


class GoalEvaluationOut(Schema):
    goal_id: UUID
    version: int
    run_id: UUID
    run_status: str
    watermark: int
    as_of: date
    cut_over: date = Field(description="Actuals up to this date; projected after it")
    status: str = Field(description="ON_TRACK, AT_RISK, OFF_TRACK or UNDETERMINED")
    method: str
    method_note: str
    out_of_date: bool = Field(description="Entries were posted after this evaluation")
    figures: list[GoalFigureOut]
    history: list[GoalHistoryOut] = Field(description="Earlier evaluations: the trend of the gap")


def _evaluation_out(e: services.Evaluation) -> GoalEvaluationOut:
    cut = cut_over(e.run.as_of_date)
    return GoalEvaluationOut(
        goal_id=e.goal.id, version=e.version.number, run_id=e.run.id, run_status=e.run.status,
        watermark=e.run.actuals_watermark, as_of=e.run.as_of_date, cut_over=cut,
        status=e.status, method=e.method, method_note=method_note(e.method, cut),
        out_of_date=e.out_of_date,
        figures=[GoalFigureOut(
            result_id=r.id, key=r.series_key, dimensions=r.dimensions,
            period_start=r.period_start, period_end=r.period_end, granularity=r.granularity,
            nature=r.nature, value=_amount(r.value), unit=r.unit, nm_reason=r.nm_reason,
        ) for r in e.values],
        history=[GoalHistoryOut(as_of=h.as_of, status=h.status, projected=_amount(h.projected),
                                gap=_amount(h.gap), created_at=h.created_at)
                 for h in e.history],
    )  # fmt: skip


class GoalEvaluateIn(Schema):
    as_of: date | None = Field(None, description="Default: today")
    driver: str = Field("", max_length=40, description="Override the goal's goal-seek driver")


@router.post(f"{BASE}/goals/{{uuid:goal_id}}/evaluations", response={201: GoalEvaluationOut})
@requires("planning.run")
def evaluate_goal(request: HttpRequest, slug: str, entity_id: UUID, goal_id: UUID,
                  payload: GoalEvaluateIn) -> Status[GoalEvaluationOut]:  # fmt: skip
    """Evaluate the goal now: a reproducible calculation run and a stored summary."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = services.evaluate(ctx, entity_id, goal_id, as_of=payload.as_of,
                              driver=payload.driver)  # fmt: skip
    return Status(201, _evaluation_out(found))


@router.get(f"{BASE}/goals/{{uuid:goal_id}}/evaluations/latest", response=GoalEvaluationOut)
@requires("planning.read")
def latest_evaluation(request: HttpRequest, slug: str, entity_id: UUID,
                      goal_id: UUID) -> GoalEvaluationOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _evaluation_out(services.latest_evaluation(ctx, entity_id, goal_id))
