"""Keeping forecasts current, their history, and how accurate they were (M3-8, doc 10 §3.4).

- **Freshness.** The latest forecast is out of date when any of these holds:
  - the entity has posted entries after the run's watermark;
  - the inputs prepared now differ from the snapshot the run used. This covers allocations,
    disputes, reconciliations, obligations, loans, tax payments, manual items and settings: every
    change the forecast depends on, without hooks in other modules;
  - the run's as-of date has passed.

  Runs are never edited; an out-of-date run is only marked stale.
- **Refresh.** ``refresh`` makes a new run as of today, superseding the stale one. The scheduled
  ``cashflow_refresh`` job does this every 15 minutes (no background threads in web processes). It
  acts with the permissions of the user who ran the entity's latest forecast, and skips an entity
  when that user no longer has them.
- **Accuracy.** For each fully elapsed ISO week, compare the net cash movement the forecast made
  1, 4 and 13 weeks earlier expected with the actual movement on the cash accounts.
  - Error = forecast - actual.
  - APE = |error| / |actual|, and is not meaningful when the actual is 0.
  - MAPE is the mean APE over the weeks, as a percentage.
  - Accuracy is reported, not gated (doc 12).
  - Only the total is compared: actual bank movements are not categorised yet.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import DomainError
from fcp.modules.calendar.api import week_label, week_start
from fcp.modules.metrics.api import (
    CalcRun,
    canonical_digest,
    current_mapping,
    latest_requesters,
    list_calc_runs,
    mark_stale,
)
from fcp.modules.reporting.api import cash_daily, posted_since
from fcp.modules.tenancy.api import Tenant, WorkspaceContext, enter_workspace, get_entity

from .engine import KIND
from .services import CASH_LINE, Forecast, forecast_of, prepare, run_forecast

log = logging.getLogger(__name__)
ZERO = Decimal(0)
HORIZONS = (1, 4, 13)
FINISHED = (CalcRun.Status.VALID, CalcRun.Status.INVALID)


@dataclass(frozen=True)
class Freshness:
    stale: bool
    reasons: tuple[str, ...]


def latest_run(ctx: WorkspaceContext, entity_id: UUID) -> CalcRun | None:
    return next((r for r in list_calc_runs(ctx, entity_id, KIND, 20) if r.status in FINISHED), None)


def freshness(
    ctx: WorkspaceContext, entity_id: UUID, run: CalcRun, today: date | None = None
) -> Freshness:
    today = today or timezone.localdate()
    reasons = []
    if posted_since(ctx, entity_id, run.actuals_watermark):
        reasons.append("new postings since the forecast was made")
    if canonical_digest(
        prepare(ctx, entity_id, run.as_of_date, permission="planning.read")
    ) != canonical_digest(run.input_refs):
        reasons.append("open items, commitments, settings or reconciliations changed")
    if run.as_of_date < today:
        reasons.append(f"made as of {run.as_of_date.isoformat()}; today is {today.isoformat()}")
    return Freshness(run.stale or bool(reasons), tuple(reasons))


def refresh(
    ctx: WorkspaceContext,
    entity_id: UUID,
    today: date | None = None,
    trigger: str = CalcRun.Trigger.SCHEDULE,
) -> CalcRun | None:
    """A new forecast as of today when the latest is out of date; None when it is current."""
    today = today or timezone.localdate()
    with transaction.atomic():
        entity = get_entity(ctx, entity_id, "planning.run")
        latest = latest_run(ctx, entity.id)
        if latest is None or not freshness(ctx, entity.id, latest, today).stale:
            return None
        mark_stale(entity.id, [KIND])
        return run_forecast(ctx, entity.id, today, trigger=trigger, supersedes=latest)


@dataclass
class RefreshReport:
    refreshed: int = 0
    current: int = 0
    skipped: list[str] = field(default_factory=list)


def refresh_all(today: date | None = None) -> RefreshReport:
    """The scheduled job: refresh every entity's out-of-date forecast, workspace by workspace."""
    report = RefreshReport()
    with connection.cursor() as cursor:
        cursor.execute("SELECT cashflow_forecast_tenant_ids()")
        tenant_ids = [row[0] for row in cursor.fetchall()]
    for tenant_id in tenant_ids:
        with transaction.atomic():
            set_context(tenant_id=tenant_id)
            owners = latest_requesters(KIND)
        for entity_id, user in owners:
            try:
                with transaction.atomic():
                    set_context(tenant_id=tenant_id, user_id=user.id)
                    slug = Tenant.objects.get(id=tenant_id).slug
                    ctx = enter_workspace(user, slug)
                    made = refresh(ctx, entity_id, today)
            except DomainError as refused:  # e.g. the user lost access or permission
                report.skipped.append(f"{tenant_id}/{entity_id}: {refused}")
                log.warning("cashflow_refresh skipped %s/%s: %s", tenant_id, entity_id, refused)
                continue
            if made is None:
                report.current += 1
            else:
                report.refreshed += 1
    return report


