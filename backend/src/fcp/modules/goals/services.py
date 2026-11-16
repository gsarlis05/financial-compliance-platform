"""Goals: create with a frozen baseline, revise, retire, evaluate (M4-6, doc 10 §6).

Reading needs ``planning.read``; creating, revising and retiring need ``goal.manage``; running an
evaluation needs ``planning.run``. Each evaluation is a calculation run (``GOAL_EVAL``) and an
append-only summary row that alerts read (M4-7).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.budgeting.api import approved_plan
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.cashflow.api import latest_cash_forecast
from fcp.modules.kpi.api import kpi_inputs, period_months
from fcp.modules.metrics.api import CalcRun, calc_results, execute, get_calc_run, taxonomy_lines
from fcp.modules.reporting.api import posted_since
from fcp.modules.tenancy.api import WorkspaceContext, active_members, get_entity

from .catalogue import BALANCE, Metric, metric, metrics
from .engine import BASELINE_KIND, EVAL_KIND, STATUSES, cut_over
from .models import Goal, GoalEvaluation, GoalVersion

READ, MANAGE, RUN = "planning.read", "goal.manage", "planning.run"
# Called after every stored evaluation, in its transaction (alerts, M4-7). Modules register
# here so that goals never imports them.
Listener = Callable[[WorkspaceContext, Goal, GoalEvaluation], None]
_LISTENERS: list[Listener] = []


def on_evaluation(listener: Listener) -> Listener:
    """Register ``listener(ctx, goal, summary)`` for every new evaluation (idempotent)."""
    if listener not in _LISTENERS:
        _LISTENERS.append(listener)
    return listener


MAX_MONTHS = 24
TargetType = GoalVersion.TargetType
DEFAULT_MATERIALITY = Decimal("0.05")
LIMIT = Decimal("1e15")


def _invalid(name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={name: [message]})


def _audit(ctx: WorkspaceContext, goal: Goal, action: str, changes: dict[str, Any]) -> None:
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=action, subject_type="goal",
          subject_id=goal.id, entity_id=goal.legal_entity_id, changes=changes)  # fmt: skip


def available_metrics(ctx: WorkspaceContext, entity_id: UUID) -> list[Metric]:
    entity = get_entity(ctx, entity_id, READ)
    return metrics(entity.id)


@dataclass(frozen=True)
class GoalInput:
    name: str
    metric: str
    period_start: date
    period_end: date
    target_type: str
    target: Decimal
    materiality: Decimal = DEFAULT_MATERIALITY
    owner_id: UUID | None = None
    driver: str = ""


@dataclass(frozen=True)
class RevisionInput:
    target_type: str
    target: Decimal
    reason: str
    materiality: Decimal = DEFAULT_MATERIALITY
    owner_id: UUID | None = None
    driver: str = ""


@dataclass(frozen=True)
class GoalView:
    goal: Goal
    current: GoalVersion
    versions: list[GoalVersion]
    latest: GoalEvaluation | None


# --- validation -----------------------------------------------------------------------------------


def _period(start: date, end: date) -> None:
    if start.day != 1 or end != month_end(end) or end <= start:
        raise _invalid("period_start", "A goal covers whole months: from the first day of a "
                       "month to the last day of a later or the same month.")  # fmt: skip
    if end > month_end(add_months(start, MAX_MONTHS - 1)):
        raise _invalid("period_end", f"A goal covers at most {MAX_MONTHS} months.")


def _check_target(m: Metric, target_type: str, target: Decimal, materiality: Decimal) -> None:
    if target_type not in TargetType.values:
        raise _invalid("target_type", "Choose absolute, change %, stay at least or stay at most.")
    if target_type in (TargetType.MAINTAIN_MIN, TargetType.MAINTAIN_MAX) and m.kind != BALANCE:
        raise _invalid("target_type", "A threshold to stay above or below applies to a balance "
                       "such as cash; for other metrics choose an absolute target.")  # fmt: skip
    if not target.is_finite() or abs(target) >= LIMIT:
        raise _invalid("target", "Enter a target below 10^15.")
    if target_type == TargetType.CHANGE_PCT and (target == 0 or target < -1 or target > 100):
        raise _invalid("target", "Enter a change between -100% and +10,000%, not 0 (as a "
                       "fraction: 0.15 for +15%).")  # fmt: skip
    if not materiality.is_finite() or not Decimal(0) <= materiality <= 1:
        raise _invalid("materiality", "The materiality threshold is between 0% and 100%.")


def _check_driver(ctx: WorkspaceContext, entity_id: UUID, driver: str) -> str:
    driver = driver.strip()
    if not driver:
        return ""
    keys = set()
    for line in taxonomy_lines(ctx, entity_id):
        keys |= {line.code, line.section, *(line.code.split(".")[:1])}
    if driver not in keys:
        raise _invalid("driver", f"Unknown driver {driver!r}: choose a taxonomy line or section.")
    return driver


def _owner(ctx: WorkspaceContext, owner_id: UUID | None) -> UUID:
    if owner_id is None:
        return ctx.user.id
    if owner_id not in {m.user_id for m in active_members(ctx)}:
        raise _invalid("owner_id", "The owner must be an active member of this workspace.")
    return owner_id


def _direction(m: Metric, target_type: str, target: Decimal) -> str:
    if target_type == TargetType.MAINTAIN_MIN:
        return GoalVersion.Direction.AT_LEAST
    if target_type == TargetType.MAINTAIN_MAX:
        return GoalVersion.Direction.AT_MOST
    if target_type == TargetType.CHANGE_PCT:
        return GoalVersion.Direction.AT_LEAST if target > 0 else GoalVersion.Direction.AT_MOST
    higher = m.direction == "HIGHER_BETTER"
    return GoalVersion.Direction.AT_LEAST if higher else GoalVersion.Direction.AT_MOST


def _target_value(target_type: str, target: Decimal, baseline: Decimal | None) -> Decimal:
    if target_type != TargetType.CHANGE_PCT:
        return target
    if baseline is None:
        raise ConflictError("The baseline is not meaningful, so a change from it cannot be set: "
                            "choose an absolute target.")  # fmt: skip
    return baseline + abs(baseline) * target


# --- the baseline ---------------------------------------------------------------------------------


def baseline_window(m: Metric, start: date, end: date) -> tuple[date, date]:
    """A balance: the month before the goal starts (its closing is the starting balance).
    Anything else: the same months one year earlier."""
    if m.kind == BALANCE:
        before = add_months(start, -1)
        return before, month_end(before)
    return add_months(start, -12), month_end(add_months(month_start(end), -12))


def _baseline(ctx: WorkspaceContext, entity_id: UUID, m: Metric, start: date,
              end: date) -> tuple[CalcRun, Decimal | None, str, date, date]:  # fmt: skip
    first, last = baseline_window(m, start, end)
    refs = {
        **{k: v for k, v in kpi_inputs(ctx, entity_id, first, last).items()
           if k in ("accounts", "operational")},
        "date_from": first.isoformat(), "date_to": last.isoformat(),
        "formula": m.formula, "metric": m.key, "metric_ref": m.ref,
    }  # fmt: skip
    run = execute(ctx, entity_id, BASELINE_KIND, as_of=last, refs=refs)
    if run.status != CalcRun.Status.VALID:
        raise ConflictError(f"The baseline could not be computed: {run.error or run.status}.")
    value = calc_results(run)[0]
    return run, value.value, value.nm_reason, first, last


# --- create, revise, retire -----------------------------------------------------------------------


@transaction.atomic
def create(ctx: WorkspaceContext, entity_id: UUID, data: GoalInput) -> GoalView:
    entity = get_entity(ctx, entity_id, MANAGE)
    name = data.name.strip()
    if not name or len(name) > 120:
        raise _invalid("name", "Give the goal a name of 1 to 120 characters.")
    _period(data.period_start, data.period_end)
    m = metric(entity.id, data.metric)
    _check_target(m, data.target_type, data.target, data.materiality)
    driver = _check_driver(ctx, entity.id, data.driver)
    owner = _owner(ctx, data.owner_id)
    run, base, nm, first, last = _baseline(ctx, entity.id, m, data.period_start, data.period_end)
    goal = Goal.objects.create(
        tenant=ctx.tenant, legal_entity=entity, name=name, metric=m.key, metric_kind=m.kind,
        metric_ref=m.ref, metric_name=m.name, formula=m.formula, unit=m.unit, display=m.display,
        metric_direction=m.direction,
        period_start=data.period_start, period_end=data.period_end, created_by=ctx.user,
    )  # fmt: skip
    version = GoalVersion.objects.create(
        tenant=ctx.tenant, goal=goal, legal_entity=entity, number=1,
        target_type=data.target_type, target_input=data.target,
        target_value=_target_value(data.target_type, data.target, base),
        direction=_direction(m, data.target_type, data.target), materiality=data.materiality,
        owner_id=owner, driver=driver, baseline_value=base, baseline_nm_reason=nm,
        baseline_from=first, baseline_to=last, baseline_run_id=run.id, created_by=ctx.user,
    )  # fmt: skip
    _audit(ctx, goal, "goals.goal.created", {
        "name": name, "metric": m.key, "metric_ref": m.ref, "target_type": data.target_type,
        "target": str(version.target_value), "baseline": None if base is None else str(base),
        "baseline_run": str(run.id),
    })  # fmt: skip
    return _view(goal)


def _goal(entity_id: UUID, goal_id: UUID, *, lock: bool = False) -> Goal:
    rows = Goal.objects.filter(legal_entity_id=entity_id, id=goal_id)
    if lock:
        rows = rows.select_for_update()
    goal = rows.first()
    if goal is None:
        raise NotFoundError("Goal not found.")
    return goal


def _view(goal: Goal) -> GoalView:
    versions = list(GoalVersion.objects.filter(goal=goal).order_by("number"))
    latest = GoalEvaluation.objects.filter(goal=goal).order_by("-created_at", "-id").first()
    current = next(v for v in versions if v.superseded_at is None)
    return GoalView(goal, current, versions, latest)


@transaction.atomic
def revise(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID, data: RevisionInput) -> GoalView:
    """A new version with a reason. The baseline is copied unchanged (AC-GO1)."""
    entity = get_entity(ctx, entity_id, MANAGE)
    goal = _goal(entity.id, goal_id, lock=True)
    if goal.status != Goal.Status.ACTIVE:
        raise ConflictError("A retired goal cannot be changed.")
    reason = data.reason.strip()
    if not reason or len(reason) > 500:
        raise _invalid("reason", "Say why the target changes (1 to 500 characters).")
    m = _stored_metric(goal)
    _check_target(m, data.target_type, data.target, data.materiality)
    driver = _check_driver(ctx, entity.id, data.driver)
    owner = _owner(ctx, data.owner_id)
    current = _view(goal).current
    number = (GoalVersion.objects.filter(goal=goal).aggregate(n=Max("number"))["n"] or 0) + 1
    current.superseded_at = timezone.now()
    current.save(update_fields=["superseded_at"])
    version = GoalVersion.objects.create(
        tenant=ctx.tenant, goal=goal, legal_entity=entity, number=number,
        target_type=data.target_type, target_input=data.target,
        target_value=_target_value(data.target_type, data.target, current.baseline_value),
        direction=_direction(m, data.target_type, data.target), materiality=data.materiality,
        owner_id=owner, driver=driver, baseline_value=current.baseline_value,
        baseline_nm_reason=current.baseline_nm_reason, baseline_from=current.baseline_from,
        baseline_to=current.baseline_to, baseline_run_id=current.baseline_run_id,
        reason=reason, created_by=ctx.user,
    )  # fmt: skip
    _audit(ctx, goal, "goals.goal.revised", {
        "version": number, "target_type": data.target_type, "target": str(version.target_value),
        "previous_target": str(current.target_value), "reason": reason,
    })  # fmt: skip
    return _view(goal)


def _stored_metric(goal: Goal) -> Metric:
    """The goal's metric as it was created (a KPI keeps the formula version it started with)."""
    return Metric(goal.metric, goal.metric_ref, goal.metric_name, "", goal.metric_kind,
                  goal.formula, goal.metric_direction, goal.unit, goal.display)  # fmt: skip


