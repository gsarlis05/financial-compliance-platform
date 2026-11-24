"""Applying a scenario's overrides to its base (M7-2, doc 10 §8): a pure function, no database.

The base is the engine input of a projection from the scenario's approved assumption set (its
drivers by month, loans and opening balance sheet). Overrides apply **in their order**, each to
the result of the ones before it, and change only that copy; the projection engine then runs
unchanged (eight invariants). Every value stays unrounded; the engine rounds each statement line
to cents once (doc 10 §2.4).

How each type changes the base:
- ``PCT_CHANGE``: the lines' monthly amounts x (1 + % / 100) in the window.
- ``ABS_CHANGE``: + the amount each month of the window; a line may not become negative.
- ``TIMING_SHIFT`` DAYS: + days to DSO, DIO or DPO in the window (not below 0). MONTHS: the
  line's amounts move by whole months inside the window; months emptied become 0 and amounts
  moved past the window's end fall outside it (stated in the notes).
- ``NEW_DEBT``: a new loan with its terms (drawn at the end of its month).
- ``NEW_HIRE``: + headcount x gross salary x (1 + employer cost % / 100) on payroll each month.
- ``CAPEX``: + capital expenditure in its month with its own useful life (straight-line from the
  set's start convention of that month); funded by a loan, a loan ``CAPEX-<n>`` of that amount is
  drawn in the same month.
- ``ONE_OFF``: an expense on a cost line in its month, or a payment that settles part of a held
  liability (other or tax payables; at most the balance at the cut-over, in total).
- ``RATE_CHANGE``: + percentage points from a month on the other debt's rate, the credit
  facility's rate and/or the named loans' rate paths (not below 0).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from typing import Any

from fcp.core.errors import ValidationFailedError
from fcp.modules.calendar.api import add_months
from fcp.modules.projections.api import (
    OPEX_LINES,
    REVENUE_LINES,
    EngineInput,
    ExtraCapex,
    LoanTerms,
    NewLoanRow,
)

HUNDRED = Decimal(100)
ZERO = Decimal(0)
Drivers = dict[tuple[str, str], dict[date, Decimal]]


@dataclass(frozen=True)
class Item:
    """One override as applied: its id, order, type and normalised parameters."""

    id: str
    seq: int
    type: str
    params: dict[str, Any]

    @property
    def label(self) -> str:
        return f"Override {self.seq} ({self.type})"


@dataclass
class Applied:
    inp: EngineInput
    notes: list[str] = field(default_factory=list)
    # Overrides an assumption set cannot hold (promotion refuses them), by label.
    inexpressible: list[str] = field(default_factory=list)
    new_loans: list[NewLoanRow] = field(default_factory=list)
    drivers: Drivers = field(default_factory=dict)  # the changed drivers, for promotion


def _month(raw: str) -> date:
    return date.fromisoformat(raw)


class _State:
    def __init__(self, inp: EngineInput) -> None:
        self.inp = inp
        self.drivers: Drivers = {k: dict(v) for k, v in inp.drivers.items()}
        self.loans: list[LoanTerms] = list(inp.loans)
        self.extra: list[ExtraCapex] = list(inp.extra_capex)
        self.settlements: dict[date, dict[str, Decimal]] = {
            m: dict(v) for m, v in inp.settlements.items()
        }
        self.out = Applied(inp)

    def series(self, key: str, line: str = "") -> dict[date, Decimal]:
        return self.drivers.setdefault((key, line), {})

    def window(self, p: dict[str, Any]) -> list[date]:
        start, end = _month(p["start_month"]), _month(p["end_month"])
        return [m for m in self.inp.months if start <= m <= end]

    def fail(self, item: Item, message: str) -> ValidationFailedError:
        text = f"{item.label}: {message}"
        return ValidationFailedError(text, field_errors={f"overrides.{item.seq}": [text]})

    def not_negative(self, item: Item, series: dict[date, Decimal], what: str) -> None:
        for m in self.inp.months:
            if series.get(m, ZERO) < 0:
                raise self.fail(item, f"{what} would be negative in {m:%m/%Y}.")

    def add_loan(self, item: Item, terms: LoanTerms, name: str) -> None:
        if any(loan.code == terms.code for loan in self.loans):
            raise self.fail(item, f"a loan {terms.code} already exists.")
        self.loans.append(terms)
        self.series("loan_rate", terms.code).update(
            dict.fromkeys(self.inp.months, terms.annual_rate)
        )
        assert terms.drawdown_month is not None  # noqa: S101 (new loans always have one)
        self.out.new_loans.append(NewLoanRow(
            code=terms.code, name=name or terms.code, amount=terms.amount,
            drawdown_month=terms.drawdown_month, structure=terms.structure,
            term_months=terms.term_months, annual_rate=terms.annual_rate,
            interest_only_months=terms.interest_only_months,
        ))  # fmt: skip


def _lines(driver: str, chosen: list[str]) -> tuple[str, ...]:
    every = REVENUE_LINES if driver == "revenue" else OPEX_LINES
    return tuple(chosen) or every


def _pct_change(s: _State, item: Item) -> None:
    p = item.params
    factor = 1 + Decimal(p["percent"]) / HUNDRED
    for line in _lines(p["driver"], p["lines"]):
        series = s.series(p["driver"], line)
        for m in s.window(p):
            series[m] = series.get(m, ZERO) * factor


def _abs_change(s: _State, item: Item) -> None:
    p = item.params
    series = s.series(p["driver"], p["line"])
    for m in s.window(p):
        series[m] = series.get(m, ZERO) + Decimal(p["amount"])
    s.not_negative(item, series, p["line"])


def _timing_shift(s: _State, item: Item) -> None:
    p = item.params
    window = s.window(p)
    if p["mode"] == "DAYS":
        series = s.series(p["driver"])
        for m in window:
            series[m] = series.get(m, ZERO) + Decimal(p["days"])
        s.not_negative(item, series, p["driver"].upper())
        return
    series = s.series(p["driver"], p["line"])
    before = dict(series)
    inside = set(window)
    k = int(p["months"])
    for m in window:
        source = add_months(m, -k)
        series[m] = before.get(source, ZERO) if source in inside else ZERO
    lost = sum((before.get(m, ZERO) for m in window if add_months(m, k) not in inside), ZERO)
    if lost:
        s.out.notes.append(f"{item.label}: {lost:.2f} of {p['line']} moved outside the window.")


def _new_debt(s: _State, item: Item) -> None:
    p = item.params
    s.add_loan(item, LoanTerms(
        code=p["code"], structure=p["structure"], term_months=int(p["term_months"]),
        annual_rate=Decimal(p["annual_rate"]), amount=Decimal(p["amount"]),
        drawdown_month=_month(p["drawdown_month"]),
        interest_only_months=int(p["interest_only_months"]),
    ), p.get("name", ""))  # fmt: skip


def _new_hire(s: _State, item: Item) -> None:
    p = item.params
    monthly = (int(p["headcount"]) * Decimal(p["gross_monthly_salary"])
               * (1 + Decimal(p["employer_cost_percent"]) / HUNDRED))  # fmt: skip
    series = s.series("opex", "OPEX.PAYROLL")
    for m in s.window(p):
        series[m] = series.get(m, ZERO) + monthly


def _capex(s: _State, item: Item) -> None:
    p = item.params
    month, amount, life = _month(p["month"]), Decimal(p["amount"]), int(p["useful_life_months"])
    spent = s.series("capex").get(month, ZERO)
    life_series = s.series("capex_life")
    if not spent or life_series.get(month) == life:
        # The set's own capex of the month can hold it: an assumption set can, too.
        s.series("capex")[month] = spent + amount
        life_series[month] = Decimal(life)
    else:
        s.extra.append(ExtraCapex(month, amount, life))
        s.out.inexpressible.append(f"{item.label}: the month already has capex with another "
                                   "useful life")  # fmt: skip
    if p["funding"] == "LOAN":
        s.add_loan(item, LoanTerms(
            code=f"CAPEX-{item.seq}", structure=p["structure"],
            term_months=int(p["term_months"]), annual_rate=Decimal(p["annual_rate"]),
            amount=amount, drawdown_month=month,
        ), f"Loan for capex ({item.label})")  # fmt: skip


def _one_off(s: _State, item: Item) -> None:
    p = item.params
    month, amount = _month(p["month"]), Decimal(p["amount"])
    if p["treatment"] == "EXPENSE":
        series = s.series("opex", p["line"])
        series[month] = series.get(month, ZERO) + amount
        return
    line = p["liability"]
    settled = s.settlements.setdefault(month, {})
    settled[line] = settled.get(line, ZERO) + amount
    total = sum((v.get(line, ZERO) for v in s.settlements.values()), ZERO)
    held = s.inp.opening.get(line, ZERO)
    if total > held:
        raise s.fail(item, f"would settle {total:.2f} of {line}, more than its balance at the "
                           f"cut-over ({held:.2f}).")  # fmt: skip
    s.out.inexpressible.append(f"{item.label}: an assumption set cannot settle a liability")


def _rate_change(s: _State, item: Item) -> None:
    p = item.params
    target, points, start = p["target"], Decimal(p["points"]), _month(p["from_month"])
    later = [m for m in s.inp.months if m >= start]
    keys = {"ALL": ("interest_rate", "revolver_rate"), "OTHER_DEBT": ("interest_rate",),
            "FACILITY": ("revolver_rate",)}.get(target, ())  # fmt: skip
    for key in keys:
        series = s.series(key)
        for m in later:
            series[m] = series.get(m, ZERO) + points
        s.not_negative(item, series, key)
    if target not in ("ALL", "LOANS"):
        return
    named = set(p.get("loans", [])) if target == "LOANS" else {x.code for x in s.loans}
    for i, loan in enumerate(s.loans):
        if loan.code not in named:
            continue
        rate, path = loan.annual_rate, dict(loan.rate_path)
        for m in s.inp.months:
            rate = loan.rate_path.get(m, rate)
            if m >= start:
                if rate + points < 0:
                    raise s.fail(item, f"the rate of {loan.code} would be negative in {m:%m/%Y}.")
                path[m] = rate + points
        s.loans[i] = replace(loan, rate_path=path)
        s.series("loan_rate", loan.code).update(path)


CHANGES = {
    "PCT_CHANGE": _pct_change, "ABS_CHANGE": _abs_change, "TIMING_SHIFT": _timing_shift,
    "NEW_DEBT": _new_debt, "NEW_HIRE": _new_hire, "CAPEX": _capex, "ONE_OFF": _one_off,
    "RATE_CHANGE": _rate_change,
}  # fmt: skip


def apply(base: EngineInput, items: Sequence[Item]) -> Applied:
    """The base with ``items`` applied in order (an empty list returns the base unchanged)."""
    if not items:
        return Applied(base)
    s = _State(base)
    for item in sorted(items, key=lambda x: x.seq):
        CHANGES[item.type](s, item)
    s.out.inp = replace(base, drivers=s.drivers, loans=tuple(s.loans),
                        extra_capex=tuple(s.extra), settlements=s.settlements)  # fmt: skip
    s.out.drivers = s.drivers
    return s.out
