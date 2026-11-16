"""The full-year outlook (M6-5, brief §3, AC-OL1), and the projection as a goal's likely outcome.

- **Months.** The fiscal year containing the chosen day. Months up to the projection's cut-over are
  **actual**, from the posted books (through ``reporting``); later months are **forecast**, from
  the latest valid, published projection whose months reach them. Without one, the outlook shows
  the actual months that have closed and says so.
- **Lines.** The income statement as the projection has it (revenue, cost of sales, operating
  costs by line, depreciation, net finance costs, tax and the subtotals) and cash at each month
  end. Actual net finance costs are interest expense plus exchange differences less interest
  income; depreciation includes amortisation.
- **Natures.** Each row is ``blend(actual, forecast, cut-over)``: every month keeps its nature and
  the two are never added silently. Quarters (of the fiscal year) and the year are sums of their
  months (cash: the last month's), labelled ACTUAL, FORECAST, or ACTUAL+FORECAST when they span
  the divider.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.utils import timezone

from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.metrics.api import (
    ActualSeries,
    CalcRun,
    Nature,
    PlanSeries,
    blend,
    calc_results,
    current_mapping,
    list_calc_runs,
)
from fcp.modules.reporting.api import actuals_monthly, fiscal_year_start, opening_net
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .assumptions import READ
from .drivers import OPEX_LINES, REVENUE_LINES
from .runs import KIND

ZERO = Decimal("0.00")
CASH = "BS.CASH"
FLOWS = (
    *(f"PL.{c}" for c in REVENUE_LINES), "PL.REVENUE", "PL.COGS", "PL.GROSS_PROFIT",
    *(f"PL.{c}" for c in OPEX_LINES), "PL.OPEX", "PL.EBITDA", "PL.DA", "PL.EBIT", "PL.INTEREST",
    "PL.PBT", "PL.TAX", "PL.NET_INCOME",
)  # fmt: skip
ROWS = (*FLOWS, CASH)
# Taxonomy line -> the projection's line, for goals (natural direction, as budgets give it).
GOAL_LINES = {
    **{c: f"PL.{c}" for c in (*REVENUE_LINES, *OPEX_LINES)},
    "COGS": "PL.COGS", "DA.DEPRECIATION": "PL.DA", "INT.EXPENSE": "PL.INTEREST",
    "TAX.INCOME": "PL.TAX",
}  # fmt: skip


def published(ctx: WorkspaceContext, entity_id: UUID) -> list[CalcRun]:
    """Valid, published projections, newest first."""
    return [r for r in list_calc_runs(ctx, entity_id, KIND, 200)
            if r.status == CalcRun.Status.VALID and r.is_published]  # fmt: skip


def _months(run: CalcRun) -> list[date]:
    return [date.fromisoformat(m) for m in run.input_refs.get("months", [])]


def covering(ctx: WorkspaceContext, entity_id: UUID, months: list[date]) -> CalcRun | None:
    """The latest published projection that projects any of ``months``."""
    wanted = set(months)
    return next((r for r in published(ctx, entity_id) if wanted & set(_months(r))), None)


def forecast_values(run: CalcRun) -> dict[str, dict[date, Decimal]]:
    found: dict[str, dict[date, Decimal]] = {}
    for r in calc_results(run):
        if r.granularity == "MONTH" and r.nature == "FORECAST" and r.value is not None:
            found.setdefault(r.series_key, {})[r.period_start] = r.value.quantize(Decimal("0.01"))
    return found


def actual_values(ctx: WorkspaceContext, entity_id: UUID,
                  months: list[date]) -> dict[str, dict[date, Decimal]]:  # fmt: skip
    """The projection's lines for closed months, from the posted books."""
    out: dict[str, dict[date, Decimal]] = {key: {} for key in ROWS}
    if not months:
        return out
    mapping = current_mapping(entity_id)
    cash_accounts = {a for a, line in mapping.items() if line.code == CASH}
    by_line: dict[tuple[str, date], Decimal] = {}
    facts = actuals_monthly(ctx, entity_id, date_from=months[0], date_to=month_end(months[-1]))
    for fact in facts.facts:
        line = mapping.get(fact.account_id)
        if line is not None and line.statement == "PL":
            slot = (line.code, fact.period)
            by_line[slot] = by_line.get(slot, ZERO) + fact.net_debit

    def debit(month: date, *codes: str) -> Decimal:
        return sum((by_line.get((c, month), ZERO) for c in codes), ZERO)

    for m in months:
        row = {f"PL.{c}": -debit(m, c) for c in REVENUE_LINES}
        row |= {f"PL.{c}": debit(m, c) for c in OPEX_LINES}
        row["PL.REVENUE"] = sum((row[f"PL.{c}"] for c in REVENUE_LINES), ZERO)
        row["PL.COGS"] = debit(m, "COGS")
        row["PL.GROSS_PROFIT"] = row["PL.REVENUE"] - row["PL.COGS"]
        row["PL.OPEX"] = sum((row[f"PL.{c}"] for c in OPEX_LINES), ZERO)
        row["PL.EBITDA"] = row["PL.GROSS_PROFIT"] - row["PL.OPEX"]
        row["PL.DA"] = debit(m, "DA.DEPRECIATION", "DA.AMORTISATION")
        row["PL.EBIT"] = row["PL.EBITDA"] - row["PL.DA"]
        row["PL.INTEREST"] = debit(m, "INT.EXPENSE", "FX.DIFF", "INT.INCOME")
        row["PL.PBT"] = row["PL.EBIT"] - row["PL.INTEREST"]
        row["PL.TAX"] = debit(m, "TAX.INCOME")
        row["PL.NET_INCOME"] = row["PL.PBT"] - row["PL.TAX"]
        _, net = opening_net(ctx, entity_id, before=month_end(m) + timedelta(days=1))
        row[CASH] = sum((v for a, v in net.items() if a in cash_accounts), ZERO)
        for key, value in row.items():
            out[key][m] = value
    return out