@transaction.atomic
def retire(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID) -> GoalView:
    entity = get_entity(ctx, entity_id, MANAGE)
    goal = _goal(entity.id, goal_id, lock=True)
    if goal.status == Goal.Status.RETIRED:
        return _view(goal)
    goal.status, goal.retired_by, goal.retired_at = Goal.Status.RETIRED, ctx.user, timezone.now()
    goal.save(update_fields=["status", "retired_by", "retired_at"])
    _audit(ctx, goal, "goals.goal.retired", {})
    return _view(goal)


def list_goals(ctx: WorkspaceContext, entity_id: UUID, *, include_retired: bool = False,
               ) -> list[GoalView]:  # fmt: skip
    entity = get_entity(ctx, entity_id, READ)
    goals = Goal.objects.filter(legal_entity=entity).order_by("period_end", "name", "id")
    if not include_retired:
        goals = goals.filter(status=Goal.Status.ACTIVE)
    return [_view(g) for g in goals]


def get_goal(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID) -> GoalView:
    entity = get_entity(ctx, entity_id, READ)
    return _view(_goal(entity.id, goal_id))


# --- evaluation -----------------------------------------------------------------------------------


def _lines(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, list[Any]]:
    credit_types = ("INCOME", "LIABILITY", "EQUITY")
    return {
        line.code: [line.section, line.account_types.split(",")[0] in credit_types]
        for line in taxonomy_lines(ctx, entity_id)
    }


