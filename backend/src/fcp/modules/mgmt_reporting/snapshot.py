"""The frozen figures of a report pack (M8-1, doc 10 §9, FR-E3, AC-MR1, AC-MR6).

Generating a pack reads what the reports and runs hold now, under the generating user's own
permissions, and stores the result as plain data: amounts as exact decimal strings, each with its
nature, plus the references used (calc runs, budget versions, the ledger watermark). Nothing is
recomputed when the pack is read, so it reads the same for ever.

Each block is ``{"status": "ok" | "empty" | "denied", "reason": ..., "data": ...}``: a block the
user may not see says so instead of failing the pack (T30: a pack never holds more than its
preparer may see), and a block without data says why.

Blocks:
- ``statements``: the actual income statement, balance sheet and cash flow for the period, with
  the same period a year earlier;
- ``budget``: the variance report (M4-3) of the current approved annual budget for month,
  quarter to date, year to date and full year, against the budget, the original budget and the
  prior year, with each variance's explanation;
- ``kpis``: the latest KPI set for the period, calculated now (a stored, reproducible run) when
  there is none or it is out of date (V1-4: a pack no longer depends on someone having opened
  the dashboard for that period first);
- ``cash``: the latest 13-week cash forecast;
- ``projection``: the latest published projection covering the months after the period (its
  engine is pending professional review, and the block says so);
- ``goals``: each active goal's latest evaluation.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import DomainError, NotFoundError, PermissionDeniedError
from fcp.modules.budgeting.api import VarianceComparison, compute_variance, list_budget_views
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.cashflow.api import forecast_freshness, latest_cash_forecast
from fcp.modules.goals.api import goal_views
from fcp.modules.kpi.api import KpiSet, latest_kpi_set, run_kpi_set
from fcp.modules.metrics.api import canonical_digest, entity_statements
from fcp.modules.projections.api import forecast_values, published_projections
from fcp.modules.reporting.api import current_watermark, fiscal_year_start, unposted_count
from fcp.modules.tenancy.api import WorkspaceContext

FORMAT = 1  # the snapshot layout; a new layout gets a new number, old packs keep theirs
VIEWS = ("MONTH", "QTD", "YTD", "FULL_YEAR")
COMPARISONS = (VarianceComparison.ACTUAL_VS_BUDGET, VarianceComparison.CURRENT_VS_ORIGINAL,
               VarianceComparison.ACTUAL_VS_PRIOR_YEAR)  # fmt: skip
PROJECTED = ("PL.REVENUE", "PL.EBITDA", "PL.NET_INCOME", "CF.NET_CHANGE", "BS.CASH")
ENGINE_STATUS = "PENDING_PROFESSIONAL_REVIEW"
HORIZON = 12  # projected months shown after the period


@dataclass(frozen=True)
class Period:
    kind: str  # MONTH | QUARTER | YEAR
    start: date
    end: date

    @property
    def last_month(self) -> date:
        return month_start(self.end)


def period_of(ctx: WorkspaceContext, entity_id: UUID, kind: str, month: date) -> Period:
    """The month, fiscal quarter or fiscal year that contains ``month``."""
    month = month_start(month)
    if kind == "MONTH":
        return Period(kind, month, month_end(month))
    year = month_start(fiscal_year_start(ctx, entity_id, month))
    if kind == "YEAR":
        return Period(kind, year, month_end(add_months(year, 11)))
    elapsed = (month.year - year.year) * 12 + month.month - year.month
    first = add_months(year, elapsed - elapsed % 3)
    return Period(kind, first, month_end(add_months(first, 2)))


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _exact(value: Decimal | None) -> str | None:
    return None if value is None else format(value.normalize(), "f")


def _block(build: Callable[[], dict[str, Any]], empty: str) -> dict[str, Any]:
    try:
        return {"status": "ok", "reason": "", "data": build()}
    except PermissionDeniedError:
        return {"status": "denied", "reason": "You do not have permission to see this.",
                "data": {}}  # fmt: skip
    except NotFoundError as missing:
        return {"status": "empty", "reason": str(missing) or empty, "data": {}}
    except DomainError as refused:
        return {"status": "empty", "reason": str(refused) or empty, "data": {}}


# --- blocks ---------------------------------------------------------------------------------------


def statements(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> dict[str, Any]:
    found = entity_statements(ctx, entity_id, date_from=p.start, date_to=p.end)
    return {
        "watermark": found.watermark, "taxonomy": found.taxonomy, "ok": found.ok,
        "comparative": None if found.comparative is None else {
            "from": found.comparative.date_from.isoformat(),
            "to": found.comparative.date_to.isoformat()},
        "statements": [{
            "kind": s.kind, "name": s.name, "name_el": s.name_el,
            "rows": [{"kind": str(r.kind), "code": r.code, "name": r.name, "name_el": r.name_el,
                      "current": _money(r.current), "comparative": _money(r.comparative),
                      "nature": "ACTUAL"} for r in s.rows],
        } for s in found.all],
    }  # fmt: skip


def _current_budget(ctx: WorkspaceContext, entity_id: UUID, month: date) -> Any:
    if not ctx.can("budget.read", entity_id):
        raise PermissionDeniedError("You do not have permission to see budgets.")
    for view in list_budget_views(ctx, entity_id):
        b = view.budget
        if (
            b.kind == "ANNUAL"
            and view.current
            and b.fiscal_year_start <= month <= b.fiscal_year_end
        ):
            return view
    raise NotFoundError("No approved annual budget covers this period.")


def budget(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> dict[str, Any]:
    view = _current_budget(ctx, entity_id, p.last_month)
    reports = []
    for comparison in COMPARISONS:
        for kind in VIEWS:
            found = compute_variance(ctx, entity_id, view.current.id, month=p.last_month,
                                     view=kind, comparison=comparison)  # fmt: skip
            reports.append({
                "view": kind, "comparison": str(comparison), "watermark": found.watermark,
                "unposted": found.unposted,
                "window": [m.isoformat() for m in found.window],
                "rows": [{
                    "line_id": str(r.line_id) if r.line_id else None,
                    "taxonomy_code": r.taxonomy_code,
                    "account_id": str(r.account_id) if r.account_id else None,
                    "dimension_value_id": str(r.dimension_value_id) if r.dimension_value_id
                    else None,
                    "direction": r.direction, "subject": _money(r.subject),
                    "subject_nature": r.subject_nature, "comparison": _money(r.comparison),
                    "comparison_nature": r.comparison_nature, "variance": _money(r.variance),
                    "percent": _money(r.percent), "favourable": r.favourable,
                    "requires_explanation": r.requires_explanation,
                    "explanation": r.explanation.comment if r.explanation else None,
                } for r in found.rows],
            })  # fmt: skip
    return {
        "budget_id": str(view.budget.id), "budget_name": view.budget.name,
        "version_id": str(view.current.id), "version_number": view.current.number,
        "reports": reports,
    }  # fmt: skip


def _kpi_set(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> KpiSet:
    """The current KPI set for the period, calculated if there is none or it is out of date."""
    found: KpiSet | None
    try:
        found = latest_kpi_set(ctx, entity_id, date_from=p.start, date_to=p.end)
    except NotFoundError:
        found = None  # none calculated for this period yet: calculated below
    if found is not None and not found.out_of_date:
        return found
    try:
        return run_kpi_set(ctx, entity_id, date_from=p.start, date_to=p.end)
    except PermissionDeniedError:
        raise NotFoundError(
            "No KPI set for this period yet, and you may not calculate one: ask someone who "
            "runs the planning calculations."
        ) from None


def kpis(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> dict[str, Any]:
    found = _kpi_set(ctx, entity_id, p)
    values = []
    for r in found.values:
        meta = found.definitions.get(r.series_key)
        if meta is None:
            continue
        values.append({"key": meta.key, "name": meta.name, "name_el": meta.name_el,
                       "display": meta.display, "direction": meta.direction,
                       "value": _exact(r.value), "nm_reason": r.nm_reason,
                       "nature": r.nature})  # fmt: skip
    return {"run_id": str(found.run.id), "stale": found.out_of_date, "values": values}


def cash(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, Any]:
    found = latest_cash_forecast(ctx, entity_id)
    fresh = forecast_freshness(ctx, entity_id, found.run)
    return {
        "run_id": str(found.run.id), "as_of": found.run.as_of_date.isoformat(),
        "stale": fresh.stale, "nature": "FORECAST",
        "opening": _money(sum(found.opening_accounts.values(), Decimal(0))),
        "weeks": [{"label": w.label, "start": w.start.isoformat(), "end": w.end.isoformat(),
                   "closing": _money(w.amounts.get("closing", Decimal(0))),
                   "minimum": _money(w.amounts.get("minimum", Decimal(0)))}
                  for w in found.weeks],
        "first_shortfall": found.first_shortfall[0].isoformat() if found.first_shortfall else None,
    }  # fmt: skip


def projection(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> dict[str, Any]:
    if not ctx.can("planning.read", entity_id):
        raise PermissionDeniedError("You do not have permission to see projections.")
    after = add_months(p.last_month, 1)
    months = [add_months(after, k) for k in range(HORIZON)]
    for run in published_projections(ctx, entity_id):
        values = forecast_values(run)
        shown = [m for m in months if any(m in values.get(k, {}) for k in PROJECTED)]
        if not shown:
            continue
        return {
            "run_id": str(run.id), "as_of": run.as_of_date.isoformat(), "stale": run.stale,
            "nature": "FORECAST", "engine_status": ENGINE_STATUS,
            "months": [m.isoformat() for m in shown],
            "rows": {k: [_money(values.get(k, {}).get(m)) for m in shown] for k in PROJECTED},
        }  # fmt: skip
    raise NotFoundError("No published projection covers the months after this period.")


def goals(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, Any]:
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


# --- the snapshot ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Snapshot:
    data: dict[str, Any]
    digest: str
    watermark: int


def take(ctx: WorkspaceContext, entity_id: UUID, p: Period) -> Snapshot:
    """Every block of the pack, as plain data, with the references used."""
    watermark = current_watermark(ctx, entity_id)
    blocks = {
        "statements": _block(lambda: statements(ctx, entity_id, p), "No statements."),
        "budget": _block(lambda: budget(ctx, entity_id, p), "No budget."),
        "kpis": _block(lambda: kpis(ctx, entity_id, p), "No KPI set for this period yet."),
        "cash": _block(lambda: cash(ctx, entity_id), "No cash forecast yet."),
        "projection": _block(lambda: projection(ctx, entity_id, p), "No published projection."),
        "goals": _block(lambda: goals(ctx, entity_id), "No goals yet."),
    }
    runs = {k: blocks[k]["data"].get("run_id") for k in ("kpis", "cash", "projection")}
    budget_data = blocks["budget"]["data"]
    data = {
        "format": FORMAT,
        "period": {"kind": p.kind, "start": p.start.isoformat(), "end": p.end.isoformat()},
        "watermark": watermark,
        "unposted": unposted_count(ctx, entity_id, date_from=p.start, date_to=p.end),
        "references": {
            "calc_runs": {k: v for k, v in runs.items() if v},
            "budget_version_id": budget_data.get("version_id"),
            "watermark": watermark,
        },
        "blocks": blocks,
    }
    return Snapshot(data, canonical_digest(data), watermark)


def missing_explanations(data: dict[str, Any]) -> list[str]:
    """Budget lines whose variance against the current budget needs an explanation it lacks."""
    block = data["blocks"]["budget"]
    if block["status"] != "ok":
        return []
    found = []
    for report in block["data"]["reports"]:
        if report["comparison"] != VarianceComparison.ACTUAL_VS_BUDGET:
            continue
        for row in report["rows"]:
            if row["requires_explanation"] and not row["explanation"]:
                found.append(f"{row['taxonomy_code'] or row['account_id']} ({report['view']})")
    return found
