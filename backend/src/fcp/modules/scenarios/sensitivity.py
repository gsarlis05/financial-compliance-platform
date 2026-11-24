"""Sensitivity analysis and tornado (M7-3, doc 10 §3.6, brief 21 §3).

- **One variable:** one driver is varied over a range in up to 11 steps, and the chosen output is
  measured at each step.
- **Tornado:** each driver is shocked down and up by the same % on its own; drivers are ranked by
  the swing of the output (the absolute difference between the two), ties by the driver's name.

Each step is a deterministic re-run of the unchanged projection engine on the base's engine input
with that one driver changed. The base is an approved assumption set or a shared scenario (its
overrides applied first). Results are hypothetical; they are cached by their input hash for a
short time and never stored as versions (doc 02). This module is pure; the service in
``sensitivity_runs.py`` adds the base, the cache, quotas and the time limit (threat T34).

Drivers and how a shock applies (every month of the horizon):
- ``revenue``, ``revenue:<line>``, ``opex``, ``opex:<line>``, ``capex``: amounts x (1 + % / 100);
- ``gross_margin``: the margin x (1 + % / 100) (a relative change: 40% shocked by +10% is 44%);
- ``dso``, ``dio``, ``dpo``: days x (1 + % / 100), or + days (one-variable in days), not below 0;
- ``interest_rate``: every rate x (1 + % / 100): other debt, the credit facility and each loan.

Outputs: ``MIN_CASH`` (the lowest month-end cash), ``CLOSING_CASH`` (at the end of the horizon),
``FIRST_SHORTFALL`` (the number of months before cash first falls below zero; the whole horizon if
it never does), ``EBITDA`` and ``NET_INCOME`` (for a year of the horizon).
"""

import time
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.modules.projections.api import (
    OPEX_LINES,
    REVENUE_LINES,
    EngineInput,
    Projection,
    line_name,
    project,
)

HUNDRED = Decimal(100)
ZERO = Decimal(0)
OUTPUTS = ("MIN_CASH", "CLOSING_CASH", "FIRST_SHORTFALL", "EBITDA", "NET_INCOME")
DAYS = ("dso", "dio", "dpo")
MAX_STEPS = 11
MAX_DRIVERS = 25
LABELS = {
    "revenue": "Revenue (all lines)", "opex": "Operating costs (all lines)",
    "gross_margin": "Gross margin", "capex": "Capital expenditure", "dso": "Customer days (DSO)",
    "dio": "Stock days (DIO)", "dpo": "Supplier days (DPO)", "interest_rate": "Interest rates",
}  # fmt: skip
DRIVERS: tuple[str, ...] = (
    "revenue", *(f"revenue:{x}" for x in REVENUE_LINES), "gross_margin",
    "opex", *(f"opex:{x}" for x in OPEX_LINES), "dso", "dio", "dpo", "interest_rate", "capex",
)  # fmt: skip


def label(driver: str) -> str:
    """Plain words: a line driver is named by its projection line (e.g. "Payroll")."""
    if driver in LABELS:
        return LABELS[driver]
    line = driver.split(":", 1)[1]
    return line_name(f"PL.{line}", "en")


def _invalid(name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={name: [message]})


def keys_of(driver: str) -> list[tuple[str, str]]:
    if driver in ("revenue", "opex"):
        lines = REVENUE_LINES if driver == "revenue" else OPEX_LINES
        return [(driver, line) for line in lines]
    if ":" in driver:
        key, line = driver.split(":", 1)
        return [(key, line)]
    return [(driver, "")]


def shock(inp: EngineInput, driver: str, *, percent: Decimal = ZERO,
          days: int = 0) -> EngineInput:  # fmt: skip
    """The base with one driver changed by ``percent`` (relative) or by ``days`` (days drivers)."""
    if driver not in DRIVERS:
        raise _invalid("driver", f"driver: choose one of {', '.join(DRIVERS)}.")
    factor = 1 + percent / HUNDRED
    drivers = {k: dict(v) for k, v in inp.drivers.items()}
    if driver == "interest_rate":
        for name in ("interest_rate", "revolver_rate"):
            drivers[(name, "")] = {m: v * factor for m, v in drivers.get((name, ""), {}).items()}
        loans = tuple(
            replace(x, annual_rate=x.annual_rate * factor,
                    rate_path={m: r * factor for m, r in x.rate_path.items()})
            for x in inp.loans
        )  # fmt: skip
        return replace(inp, drivers=drivers, loans=loans)
    for pair in keys_of(driver):
        series = drivers.get(pair, {})
        changed = {m: v * factor + days for m, v in series.items()}
        if driver in DAYS:
            changed = {m: max(v, ZERO) for m, v in changed.items()}
        drivers[pair] = changed
    return replace(inp, drivers=drivers)


