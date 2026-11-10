"""The CFO dashboard (M4-8, doc 10 §10, AC-DB1 to AC-DB5).

One request returns every widget for one period and comparison, so all widgets agree (AC-DB4):
- the **period** is a preset (month, quarter to date, year to date) ending in a chosen month. The
  quarter and year follow the entity's fiscal year, as the variance report does;
- the **comparison** is the budget or the same period a year earlier.

Widgets read what the reports and runs already hold, never a copy (doc 10 P1):
- **KPI cards**: the latest KPI set for the period (and for the prior-year period when comparing
  with the prior year). The page offers to calculate one when there is none;
- **cash**: the latest 13-week cash forecast, with its freshness;
- **budget vs actual** and **top variances**: the variance report (M4-3) for the current approved
  annual budget;
- **goals**: each active goal's latest evaluation;
- **alerts**: the open alerts.

A widget the user may not see says so (``denied``) instead of failing the page (AC-DB3), and one
without data says why (``empty``).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import DomainError, NotFoundError, PermissionDeniedError
from fcp.modules.budgeting.api import VarianceComparison, compute_variance, list_budget_views
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.cashflow.api import forecast_freshness, latest_cash_forecast
from fcp.modules.goals.api import goal_views
from fcp.modules.kpi.api import latest_kpi_set
from fcp.modules.reporting.api import fiscal_year_start
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import alerts as alert_service

PRESETS = ("MONTH", "QTD", "YTD")
COMPARISONS = ("BUDGET", "PRIOR_YEAR")
WIDGETS = ("kpis", "cash", "budget", "top_variances", "goals", "alerts")
DEFAULT_KPIS = ("GROSS_MARGIN", "EBITDA_MARGIN", "CURRENT_RATIO", "DSO", "CASH_RUNWAY",
                "REVENUE_GROWTH")  # fmt: skip
TOP = 5


@dataclass(frozen=True)
class Period:
    preset: str
    month: date  # first day of the month the period ends in
    date_from: date
    date_to: date
    fiscal_year_start: date
    comparison: str

    @property
    def prior(self) -> tuple[date, date]:
        return add_months(self.date_from, -12), month_end(add_months(self.month, -12))


def period(ctx: WorkspaceContext, entity_id: UUID, preset: str, month: date,
           comparison: str) -> Period:  # fmt: skip
    month = month_start(month)
    try:
        start = fiscal_year_start(ctx, entity_id, month)
    except DomainError:
        start = date(month.year, 1, 1)
    start = month_start(start)
    if preset == "MONTH":
        first = month
    elif preset == "QTD":
        elapsed = (month.year - start.year) * 12 + month.month - start.month
        first = add_months(start, elapsed - elapsed % 3)
    else:
        first = start
    return Period(preset, month, first, month_end(month), start, comparison)


@dataclass
class Widget:
    status: str = "ok"  # ok | empty | denied
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def _guard(build: Callable[[], dict[str, Any]], empty: str) -> Widget:
    try:
        return Widget(data=build())
    except PermissionDeniedError:
        return Widget("denied", "You do not have permission to see this.")
    except NotFoundError as missing:
        return Widget("empty", str(missing) or empty)
    except DomainError as refused:
        return Widget("empty", str(refused))


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _exact(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


# --- widgets --------------------------------------------------------------------------------------


def _kpis(ctx: WorkspaceContext, entity_id: UUID, p: Period, keys: list[str]) -> dict[str, Any]:
    current = latest_kpi_set(ctx, entity_id, date_from=p.date_from, date_to=p.date_to)
    prior: dict[str, Any] = {}
    if p.comparison == "PRIOR_YEAR":
        try:
            first, last = p.prior
            earlier = latest_kpi_set(ctx, entity_id, date_from=first, date_to=last)
            prior = {r.series_key: r for r in earlier.values}
        except NotFoundError:
            prior = {}
    wanted = [f"kpi.{k}" for k in keys]
    rows = {r.series_key: r for r in current.values}
    cards = []
    for key in wanted:
        r, meta = rows.get(key), current.definitions.get(key)
        if r is None or meta is None:
            continue
        before = prior.get(key)
        cards.append({
            "key": meta.key, "name": meta.name, "name_el": meta.name_el, "display": meta.display,
            "direction": meta.direction, "result_id": str(r.id), "value": _exact(r.value),
            "nm_reason": r.nm_reason, "nature": r.nature,
            "comparison_value": _exact(before.value) if before is not None else None,
        })  # fmt: skip
    return {"run_id": str(current.run.id), "stale": current.out_of_date, "cards": cards}


def _cash(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, Any]:
    found = latest_cash_forecast(ctx, entity_id)
    fresh = forecast_freshness(ctx, entity_id, found.run)
    opening = sum(found.opening_accounts.values(), Decimal(0))
    return {
        "run_id": str(found.run.id), "as_of": found.run.as_of_date.isoformat(),
        "stale": fresh.stale, "opening": _money(opening),
        "weeks": [{"label": w.label, "start": w.start.isoformat(), "end": w.end.isoformat(),
                   "closing": _money(w.amounts.get("closing", Decimal(0))),
                   "minimum": _money(w.amounts.get("minimum", Decimal(0)))}
                  for w in found.weeks],
        "first_shortfall": found.first_shortfall[0].isoformat() if found.first_shortfall else None,
    }  # fmt: skip


def _current_budget(ctx: WorkspaceContext, entity_id: UUID, month: date) -> Any:
    for view in list_budget_views(ctx, entity_id):
        b = view.budget
        covers = b.fiscal_year_start <= month <= b.fiscal_year_end
        if b.kind == "ANNUAL" and view.current and covers:
            return view
    raise NotFoundError("No approved annual budget covers this month.")


def _variance(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> dict[str, Any]:
    if not ctx.can("budget.read", entity_id):
        raise PermissionDeniedError("You do not have permission to see budgets.")
    view = _current_budget(ctx, entity_id, p.month)
    comparison = (VarianceComparison.ACTUAL_VS_BUDGET if p.comparison == "BUDGET"
                  else VarianceComparison.ACTUAL_VS_PRIOR_YEAR)  # fmt: skip
    found = compute_variance(ctx, entity_id, view.current.id, month=p.month, view=p.preset,
                             comparison=comparison)  # fmt: skip
    kept = [r for r in found.rows if r.line_id is not None]
    rows = [{
        "line": r.taxonomy_code or str(r.account_id), "dimension_value_id":
            str(r.dimension_value_id) if r.dimension_value_id else None,
        "direction": r.direction, "actual": _money(r.subject), "actual_nature": r.subject_nature,
        "comparison": _money(r.comparison), "comparison_nature": r.comparison_nature,
        "variance": _money(r.variance), "percent": _money(r.percent),
        "favourable": r.favourable, "requires_explanation": r.requires_explanation,
    } for r in kept]  # fmt: skip
    worst = sorted((i for i, r in enumerate(kept) if r.favourable is False),
                   key=lambda i: abs(kept[i].variance), reverse=True)[:TOP]  # fmt: skip
    top = [rows[i] for i in worst]
    return {
        "budget_id": str(view.budget.id), "budget_name": view.budget.name,
        "version_id": str(view.current.id), "version_number": view.current.number,
        "watermark": found.watermark, "unposted": found.unposted, "rows": rows, "top": top,
    }  # fmt: skip


def _goals(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, Any]:
    items = []
    for v in goal_views(ctx, entity_id):
        g, latest = v.goal, v.latest
        items.append({
            "id": str(g.id), "name": g.name, "metric_name": g.metric_name, "unit": g.unit,
            "display": g.display, "period_end": g.period_end.isoformat(),
            "target": _exact(v.current.target_value), "direction": v.current.direction,
            "status": latest.status if latest else None,
            "projected": _exact(latest.projected) if latest else None,
            "as_of": latest.as_of.isoformat() if latest else None,
        })  # fmt: skip
    return {"goals": items}


def _alerts(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, Any]:
    counts = alert_service.open_counts(ctx, entity_id)
    latest = alert_service.alerts(ctx, entity_id, limit=TOP)
    return {"warning": counts["WARNING"], "critical": counts["CRITICAL"],
            "latest": [{"id": str(a.id), "title": a.title, "severity": a.severity,
                        "kind": a.kind, "created_at": a.created_at.isoformat()}
                       for a in latest]}  # fmt: skip


def overview(ctx: WorkspaceContext, entity_id: UUID, p: Period,
             kpi_keys: list[str]) -> dict[str, Widget]:  # fmt: skip
    entity = get_entity(ctx, entity_id, "planning.read")
    variance = _guard(lambda: _variance(ctx, entity.id, p), "No budget")
    top = Widget(
        variance.status,
        variance.reason,
        {k: variance.data[k] for k in ("budget_name", "top")} if variance.data else {},
    )
    return {
        "kpis": _guard(lambda: _kpis(ctx, entity.id, p, kpi_keys),
                       "No KPI set for this period yet."),
        "cash": _guard(lambda: _cash(ctx, entity.id), "No cash forecast yet."),
        "budget": variance,
        "top_variances": top,
        "goals": _guard(lambda: _goals(ctx, entity.id), "No goals yet."),
        "alerts": _guard(lambda: _alerts(ctx, entity.id), "No alerts."),
    }  # fmt: skip
