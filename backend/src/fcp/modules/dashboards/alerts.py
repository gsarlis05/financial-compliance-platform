"""Alerts: raised on a change of state, never twice for the same state; acknowledged once (M4-7).

Sources:
- **Goals** (AC-GO4): after every goal evaluation, its status (an alert when it becomes at risk or
  off track) and, for threshold goals, a breach in actuals or in the forecast.
- **Budgets** (doc 10 §7): when budgets are checked, each line of the current approved version:
  - an **overrun**: the year-to-date variance is unfavourable (costs above budget, income below
    it) and reaches the entity's variance thresholds (M4-3: both the amount and the percentage);
  - a **trend**: the last 3 months were each unfavourable.

Who sees an alert follows the permission its source needs (``planning.read`` for goals,
``budget.read`` for budgets). Acknowledging needs ``alert.acknowledge``; the acknowledgement is
shared, records who made it, and is final.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.budgeting.api import VarianceComparison, compute_variance, list_budget_views
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Alert, AlertState

READ, ACK = "planning.read", "alert.acknowledge"
GOAL_AUDIENCE, BUDGET_AUDIENCE = "planning.read", "budget.read"
ALERTING_GOAL = {"AT_RISK": Alert.Severity.WARNING, "OFF_TRACK": Alert.Severity.CRITICAL}
TREND_MONTHS = 3
AVB = VarianceComparison.ACTUAL_VS_BUDGET


@dataclass(frozen=True)
class Observation:
    key: str
    state: str
    alerting: bool
    kind: str = ""
    severity: str = Alert.Severity.WARNING
    title: str = ""
    detail: str = ""
    subject_type: str = ""
    subject_id: UUID | None = None
    period: date | None = None
    source_run_id: UUID | None = None
    audience: str = GOAL_AUDIENCE


def observe(ctx: WorkspaceContext, entity_id: UUID, seen: Observation) -> Alert | None:
    """Record the state of ``seen.key``; raise an alert only when it changed into an alerting
    state. The state row is locked, so two concurrent observations cannot raise twice."""
    with transaction.atomic():
        state, _ = AlertState.objects.select_for_update().get_or_create(
            legal_entity_id=entity_id, key=seen.key,
            defaults={"tenant_id": ctx.tenant.id, "state": "NONE"},
        )  # fmt: skip
        if state.state == seen.state:
            return None
        state.state, state.changes = seen.state, state.changes + 1
        state.save(update_fields=["state", "changes", "changed_at"])
        if not seen.alerting or seen.subject_id is None:
            return None
        alert = Alert.objects.create(
            tenant_id=ctx.tenant.id, legal_entity_id=entity_id, key=seen.key,
            sequence=state.changes, kind=seen.kind, state=seen.state, severity=seen.severity,
            title=seen.title[:200], detail=seen.detail[:500], subject_type=seen.subject_type,
            subject_id=seen.subject_id, period=seen.period, source_run_id=seen.source_run_id,
            audience=seen.audience,
        )  # fmt: skip
        audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="dashboards.alert.raised",
              subject_type="alert", subject_id=alert.id, entity_id=entity_id,
              changes={"key": seen.key, "state": seen.state, "kind": seen.kind})  # fmt: skip
        return alert


# --- goals ------------------------------------------------------------------------------------


def goal_evaluated(ctx: WorkspaceContext, goal: Any, summary: Any) -> None:
    """The goals listener (registered in ``apps.py``): status and breach alerts (AC-GO4)."""
    status = summary.status
    words = {"AT_RISK": "at risk", "OFF_TRACK": "off track", "ON_TRACK": "on track",
             "UNDETERMINED": "undetermined"}  # fmt: skip
    detail = f"Evaluated as of {summary.as_of.isoformat()}"
    if summary.gap is not None:
        gap = (f"{summary.gap * 100:.2f} percentage points" if goal.display == "percent"
               else f"{summary.gap:.2f}")  # fmt: skip
        detail += f"; gap to target {gap}"
    observe(ctx, goal.legal_entity_id, Observation(
        key=f"goal:{goal.id}:status", state=status, alerting=status in ALERTING_GOAL,
        kind=Alert.Kind.GOAL_STATUS, severity=ALERTING_GOAL.get(status, Alert.Severity.WARNING),
        title=f"Goal {goal.name} is {words.get(status, status)}", detail=detail,
        subject_type="goal", subject_id=goal.id, period=goal.period_end,
        source_run_id=summary.run_id,
    ))  # fmt: skip
    breach = summary.breach_date
    forecast = breach is not None and breach > summary.as_of
    observe(ctx, goal.legal_entity_id, Observation(
        key=f"goal:{goal.id}:breach", state="BREACH" if breach else "NONE",
        alerting=breach is not None, kind=Alert.Kind.GOAL_BREACH,
        severity=Alert.Severity.CRITICAL,
        title=f"Goal {goal.name}: threshold " + ("breach forecast" if forecast else "breached"),
        detail=f"First breach on {breach.isoformat()}" if breach else "",
        subject_type="goal", subject_id=goal.id, period=breach, source_run_id=summary.run_id,
    ))  # fmt: skip


# --- budgets ----------------------------------------------------------------------------------


def last_complete_month(today: date) -> date:
    end = today if today == month_end(today) else month_start(today) - timedelta(days=1)
    return month_start(end)


def _line(row: Any) -> str:
    subject = row.taxonomy_code or f"account {row.account_id}"
    return subject if row.dimension_value_id is None else f"{subject} / {row.dimension_value_id}"


def check_budgets(ctx: WorkspaceContext, entity_id: UUID, month: date | None = None) -> int:
    """Check every budget's current approved version for ``month`` (default: the last complete
    month). Returns how many alerts were raised. Without ``budget.read`` nothing is checked."""
    entity = get_entity(ctx, entity_id, READ)
    if not ctx.can(BUDGET_AUDIENCE, entity.id):
        return 0
    month = month_start(month) if month else last_complete_month(timezone.localdate())
    raised = 0
    for view in list_budget_views(ctx, entity.id):
        version = view.current
        budget = view.budget
        if version is None or not budget.fiscal_year_start <= month <= budget.fiscal_year_end:
            continue
        ytd = compute_variance(ctx, entity.id, version.id, month=month, view="YTD",
                               comparison=AVB)  # fmt: skip
        trend: dict[str, list[bool]] = {}
        months = [add_months(month, -i) for i in range(TREND_MONTHS)]
        if all(m >= month_start(budget.fiscal_year_start) for m in months):
            for m in months:
                found = compute_variance(ctx, entity.id, version.id, month=m, view="MONTH",
                                         comparison=AVB)  # fmt: skip
                for row in found.rows:
                    if row.line_id is not None:
                        trend.setdefault(_line(row), []).append(row.favourable is False)
        for row in ytd.rows:
            if row.line_id is None:
                continue
            line = _line(row)
            over = row.favourable is False and row.requires_explanation
            pct = "n/m" if row.percent is None else f"{row.percent:.1f}%"
            base = f"budget:{budget.id}:{line}"
            if observe(ctx, entity.id, Observation(
                key=f"{base}:overrun", state="OVERRUN" if over else "OK", alerting=over,
                kind=Alert.Kind.BUDGET_OVERRUN, severity=Alert.Severity.CRITICAL,
                title=f"{budget.name}: {line} unfavourable against budget year to date",
                detail=f"Year to date to {month_end(month).isoformat()}: actual {row.subject:.2f}, "
                       f"budget {row.comparison:.2f}, variance {row.variance:.2f} ({pct})",
                subject_type="budget", subject_id=budget.id, period=month,
                audience=BUDGET_AUDIENCE,
            )):  # fmt: skip
                raised += 1
            flags = trend.get(line)
            if flags is None:
                continue
            bad = len(flags) == TREND_MONTHS and all(flags)
            if observe(ctx, entity.id, Observation(
                key=f"{base}:trend", state="UNFAVOURABLE_3M" if bad else "OK", alerting=bad,
                kind=Alert.Kind.BUDGET_TREND, severity=Alert.Severity.WARNING,
                title=f"{budget.name}: {line} unfavourable 3 months in a row",
                detail=f"Unfavourable against budget in each month from "
                       f"{months[-1].isoformat()[:7]} to {month.isoformat()[:7]}",
                subject_type="budget", subject_id=budget.id, period=month,
                audience=BUDGET_AUDIENCE,
            )):  # fmt: skip
                raised += 1
    return raised


# --- reading and acknowledging ----------------------------------------------------------------


def _visible(ctx: WorkspaceContext, entity_id: UUID) -> list[str]:
    return [p for p in (GOAL_AUDIENCE, BUDGET_AUDIENCE) if ctx.can(p, entity_id)]


def alerts(ctx: WorkspaceContext, entity_id: UUID, *, include_acknowledged: bool = False,
           limit: int = 100) -> list[Alert]:  # fmt: skip
    entity = get_entity(ctx, entity_id, READ)
    rows = Alert.objects.filter(legal_entity=entity, audience__in=_visible(ctx, entity.id))
    if not include_acknowledged:
        rows = rows.filter(acknowledged_at__isnull=True)
    return list(rows.select_related("acknowledged_by").order_by("-created_at", "-id")
                [: max(1, min(limit, 500))])  # fmt: skip


def open_counts(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, int]:
    entity = get_entity(ctx, entity_id, READ)
    rows = Alert.objects.filter(legal_entity=entity, audience__in=_visible(ctx, entity.id),
                                acknowledged_at__isnull=True)  # fmt: skip
    return {s: rows.filter(severity=s).count() for s in Alert.Severity.values}


@transaction.atomic
def acknowledge(ctx: WorkspaceContext, entity_id: UUID, alert_id: UUID, note: str = "") -> Alert:
    entity = get_entity(ctx, entity_id, ACK)
    alert = (Alert.objects.select_for_update()
             .filter(legal_entity=entity, id=alert_id, audience__in=_visible(ctx, entity.id))
             .first())  # fmt: skip
    if alert is None:
        raise NotFoundError("Alert not found.")
    if alert.acknowledged_at is not None:
        raise ConflictError("This alert has already been acknowledged.")
    note = note.strip()
    if len(note) > 300:
        raise ValidationFailedError("Keep the note to 300 characters.",
                                    field_errors={"note": ["too long"]})  # fmt: skip
    alert.acknowledged_by, alert.acknowledged_at = ctx.user, timezone.now()
    alert.acknowledgement_note = note
    alert.save(update_fields=["acknowledged_by", "acknowledged_at", "acknowledgement_note"])
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
          action="dashboards.alert.acknowledged", subject_type="alert", subject_id=alert.id,
          entity_id=entity.id, changes={"note": note})  # fmt: skip
    return alert