@dataclass(frozen=True)
class Measure:
    value: Decimal
    month: date | None = None  # the month of the lowest cash or the first shortfall


def measure(p: Projection, output: str, year: int | None = None) -> Measure:
    if output not in OUTPUTS:
        raise _invalid("output", f"output: choose one of {', '.join(OUTPUTS)}.")
    cash = [(m.month, m.bs["BS.CASH"]) for m in p.months]
    if output == "MIN_CASH":
        month, value = min(cash, key=lambda x: (x[1], x[0]))
        return Measure(value, month)
    if output == "CLOSING_CASH":
        return Measure(cash[-1][1], cash[-1][0])
    if output == "FIRST_SHORTFALL":
        for n, (month, value) in enumerate(cash):
            if value < 0:
                return Measure(Decimal(n), month)
        return Measure(Decimal(len(cash)))
    years = sorted({m.month.year for m in p.months})
    if year not in years:
        choices = ", ".join(map(str, years))
        raise _invalid("year", f"year: choose a year of the horizon ({choices}).")
    key = "PL.EBITDA" if output == "EBITDA" else "PL.NET_INCOME"
    return Measure(sum((m.pl[key] for m in p.months if m.month.year == year), ZERO))


class TimeLimitError(ConflictError):
    """A sensitivity run took longer than its time limit (threat T34)."""


def run(inp: EngineInput, output: str, year: int | None,
        deadline: int | None = None) -> Measure:  # fmt: skip
    if deadline is not None and time.monotonic_ns() > deadline:
        raise TimeLimitError("The analysis took longer than its time limit. Choose fewer "
                             "drivers or steps, or a shorter horizon.")  # fmt: skip
    return measure(project(inp)[0], output, year)


@dataclass(frozen=True)
class Point:
    shock: Decimal  # % or days
    result: Measure


def steps_of(low: Decimal, high: Decimal, count: int) -> list[Decimal]:
    """``count`` evenly spaced values from ``low`` to ``high`` (both included)."""
    if not 2 <= count <= MAX_STEPS:
        raise _invalid("steps", f"steps: from 2 to {MAX_STEPS}.")
    if high <= low:
        raise _invalid("high", "high: must be above low.")
    width = (high - low) / (count - 1)
    return [(low + width * k).quantize(Decimal("0.0001")).normalize() for k in range(count)]


def one_variable(  # noqa: PLR0913 (keyword-only options)
    inp: EngineInput,
    driver: str,
    values: list[Decimal],
    *,
    unit: str,
    output: str,
    year: int | None,
    deadline: int | None = None,
) -> list[Point]:
    """The output at each value of one driver (``unit`` PERCENT or DAYS)."""
    if unit == "DAYS" and driver not in DAYS:
        raise _invalid("unit", "unit: days apply to DSO, DIO and DPO only; use PERCENT.")
    out = []
    for v in values:
        changed = (shock(inp, driver, days=int(v)) if unit == "DAYS"
                   else shock(inp, driver, percent=v))  # fmt: skip
        out.append(Point(v, run(changed, output, year, deadline)))
    return out


@dataclass(frozen=True)
class Bar:
    driver: str
    label: str
    low: Measure  # at -shock %
    high: Measure  # at +shock %
    swing: Decimal


def tornado(inp: EngineInput, drivers: list[str], *, percent: Decimal, output: str,
            year: int | None, deadline: int | None = None) -> list[Bar]:  # fmt: skip
    """Each driver at -percent and +percent on its own, ranked by the swing of the output."""
    if not drivers or len(drivers) > MAX_DRIVERS or len(set(drivers)) != len(drivers):
        raise _invalid("drivers", f"drivers: from 1 to {MAX_DRIVERS} different drivers.")
    bars = []
    for d in drivers:
        low = run(shock(inp, d, percent=-percent), output, year, deadline)
        high = run(shock(inp, d, percent=percent), output, year, deadline)
        bars.append(Bar(d, label(d), low, high, abs(high.value - low.value)))
    return sorted(bars, key=lambda b: (-b.swing, b.driver))