# --- history and accuracy -------------------------------------------------------------------------


def history(ctx: WorkspaceContext, entity_id: UUID, limit: int = 20) -> list[Forecast]:
    return [
        forecast_of(r) for r in list_calc_runs(ctx, entity_id, KIND, limit) if r.status in FINISHED
    ]


@dataclass(frozen=True)
class Comparison:
    horizon: int
    run_id: UUID
    forecast: Decimal
    error: Decimal
    ape: Decimal | None  # None: actual movement was 0 (not meaningful)


@dataclass(frozen=True)
class AccuracyWeek:
    label: str
    start: date
    actual: Decimal
    comparisons: tuple[Comparison, ...]


@dataclass(frozen=True)
class Accuracy:
    weeks: tuple[AccuracyWeek, ...]
    mape: dict[int, Decimal | None]  # percent, by horizon in weeks
    samples: dict[int, int]


def _actual_by_week(
    ctx: WorkspaceContext, entity_id: UUID, first: date, last: date
) -> dict[date, Decimal]:
    cash = [a for a, line in current_mapping(entity_id).items() if line.code == CASH_LINE]
    totals: dict[date, Decimal] = {}
    for fact in cash_daily(ctx, entity_id, account_ids=cash, date_from=first, date_to=last).facts:
        start = week_start(fact.period)
        totals[start] = totals.get(start, ZERO) + fact.net_debit
    return totals


def accuracy(ctx: WorkspaceContext, entity_id: UUID, as_of: date, weeks: int = 13) -> Accuracy:
    """Forecast against actual net cash movement for the ``weeks`` full weeks before ``as_of``."""
    entity = get_entity(ctx, entity_id, "planning.read")
    current = week_start(as_of)
    starts = [current - timedelta(weeks=k) for k in range(weeks, 0, -1)]
    actual = _actual_by_week(ctx, entity.id, starts[0], current - timedelta(days=1))
    made: dict[date, CalcRun] = {}  # week the forecast was made -> its latest valid run
    for run in sorted(
        (r for r in list_calc_runs(ctx, entity.id, KIND, 200) if r.status == CalcRun.Status.VALID),
        key=lambda r: r.created_at,
    ):
        made[week_start(run.as_of_date)] = run
    forecasts: dict[UUID, dict[date, Decimal]] = {}
    rows = []
    apes: dict[int, list[Decimal]] = {h: [] for h in HORIZONS}
    for start in starts:
        real = actual.get(start, ZERO)
        comparisons = []
        for h in HORIZONS:
            earlier = made.get(start - timedelta(weeks=h))
            if earlier is None:
                continue
            if earlier.id not in forecasts:
                forecasts[earlier.id] = {
                    w.start: w.amounts.get("net", ZERO) for w in forecast_of(earlier).weeks
                }
            if start not in forecasts[earlier.id]:
                continue
            expected = forecasts[earlier.id][start]
            error = expected - real
            ape = None if real == 0 else abs(error) / abs(real)
            if ape is not None:
                apes[h].append(ape)
            comparisons.append(Comparison(h, earlier.id, expected, error, ape))
        rows.append(AccuracyWeek(week_label(start), start, real, tuple(comparisons)))
    mape = {
        h: (sum(v, ZERO) / len(v) * 100).quantize(Decimal("0.01"), ROUND_HALF_UP) if v else None
        for h, v in apes.items()
    }
    return Accuracy(tuple(rows), mape, {h: len(v) for h, v in apes.items()})


def summary(f: Forecast) -> dict[str, Any]:
    """A run in the history list."""
    last = f.weeks[-1].amounts if f.weeks else {}
    return {
        "run_id": f.run.id,
        "as_of": f.run.as_of_date,
        "created_at": f.run.created_at,
        "status": f.run.status,
        "stale": f.run.stale,
        "trigger": f.run.trigger,
        "supersedes_id": f.run.supersedes_id,
        "actuals_watermark": f.run.actuals_watermark,
        "opening_cash": sum(f.opening_accounts.values(), ZERO),
        "closing_week_13": last.get("closing", ZERO),
        "first_shortfall": f.first_shortfall[0] if f.first_shortfall else None,
    }