def _forecast(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, Any] | None:
    try:
        found = latest_cash_forecast(ctx, entity_id)
    except NotFoundError:
        return None
    return {
        "run_id": str(found.run.id),
        "as_of": found.run.as_of_date.isoformat(),
        "weeks": [[w.end.isoformat(), f"{w.amounts.get('closing', Decimal(0))}"]
                  for w in found.weeks],
    }  # fmt: skip


def evaluation_refs(ctx: WorkspaceContext, view: GoalView, as_of: date,
                    driver: str = "") -> dict[str, Any]:  # fmt: skip
    goal, v = view.goal, view.current
    entity_id = goal.legal_entity_id
    cut = cut_over(as_of)
    months = period_months(goal.period_start, month_start(goal.period_end))
    snapshot = kpi_inputs(ctx, entity_id, goal.period_start, goal.period_end)
    plan = approved_plan(ctx, entity_id, months) if goal.metric_kind != BALANCE else None
    return {
        "goal": {
            "id": str(goal.id), "version_id": str(v.id), "number": v.number,
            "metric": goal.metric, "metric_ref": goal.metric_ref, "kind": goal.metric_kind,
            "formula": goal.formula, "unit": goal.unit,
            "period_from": goal.period_start.isoformat(), "period_to": goal.period_end.isoformat(),
            "target_type": v.target_type, "target": str(v.target_value),
            "direction": v.direction, "materiality": str(v.materiality),
            "driver": driver or v.driver,
            "baseline": None if v.baseline_value is None else str(v.baseline_value),
            "baseline_nm": v.baseline_nm_reason, "baseline_run": str(v.baseline_run_id),
        },
        "as_of": as_of.isoformat(),
        "cut": cut.isoformat(),
        "accounts": snapshot["accounts"],
        "operational": snapshot["operational"],
        "lines": _lines(ctx, entity_id),
        "plan": None if plan is None else {"versions": plan.versions, "amounts": plan.amounts},
        "forecast": _forecast(ctx, entity_id) if goal.metric_kind == BALANCE else None,
    }  # fmt: skip