@dataclass(frozen=True)
class Column:
    start: date
    end: date
    granularity: str  # MONTH, QUARTER, YEAR
    nature: str  # ACTUAL, FORECAST or ACTUAL+FORECAST


@dataclass(frozen=True)
class Outlook:
    year_start: date
    cutover: date | None  # the last actual month end; None when nothing is forecast
    run: CalcRun | None
    columns: list[Column]
    rows: dict[str, list[Decimal | None]]
    note: str


def _bucket_nature(natures: set[Nature]) -> str:
    return "+".join(n.value for n in (Nature.ACTUAL, Nature.FORECAST) if n in natures)


def outlook(ctx: WorkspaceContext, entity_id: UUID, day: date,
            today: date | None = None) -> Outlook:  # fmt: skip
    entity = get_entity(ctx, entity_id, READ).id
    start = fiscal_year_start(ctx, entity, day)
    months = [add_months(start, n) for n in range(12)]
    run = covering(ctx, entity, months)
    if run is not None:
        cutover = date.fromisoformat(run.input_refs["cutover"])
        note = (f"Actuals to {cutover:%d/%m/%Y}, then the published projection of "
                f"{run.created_at:%d/%m/%Y}.")  # fmt: skip
    else:
        cutover = month_end(add_months(month_start(today or timezone.localdate()), -1))
        note = "No published projection reaches this year: actual months only."
    first_forecast = add_months(month_start(cutover), 1)
    actual_months = [m for m in months if m < first_forecast]
    actual = actual_values(ctx, entity, actual_months)
    forecast = forecast_values(run) if run is not None else {}
    projected = set(_months(run)) if run is not None else set()
    shown = [m for m in months if m < first_forecast or m in projected]
    return _assemble(start, months, shown, actual, forecast, first_forecast, run, note)


def _assemble(  # noqa: PLR0913, PLR0917 (the parts of one outlook)
    start: date,
    months: list[date],
    shown: list[date],
    actual: dict[str, dict[date, Decimal]],
    forecast: dict[str, dict[date, Decimal]],
    first_forecast: date,
    run: CalcRun | None,
    note: str,
) -> Outlook:
    rows: dict[str, list[Decimal | None]] = {}
    natures: dict[date, Nature] = {}
    columns: list[Column] = []
    for key in ROWS:
        blended = blend(
            ActualSeries({m: v for m, v in actual.get(key, {}).items() if m in shown}),
            PlanSeries(Nature.FORECAST,
                       {m: v for m, v in forecast.get(key, {}).items() if m in shown}),
            first_forecast,
        )  # fmt: skip
        points = {p.period: p for p in blended.points}
        natures |= {p.period: p.nature for p in blended.points}
        values: list[Decimal | None] = [points[m].value if m in points else None for m in months]
        for q in range(4):
            values.append(_total(key, [points.get(m) for m in months[3 * q : 3 * q + 3]]))
        values.append(_total(key, [points.get(m) for m in months]))
        rows[key] = values
    for m in months:
        nature = natures.get(m)
        columns.append(Column(m, month_end(m), "MONTH", nature.value if nature else ""))
    for q in range(4):
        part = months[3 * q : 3 * q + 3]
        label = _bucket_nature({natures[m] for m in part if m in natures})
        columns.append(Column(part[0], month_end(part[-1]), "QUARTER", label))
    columns.append(Column(start, month_end(months[-1]), "YEAR",
                          _bucket_nature(set(natures.values()))))  # fmt: skip
    cutover = None if run is None else first_forecast - timedelta(days=1)
    return Outlook(start, cutover, run, columns, rows, note)


def _total(key: str, points: list[Any]) -> Decimal | None:
    """A bucket: the sum of its months, or the last month's cash; None unless every month is
    known."""
    if not points or any(p is None for p in points):
        return None
    if key == CASH:
        return Decimal(points[-1].value)
    return sum((Decimal(p.value) for p in points), ZERO)


# --- goals (M4-6) use the outlook -----------------------------------------------------------------


def projected_plan(ctx: WorkspaceContext, entity_id: UUID,
                   months: list[date]) -> dict[str, Any] | None:  # fmt: skip
    """The latest published projection over ``months``, shaped like an approved budget (amounts
    per ``line:<code>`` and month, in the line's natural direction) for a goal's likely outcome;
    None when the user cannot read plans or no published projection reaches the months."""
    if not months or not ctx.can(READ, entity_id):
        return None
    run = covering(ctx, entity_id, months)
    if run is None:
        return None
    values = forecast_values(run)
    projected = sorted(set(_months(run)) & set(months))
    return {
        "source": "PROJECTION",
        "versions": [{"id": str(run.id), "budget": "projection", "number": "",
                      "fiscal_year_start": projected[0].isoformat(),
                      "fiscal_year_end": month_end(projected[-1]).isoformat()}],
        "amounts": {f"line:{code}": {m.isoformat(): str(values.get(key, {}).get(m, ZERO))
                                     for m in projected}
                    for code, key in GOAL_LINES.items()},
    }  # fmt: skip
