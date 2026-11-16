"""Rolling forecasts (M6-4, brief §3, AC-RF1): the next 12 or 24 months, kept current.

- **Setting.** One per legal entity: the assumption-set family (its approved version is used), the
  horizon and whether it is active. The scheduled re-run acts as the user who last changed it,
  with that user's current permissions.
- **A run.** A projection (kind PROJECTION) whose cut-over is the end of the last full month before
  today, over the next 12 or 24 months. Months the set does not cover take the set's value for the
  same calendar month (no growth). Each run is kept; a new one supersedes the latest.
- **Stale** when the books have postings after the latest run's watermark, a new month has
  started, or another version of the family was approved. The stale run is marked, never changed.
- **Refresh.** ``refresh`` makes a new run when the latest is stale (or there is none); the
  scheduled ``projections_refresh`` job does this for every active rolling forecast.
- **Accuracy.** For each of the last 12 closed months: what the rolling forecasts made 1, 3 and 6
  months earlier expected, against the actual, for revenue, EBITDA and closing cash. Error =
  forecast - actual; % error = |error| / |actual|, not meaningful when the actual is 0. Reported,
  not gated.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import ConflictError, DomainError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.metrics.api import CalcRun, calc_results, current_mapping, list_calc_runs
from fcp.modules.reporting.api import actuals_monthly, opening_net, posted_since
from fcp.modules.tenancy.api import Tenant, WorkspaceContext, enter_workspace, get_entity

from .assumptions import READ, RUN
from .drivers import OPEX_LINES, REVENUE_LINES
from .models import AssumptionSet, RollingForecast
from .runs import KIND, run_projection

log = logging.getLogger(__name__)
ZERO = Decimal(0)
HORIZONS = (1, 3, 6)
MEASURES = ("PL.REVENUE", "PL.EBITDA", "BS.CASH")
FINISHED = (CalcRun.Status.VALID, CalcRun.Status.INVALID)


def _audit(ctx: WorkspaceContext, rolling: RollingForecast, action: str,
           changes: dict[str, object]) -> None:  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=action,
          subject_type="rolling_forecast", subject_id=rolling.id,
          entity_id=rolling.legal_entity_id, changes=changes)  # fmt: skip


def setting(ctx: WorkspaceContext, entity_id: UUID) -> RollingForecast | None:
    entity = get_entity(ctx, entity_id, READ).id
    return RollingForecast.objects.filter(legal_entity_id=entity).first()


def approved_version(entity_id: UUID, family_id: UUID) -> AssumptionSet | None:
    return AssumptionSet.objects.filter(legal_entity_id=entity_id, family_id=family_id,
                                        status=AssumptionSet.Status.APPROVED).first()  # fmt: skip


@transaction.atomic
def configure(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID, horizon: int,
              active: bool = True) -> RollingForecast:  # fmt: skip
    """Set up or change the entity's rolling forecast (any version of a family names it)."""
    entity = get_entity(ctx, entity_id, RUN).id
    if horizon not in (12, 24):
        raise ValidationFailedError("Choose a horizon of 12 or 24 months.",
                                    field_errors={"horizon": ["12 or 24"]})  # fmt: skip
    chosen = AssumptionSet.objects.filter(legal_entity_id=entity, id=set_id).first()
    if chosen is None:
        raise NotFoundError("Assumption set not found.")
    if approved_version(entity, chosen.family_id) is None:
        raise ConflictError("Approve a version of this assumption set first.")
    rolling = RollingForecast.objects.select_for_update().filter(legal_entity_id=entity).first()
    before = None
    if rolling is None:
        rolling = RollingForecast(tenant=ctx.tenant, legal_entity_id=entity)
    else:
        before = {"family_id": str(rolling.family_id), "horizon": rolling.horizon,
                  "active": rolling.active}  # fmt: skip
    rolling.family_id, rolling.horizon, rolling.active = chosen.family_id, horizon, active
    rolling.updated_by = ctx.user
    rolling.save()
    _audit(ctx, rolling, "projections.rolling.configured", {
        "before": before, "family_id": str(chosen.family_id), "horizon": horizon,
        "active": active})  # fmt: skip
    return rolling


