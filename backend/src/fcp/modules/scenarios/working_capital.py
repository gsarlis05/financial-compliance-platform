"""Working-capital forecasting (M7-4, brief 21 §3; backlog M7 "working-capital forecasting
(DSO/DIO/DPO driven)").

A view over a projection of an approved assumption set, or of a shared scenario (its overrides
applied), computed now by the unchanged projection engine:
- by month: trade receivables, inventory and trade payables as projected; net working capital
  (receivables + inventory - payables); its change, and the cash effect of that change (the
  cash flow statement's working-capital lines);
- the days that drive them (DSO, DIO, DPO) and the cash conversion cycle (DSO + DIO - DPO), next
  to the days observed over the 12 months to the cut-over;
- **"What is N days worth?":** the cash released (or absorbed) by collecting N days faster, holding
  N days less stock, or paying N days later, worked out by running the engine again with the days
  changed by N for every month, not estimated.
Figures are FORECAST for an assumption set and HYPOTHETICAL for a scenario.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from fcp.core.errors import ValidationFailedError
from fcp.modules.projections.api import EngineInput, Projection, observed_days, project
from fcp.modules.tenancy.api import WorkspaceContext

from . import sensitivity as sens
from .sensitivity_runs import base as analysis_base

ZERO = Decimal("0.00")
DAY_DRIVERS = ("dso", "dio", "dpo")


@dataclass(frozen=True)
class Month:
    month: date
    receivables: Decimal
    inventory: Decimal
    payables: Decimal
    net: Decimal  # receivables + inventory - payables
    change: Decimal  # against the month before (the cut-over for the first)
    cash_effect: Decimal  # the cash flow statement's working-capital lines
    dso: Decimal
    dio: Decimal
    dpo: Decimal
    ccc: Decimal  # DSO + DIO - DPO


def table(p: Projection, inp: EngineInput) -> list[Month]:
    def day(key: str, month: date) -> Decimal:
        return inp.drivers.get((key, ""), {}).get(month, Decimal(0))

    opening = p.opening
    previous = opening["BS.AR"] + opening["BS.INVENTORY"] - opening["BS.AP"]
    rows = []
    for m in p.months:
        net = m.bs["BS.AR"] + m.bs["BS.INVENTORY"] - m.bs["BS.AP"]
        dso, dio, dpo = (day(k, m.month) for k in DAY_DRIVERS)
        rows.append(Month(
            month=m.month, receivables=m.bs["BS.AR"], inventory=m.bs["BS.INVENTORY"],
            payables=m.bs["BS.AP"], net=net, change=net - previous,
            cash_effect=m.cf["CF.WC.AR"] + m.cf["CF.WC.INVENTORY"] + m.cf["CF.WC.AP"],
            dso=dso, dio=dio, dpo=dpo, ccc=dso + dio - dpo,
        ))  # fmt: skip
        previous = net
    return rows


@dataclass(frozen=True)
class DaysValue:
    driver: str
    days: int
    closing_cash_change: Decimal  # at the end of the horizon
    lowest_cash_change: Decimal  # the change of the lowest month-end cash
    net_working_capital_change: Decimal  # at the end of the horizon (negative: released)
    by_month: list[tuple[date, Decimal]]  # the cash difference by month


def value_of_days(inp: EngineInput, driver: str, days: int) -> DaysValue:
    """The cash released by changing ``driver`` by ``days`` for every month (two engine runs)."""
    if driver not in DAY_DRIVERS:
        message = "driver: choose dso, dio or dpo."
        raise ValidationFailedError(message, field_errors={"driver": [message]})
    if not days or not -365 <= days <= 365:
        message = "days: from -365 to 365, not 0."
        raise ValidationFailedError(message, field_errors={"days": [message]})
    before, _ = project(inp)
    after, _ = project(sens.shock(inp, driver, days=days))
    cash = [(a.month, a.bs["BS.CASH"] - b.bs["BS.CASH"])
            for a, b in zip(after.months, before.months, strict=True)]  # fmt: skip

    def nwc(p: Projection) -> Decimal:
        last = p.months[-1].bs
        return last["BS.AR"] + last["BS.INVENTORY"] - last["BS.AP"]

    lowest = min(m.bs["BS.CASH"] for m in after.months) - min(
        m.bs["BS.CASH"] for m in before.months)  # fmt: skip
    return DaysValue(driver, days, cash[-1][1], lowest, nwc(after) - nwc(before), cash)


@dataclass(frozen=True)
class View:
    base_label: str
    nature: str
    watermark: int
    months: list[Month]
    observed: dict[str, Decimal]  # days over the 12 months to the cut-over
    observed_ccc: Decimal
    cutover: date


def view(ctx: WorkspaceContext, entity_id: UUID, *, set_id: UUID | None,
         scenario_id: UUID | None) -> View:  # fmt: skip
    b = analysis_base(ctx, entity_id, set_id=set_id, scenario_id=scenario_id)
    p, _ = project(b.inp)
    seen = observed_days(ctx, entity_id, b.inp.cutover)
    return View(
        base_label=b.label, nature="HYPOTHETICAL" if scenario_id else "FORECAST",
        watermark=b.watermark, months=table(p, b.inp), observed=seen,
        observed_ccc=seen["dso"] + seen["dio"] - seen["dpo"], cutover=b.inp.cutover,
    )  # fmt: skip


def days_worth(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    set_id: UUID | None,
    scenario_id: UUID | None,
    driver: str,
    days: int,
) -> DaysValue:
    b = analysis_base(ctx, entity_id, set_id=set_id, scenario_id=scenario_id)
    return value_of_days(b.inp, driver, days)