@dataclass(frozen=True)
class Evaluation:
    goal: Goal
    version: GoalVersion
    run: CalcRun
    status: str
    method: str
    values: list[Any]  # CalcResult rows
    out_of_date: bool
    summary: GoalEvaluation | None = None
    history: list[GoalEvaluation] = field(default_factory=list)


def _status(results: list[Any]) -> tuple[str, str]:
    for r in results:
        if r.series_key == "goal.status":
            return r.dimensions[0], r.dimensions[1]
    return "UNDETERMINED", ""


def _first(results: list[Any], key: str, dim: str | None = None) -> Any:
    for r in results:
        if r.series_key == key and (dim is None or (r.dimensions and r.dimensions[0] == dim)):
            return r
    return None


@transaction.atomic
def evaluate(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID, *, as_of: date | None = None,
             driver: str = "") -> Evaluation:  # fmt: skip
    entity = get_entity(ctx, entity_id, RUN)
    view = _view(_goal(entity.id, goal_id))
    if view.goal.status != Goal.Status.ACTIVE:
        raise ConflictError("A retired goal is not evaluated.")
    today = timezone.localdate()
    as_of = as_of or today
    if as_of > today:
        raise _invalid("as_of", "Evaluate as of today or an earlier date.")
    driver = _check_driver(ctx, entity.id, driver)
    refs = evaluation_refs(ctx, view, as_of, driver)
    run = execute(ctx, entity.id, EVAL_KIND, as_of=as_of, refs=refs)
    if run.status == CalcRun.Status.FAILED:
        raise ConflictError(f"The evaluation failed: {run.error}.")
    results = calc_results(run)
    status, method = _status(results)
    projected, actual = _first(results, "goal.projected"), _first(results, "goal.actual")
    gap = _first(results, "goal.gap", "PROJECTED")
    breach = _first(results, "goal.required.breach")
    summary = GoalEvaluation.objects.create(
        tenant=ctx.tenant, goal=view.goal, version=view.current, legal_entity=entity,
        run_id=run.id, as_of=as_of, status=status,
        projected=projected.value if projected else None,
        actual=actual.value if actual else None, gap=gap.value if gap else None,
        breach_date=breach.period_start if breach else None, method=method, created_by=ctx.user,
    )  # fmt: skip
    for listener in _LISTENERS:
        listener(ctx, view.goal, summary)
    return _evaluation(ctx, view.goal, run, summary)


def _evaluation(ctx: WorkspaceContext, goal: Goal, run: CalcRun,
                summary: GoalEvaluation | None) -> Evaluation:  # fmt: skip
    results = calc_results(run)
    status, method = _status(results)
    version = GoalVersion.objects.get(goal=goal, id=run.input_refs["goal"]["version_id"])
    history = list(GoalEvaluation.objects.filter(goal=goal).order_by("created_at", "id"))[-24:]
    newer = posted_since(ctx, goal.legal_entity_id, run.actuals_watermark)
    return Evaluation(goal, version, run, status if status in STATUSES else "UNDETERMINED",
                      method, results, run.stale or newer, summary, history)  # fmt: skip


def latest_evaluation(ctx: WorkspaceContext, entity_id: UUID, goal_id: UUID) -> Evaluation:
    entity = get_entity(ctx, entity_id, READ)
    goal = _goal(entity.id, goal_id)
    summary = GoalEvaluation.objects.filter(goal=goal).order_by("-created_at", "-id").first()
    if summary is None:
        raise NotFoundError("This goal has not been evaluated yet.")
    return _evaluation(ctx, goal, get_calc_run(ctx, entity.id, summary.run_id), summary)