def runs_of(ctx: WorkspaceContext, entity_id: UUID, rolling: RollingForecast,
            limit: int = 200) -> list[CalcRun]:  # fmt: skip
    """The rolling forecast's runs, newest first."""
    ref = str(rolling.id)
    return [r for r in list_calc_runs(ctx, entity_id, KIND, limit)
            if r.input_refs.get("rolling_forecast_id") == ref]  # fmt: skip


def cutover_for(today: date) -> date:
    """The end of the last full month before ``today``."""
    return month_end(add_months(month_start(today), -1))


@dataclass(frozen=True)
class Freshness:
    stale: bool
    reasons: tuple[str, ...]


def freshness(ctx: WorkspaceContext, entity_id: UUID, rolling: RollingForecast, run: CalcRun,
              today: date | None = None) -> Freshness:  # fmt: skip
    today = today or timezone.localdate()
    reasons = []
    if posted_since(ctx, entity_id, run.actuals_watermark):
        reasons.append("new postings since the forecast was made")
    if run.as_of_date < cutover_for(today):
        reasons.append(f"made to {run.as_of_date.isoformat()}; a later month has closed")
    current = approved_version(entity_id, rolling.family_id)
    if current is None or str(current.id) != run.input_refs.get("assumption_set_id"):
        reasons.append("another version of the assumptions was approved")
    if len(run.input_refs.get("months", [])) != rolling.horizon:
        reasons.append("the horizon changed")
    return Freshness(run.stale or bool(reasons), tuple(reasons))


def refresh(ctx: WorkspaceContext, entity_id: UUID, today: date | None = None,
            trigger: str = CalcRun.Trigger.SCHEDULE) -> CalcRun | None:  # fmt: skip
    """A new run when the latest is stale or missing; None when it is current or inactive."""
    today = today or timezone.localdate()
    with transaction.atomic():
        entity = get_entity(ctx, entity_id, RUN).id
        rolling = RollingForecast.objects.select_for_update().filter(legal_entity_id=entity).first()
        if rolling is None or (not rolling.active and trigger != CalcRun.Trigger.USER):
            return None
        latest = next((r for r in runs_of(ctx, entity, rolling, 20) if r.status in FINISHED),
                      None)  # fmt: skip
        if latest is not None and not freshness(ctx, entity, rolling, latest, today).stale:
            return None
        if latest is not None and not latest.stale:
            type(latest).objects.filter(id=latest.id).update(stale=True)
        current = approved_version(entity, rolling.family_id)
        if current is None:
            raise ConflictError("No approved version of the rolling forecast's assumptions.")
        return run_projection(ctx, entity, current.id, cutover=cutover_for(today),
                              months=rolling.horizon, rolling=rolling.id, trigger=trigger,
                              supersedes=latest)  # fmt: skip


@dataclass
class RefreshReport:
    refreshed: int = 0
    current: int = 0
    skipped: list[str] = field(default_factory=list)


def refresh_all(today: date | None = None) -> RefreshReport:
    """The scheduled job: every active rolling forecast, workspace by workspace."""
    report = RefreshReport()
    with connection.cursor() as cursor:
        cursor.execute("SELECT projections_rolling_tenant_ids()")
        tenant_ids = [row[0] for row in cursor.fetchall()]
    for tenant_id in tenant_ids:
        with transaction.atomic():
            set_context(tenant_id=tenant_id)
            active = RollingForecast.objects.filter(active=True).select_related("updated_by")
            found = [(r.legal_entity_id, r.updated_by) for r in active]
            slug = Tenant.objects.get(id=tenant_id).slug
        for entity_id, user in found:
            try:
                with transaction.atomic():
                    set_context(tenant_id=tenant_id, user_id=user.id)
                    made = refresh(enter_workspace(user, slug), entity_id, today)
            except DomainError as refused:  # e.g. the user lost access or permission
                report.skipped.append(f"{tenant_id}/{entity_id}: {refused}")
                log.warning("projections_refresh skipped %s/%s: %s", tenant_id, entity_id, refused)
                continue
            if made is None:
                report.current += 1
            else:
                report.refreshed += 1
    return report


