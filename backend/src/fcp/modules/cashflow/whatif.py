"""What-ifs on a cash forecast (M3-9, doc 10 §3.6, AC-CW7).

A what-if applies overrides to a forecast run's stored inputs and computes the result in memory.
It is never saved, so it can never replace the base. The kinds of override are:
- ``TIMING_SHIFT``: move the flows of a customer or supplier (``party``) and/or a category by N
  days (e.g. "customer C1 pays 60 days later");
- ``PCT_CHANGE``: scale the flows of a party and/or a category by a percentage, rounded to cents
  per flow;
- ``ONE_OFF``: add a dated receipt (positive) or payment (negative), with a reason.

Every flow an override changes or adds is HYPOTHETICAL (doc 10 P2). The base is computed again
from the same pinned data and must reproduce the run's stored output hash, so the comparison is
exactly against the run the user sees. The result is the base and the what-if, week by week,
with the difference.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.modules.metrics.api import CalcRun, Nature, Output, RunInputs
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .engine import ENGINE, KIND

MAX_OVERRIDES = 20
CENT = Decimal("0.01")
ZERO = Decimal(0)


@dataclass(frozen=True)
class Override:
    type: str  # TIMING_SHIFT | PCT_CHANGE | ONE_OFF
    party: str = ""
    category: str = ""
    days: int = 0
    percent: Decimal = ZERO
    day: date | None = None
    amount: Decimal = ZERO
    reason: str = ""


def _invalid(index: int, message: str) -> ValidationFailedError:
    return ValidationFailedError(
        f"Override {index + 1}: {message}", field_errors={f"overrides.{index}": [message]}
    )


def _check(index: int, o: Override) -> None:
    if o.type in ("TIMING_SHIFT", "PCT_CHANGE") and not (o.party or o.category):
        raise _invalid(index, "name a customer or supplier, a category, or both")
    if o.type == "TIMING_SHIFT" and not (o.days and -365 <= o.days <= 365):
        raise _invalid(index, "shift by 1 to 365 days, earlier (negative) or later")
    if o.type == "PCT_CHANGE" and not (o.percent and Decimal(-100) <= o.percent <= Decimal(1000)):
        raise _invalid(index, "change by -100% to +1000%, not 0")
    if o.type == "ONE_OFF":
        if o.day is None or not o.amount or o.amount != o.amount.quantize(CENT):
            raise _invalid(index, "a one-off needs a date and an amount in cents, not 0")
        if not o.reason.strip() or not o.category:
            raise _invalid(index, "a one-off needs a category and a reason")
    if o.type not in ("TIMING_SHIFT", "PCT_CHANGE", "ONE_OFF"):
        raise _invalid(index, f"unknown override {o.type}")


def _matches(flow: dict[str, str], o: Override) -> bool:
    return (not o.party or flow.get("party") == o.party) and (
        not o.category or flow["category"] == o.category
    )


def apply_overrides(
    refs: dict[str, Any], overrides: list[Override]
) -> tuple[dict[str, Any], list[int]]:
    """New run inputs with the overrides applied, and how many flows each one changed."""
    if not overrides or len(overrides) > MAX_OVERRIDES:
        raise ValidationFailedError(
            f"Give 1 to {MAX_OVERRIDES} overrides.", field_errors={"overrides": ["count"]}
        )
    flows = [dict(f) for f in refs.get("flows", [])]
    counts = []
    for index, o in enumerate(overrides):
        _check(index, o)
        changed = 0
        if o.type == "ONE_OFF":
            assert o.day is not None  # noqa: S101 (checked above)
            flows.append(
                {
                    "day": o.day.isoformat(),
                    "amount": f"{o.amount:.2f}",
                    "nature": Nature.HYPOTHETICAL.value,
                    "category": o.category,
                    "source": "WHATIF",
                    "ref": f"what_if:{index + 1}:{o.reason.strip()}",
                }
            )
            changed = 1
        for flow in flows:
            if o.type == "ONE_OFF" or flow["source"] == "WHATIF" or not _matches(flow, o):
                continue
            if o.type == "TIMING_SHIFT":
                day = date.fromisoformat(flow["day"]) + timedelta(days=o.days)
                flow["day"] = day.isoformat()
            else:
                scaled = Decimal(flow["amount"]) * (1 + o.percent / 100)
                flow["amount"] = f"{scaled.quantize(CENT, ROUND_HALF_UP):.2f}"
            flow["nature"] = Nature.HYPOTHETICAL.value
            changed += 1
        counts.append(changed)
    flows = [f for f in flows if Decimal(f["amount"]) != 0]  # -100% removes a flow
    return {**refs, "flows": sorted(flows, key=lambda f: (f["day"], f["source"], f["ref"]))}, counts


@dataclass
class WeekResult:
    label: str
    start: date
    closing: Decimal = ZERO
    net: Decimal = ZERO
    shortfall: bool = False


@dataclass
class Summary:
    weeks: list[WeekResult] = field(default_factory=list)
    first_shortfall: tuple[date, Decimal] | None = None
    hypothetical: Decimal = ZERO  # total of HYPOTHETICAL flows in the horizon


def summarise(output: Output) -> Summary:
    weeks: dict[date, WeekResult] = {}
    result = Summary()
    for v in output.values:
        if v.series_key == "cash.first_shortfall" and v.value is not None:
            result.first_shortfall = (v.period_start, v.value)
        if v.granularity != "WEEK":
            continue
        week = weeks.setdefault(
            v.period_start,
            WeekResult(
                f"{v.period_start.isocalendar()[0]}-W{v.period_start.isocalendar()[1]:02d}",
                v.period_start,
            ),
        )
        amount = v.value if v.value is not None else ZERO
        if v.series_key == "cash.closing":
            week.closing = amount
        elif v.series_key == "cash.net":
            week.net = amount
        elif v.series_key == "cash.shortfall":
            week.shortfall = amount > 0
        elif v.series_key == "cash.flow" and v.nature is Nature.HYPOTHETICAL:
            result.hypothetical += amount if v.dimensions[0] == "IN" else -amount
    result.weeks = [weeks[k] for k in sorted(weeks)]
    return result


@dataclass(frozen=True)
class WhatIf:
    run: CalcRun
    base: Summary
    scenario: Summary
    matched: list[int]


def _inputs(run: CalcRun, refs: dict[str, Any]) -> RunInputs:
    return RunInputs(
        run.kind,
        run.engine_version,
        run.legal_entity_id,
        run.as_of_date,
        run.actuals_watermark,
        refs,
    )


def what_if(ctx: WorkspaceContext, run: CalcRun, overrides: list[Override]) -> WhatIf:
    """Compare the forecast ``run`` with the same run under ``overrides`` (nothing is saved)."""
    get_entity(ctx, run.legal_entity_id, "planning.read")
    if run.kind != KIND or run.status != CalcRun.Status.VALID:
        raise ConflictError("What-ifs start from a valid cash forecast.")
    if run.engine_version != ENGINE.version:
        raise ConflictError("The forecast engine changed since this run; run a new forecast.")
    base_inputs = _inputs(run, dict(run.input_refs))
    data = ENGINE.load(ctx, base_inputs)
    base = ENGINE.compute(base_inputs, data)
    if base.digest() != run.output_hash:
        raise ConflictError("This forecast no longer reproduces; run a new forecast first.")
    refs, matched = apply_overrides(dict(run.input_refs), overrides)
    scenario = ENGINE.compute(_inputs(run, refs), data)
    return WhatIf(run, summarise(base), summarise(scenario), matched)