# --- accuracy -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    horizon: int  # months before
    run_id: UUID
    forecast: Decimal
    error: Decimal
    pct: Decimal | None  # |error| / |actual| in %, None when the actual is 0


@dataclass(frozen=True)
class AccuracyMonth:
    month: date
    actual: dict[str, Decimal]
    comparisons: dict[str, tuple[Comparison, ...]]


def actual_month(ctx: WorkspaceContext, entity_id: UUID,
                 month: date) -> dict[str, Decimal]:  # fmt: skip
    """Revenue and EBITDA of a closed month and its closing cash, from the ledger."""
    mapping = current_mapping(entity_id)
    lines: dict[str, Decimal] = {}
    for fact in actuals_monthly(ctx, entity_id, date_from=month, date_to=month_end(month)).facts:
        line = mapping.get(fact.account_id)
        if line is not None and line.statement == "PL":
            lines[line.code] = lines.get(line.code, ZERO) + fact.net_debit
    revenue = -sum((lines.get(c, ZERO) for c in REVENUE_LINES), ZERO)
    costs = sum((lines.get(c, ZERO) for c in ("COGS", *OPEX_LINES)), ZERO)
    _, net = opening_net(ctx, entity_id, before=month_end(month) + timedelta(days=1))
    cash = sum((amount for account_id, amount in net.items()
                if (line := mapping.get(account_id)) is not None and line.code == "BS.CASH"),
               ZERO)  # fmt: skip
    return {"PL.REVENUE": revenue, "PL.EBITDA": revenue - costs, "BS.CASH": cash}


def _forecast_values(run: CalcRun) -> dict[tuple[str, date], Decimal]:
    return {(r.series_key, r.period_start): r.value for r in calc_results(run)
            if r.granularity == "MONTH" and r.nature == "FORECAST" and r.series_key in MEASURES
            and r.value is not None}  # fmt: skip


def accuracy(ctx: WorkspaceContext, entity_id: UUID, today: date | None = None,
             months: int = 12) -> list[AccuracyMonth]:  # fmt: skip
    entity = get_entity(ctx, entity_id, READ).id
    rolling = RollingForecast.objects.filter(legal_entity_id=entity).first()
    if rolling is None:
        return []
    last_closed = month_start(cutover_for(today or timezone.localdate()))
    made: dict[date, CalcRun] = {}  # cut-over month -> its latest valid run
    for run in sorted((r for r in runs_of(ctx, entity, rolling) if r.status == "VALID"),
                      key=lambda r: r.created_at):  # fmt: skip
        made[month_start(run.as_of_date)] = run
    cache: dict[UUID, dict[tuple[str, date], Decimal]] = {}
    out = []
    for k in range(months - 1, -1, -1):
        month = add_months(last_closed, -k)
        actual = actual_month(ctx, entity, month)
        found: dict[str, list[Comparison]] = {m: [] for m in MEASURES}
        for h in HORIZONS:
            earlier = made.get(add_months(month, -h))
            if earlier is None:
                continue
            values = cache.setdefault(earlier.id, _forecast_values(earlier))
            for measure in MEASURES:
                expected = values.get((measure, month))
                if expected is None:
                    continue
                error = expected - actual[measure]
                pct = None
                if actual[measure] != 0:
                    pct = (abs(error) / abs(actual[measure]) * 100).quantize(
                        Decimal("0.01"), ROUND_HALF_UP
                    )
                found[measure].append(Comparison(h, earlier.id, expected, error, pct))
        out.append(AccuracyMonth(month, actual, {m: tuple(v) for m, v in found.items()}))
    return out
