"""The eight typed overrides of a scenario (M7-1, doc 10 §8, brief 21 §3).

Each override is a typed object with validated parameters; there is no free-form formula or
code. ``clean`` checks the parameters against the scenario's base (its horizon and loans) and
returns them normalised: amounts and percentages as decimal strings, months as the first day of
the month (``2027-03-01``). A problem is reported against its parameter, in plain words.

Types and their parameters:
- ``PCT_CHANGE``: revenue or cost lines up or down by a %. ``driver`` (revenue or opex),
  ``lines`` (none: all of them), ``percent``, ``start_month``, ``end_month``.
- ``ABS_CHANGE``: one revenue or cost line up or down by an amount a month. ``driver``,
  ``line``, ``amount``, ``start_month``, ``end_month``.
- ``TIMING_SHIFT``: customers pay, stock turns or suppliers are paid later or earlier (``mode``
  DAYS: ``driver`` dso, dio or dpo, and ``days``), or a line moves by whole months (``mode``
  MONTHS: ``driver``, ``line``, ``months``); both with ``start_month`` and ``end_month``.
- ``NEW_DEBT``: a new loan. ``code``, ``name``, ``amount``, ``drawdown_month``, ``term_months``,
  ``annual_rate``, ``structure``, ``interest_only_months``.
- ``NEW_HIRE``: people joining. ``role``, ``department``, ``headcount``,
  ``gross_monthly_salary``, ``employer_cost_percent``, ``employer_cost_source``,
  ``start_month``, ``end_month``.
- ``CAPEX``: an investment. ``amount``, ``month``, ``useful_life_months``, ``funding`` (CASH, or
  LOAN with ``term_months``, ``annual_rate`` and ``structure``).
- ``ONE_OFF``: a one-off payment. ``amount``, ``month``, ``treatment``: EXPENSE (on an opex
  ``line``) or LIABILITY_SETTLEMENT (of a ``liability``: trade, other or tax payables).
- ``RATE_CHANGE``: interest rates up or down. ``target`` (ALL, FACILITY, OTHER_DEBT, or LOANS
  with ``loans``), ``points`` (percentage points), ``from_month``.

The employer cost % of a new hire is entered by the user with its source: the platform holds no
social-insurance rate (doc 10 §8 asks for a verified parameter; brief 21 §7 item 2).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fcp.core.errors import ValidationFailedError

TYPES = (
    "PCT_CHANGE", "ABS_CHANGE", "TIMING_SHIFT", "NEW_DEBT",
    "NEW_HIRE", "CAPEX", "ONE_OFF", "RATE_CHANGE",
)  # fmt: skip
MAX_OVERRIDES = 50
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1e12")
STRUCTURES = ("ANNUITY", "EQUAL_PRINCIPAL", "BULLET")
LIABILITIES = ("BS.AP", "BS.OTHER_PAY", "BS.TAX_PAY")
CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")
MONTH = re.compile(r"^\d{4}-\d{2}(-01)?$")


@dataclass(frozen=True)
class Base:
    """What an override is checked against: the base set's horizon, loans and lines."""

    months: list[date]
    loan_codes: frozenset[str]
    revenue_lines: tuple[str, ...]
    opex_lines: tuple[str, ...]

    def lines(self, driver: str) -> tuple[str, ...]:
        return self.revenue_lines if driver == "revenue" else self.opex_lines


class _Params:
    """Reads one override's parameters; every problem names its parameter."""

    def __init__(self, raw: dict[str, Any], base: Base) -> None:
        self.raw, self.base = raw, base
        self.out: dict[str, Any] = {}

    def fail(self, name: str, message: str) -> ValidationFailedError:
        return ValidationFailedError(message, field_errors={f"params.{name}": [message]})

    def text(self, name: str, *, required: bool = True, max_length: int = 120) -> str:
        value = self.raw.get(name, "")
        if not isinstance(value, str):
            raise self.fail(name, f"{name}: enter text.")
        value = value.strip()
        if required and not value:
            raise self.fail(name, f"{name}: this is required.")
        if len(value) > max_length:
            raise self.fail(name, f"{name}: at most {max_length} characters.")
        self.out[name] = value
        return value

    def choice(self, name: str, options: tuple[str, ...], default: str | None = None) -> str:
        value = self.raw.get(name, default)
        if value not in options:
            raise self.fail(name, f"{name}: choose one of {', '.join(options)}.")
        self.out[name] = str(value)
        return str(value)

    def number(self, name: str, low: Decimal, high: Decimal, *, places: int = 4,
               nonzero: bool = False, default: str | None = None) -> Decimal:  # fmt: skip
        raw = self.raw.get(name, default)
        try:
            value = Decimal(str(raw)) if isinstance(raw, (str, int)) else Decimal("NaN")
        except InvalidOperation:
            value = Decimal("NaN")
        unit = Decimal(1).scaleb(-places)
        if not value.is_finite() or value != value.quantize(unit) or not low <= value <= high:
            raise self.fail(name, f"{name}: enter a number from {low} to {high}, "
                                  f"with at most {places} decimals.")  # fmt: skip
        if nonzero and not value:
            raise self.fail(name, f"{name}: must not be 0.")
        self.out[name] = f"{value.normalize():f}" if places != 2 else f"{value:.2f}"
        return value

    def amount(self, name: str, *, signed: bool = False, nonzero: bool = True) -> Decimal:
        low = -MAX_AMOUNT if signed else (CENT if nonzero else Decimal(0))
        return self.number(name, low, MAX_AMOUNT, places=2, nonzero=nonzero)

    def integer(self, name: str, low: int, high: int, *, nonzero: bool = False,
                default: int | None = None) -> int:  # fmt: skip
        value = self.raw.get(name, default)
        if isinstance(value, str) and re.fullmatch(r"-?\d{1,5}", value):
            value = int(value)
        if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
            raise self.fail(name, f"{name}: enter a whole number from {low} to {high}.")
        if nonzero and not value:
            raise self.fail(name, f"{name}: must not be 0.")
        self.out[name] = value
        return value

    def month(self, name: str, default: str | None = None) -> date:
        raw = self.raw.get(name, default)
        if not isinstance(raw, str) or not MONTH.match(raw):
            raise self.fail(name, f"{name}: enter a month such as 2027-03.")
        try:
            value = date(int(raw[:4]), int(raw[5:7]), 1)
        except ValueError:
            raise self.fail(name, f"{name}: enter a month such as 2027-03.") from None
        months = self.base.months
        if value not in months:
            raise self.fail(name, f"{name}: {value:%m/%Y} is outside the base's horizon "
                                  f"({months[0]:%m/%Y} to {months[-1]:%m/%Y}).")  # fmt: skip
        self.out[name] = value.isoformat()
        return value

    def period(self) -> None:
        """``start_month`` (default: the first month) to ``end_month`` (default: the last)."""
        first, last = self.base.months[0], self.base.months[-1]
        start = self.month("start_month", self.raw.get("start_month") or first.isoformat())
        end = self.month("end_month", self.raw.get("end_month") or last.isoformat())
        if end < start:
            raise self.fail("end_month", "end_month: must not be before start_month.")

    def line_of(self, name: str, driver: str) -> str:
        options = self.base.lines(driver)
        return self.choice(name, options)

    def loan(self, prefix: str = "") -> None:
        """A loan's terms (a new loan, or capex funded by a loan)."""
        self.integer(f"{prefix}term_months", 1, 600)
        self.number(f"{prefix}annual_rate", Decimal(0), Decimal(100), places=4)
        self.choice(f"{prefix}structure", STRUCTURES, default="ANNUITY")


def _pct_change(p: _Params) -> None:
    driver = p.choice("driver", ("revenue", "opex"))
    lines = p.raw.get("lines", [])
    allowed = p.base.lines(driver)
    duplicated = isinstance(lines, list) and len(set(lines)) != len(lines)
    if not isinstance(lines, list) or duplicated or any(x not in allowed for x in lines):
        raise p.fail("lines", f"lines: choose from {', '.join(allowed)} (none for all of them).")
    p.out["lines"] = [x for x in allowed if x in lines]
    p.number("percent", Decimal(-100), Decimal(1000), places=4, nonzero=True)
    p.period()


def _abs_change(p: _Params) -> None:
    driver = p.choice("driver", ("revenue", "opex"))
    p.line_of("line", driver)
    p.amount("amount", signed=True)
    p.period()


def _timing_shift(p: _Params) -> None:
    mode = p.choice("mode", ("DAYS", "MONTHS"), default="DAYS")
    if mode == "DAYS":
        p.choice("driver", ("dso", "dio", "dpo"))
        p.integer("days", -365, 365, nonzero=True)
    else:
        driver = p.choice("driver", ("revenue", "opex"))
        p.line_of("line", driver)
        p.integer("months", -12, 12, nonzero=True)
    p.period()


def _new_debt(p: _Params) -> None:
    code = p.text("code", max_length=20).upper()
    if not CODE.match(code):
        raise p.fail("code", "code: letters, digits, - and _, up to 20 characters.")
    if code in p.base.loan_codes:
        raise p.fail("code", f"code: the base already has a loan {code}.")
    p.out["code"] = code
    p.text("name", required=False)
    p.amount("amount")
    p.month("drawdown_month")
    p.loan()
    p.integer("interest_only_months", 0, 120, default=0)
    if p.out["interest_only_months"] >= p.out["term_months"]:
        raise p.fail(
            "interest_only_months", "interest_only_months: must be fewer than the term's months."
        )


def _new_hire(p: _Params) -> None:
    p.text("role")
    p.text("department", required=False)
    p.integer("headcount", 1, 1000, default=1)
    p.amount("gross_monthly_salary")
    percent = p.number("employer_cost_percent", Decimal(0), Decimal(100), places=4, default="0")
    source = p.text("employer_cost_source", required=False, max_length=300)
    if percent and not source:
        raise p.fail(
            "employer_cost_source",
            "employer_cost_source: say where the employer cost % comes from "
            "(it is entered by you; the platform holds no social-insurance rate).",
        )
    p.period()


def _capex(p: _Params) -> None:
    p.amount("amount")
    p.month("month")
    p.integer("useful_life_months", 1, 1200)
    if p.choice("funding", ("CASH", "LOAN"), default="CASH") == "LOAN":
        p.loan()


def _one_off(p: _Params) -> None:
    p.amount("amount")
    p.month("month")
    if p.choice("treatment", ("EXPENSE", "LIABILITY_SETTLEMENT")) == "EXPENSE":
        p.choice("line", p.base.opex_lines, default="OPEX.OTHER")
    else:
        p.choice("liability", LIABILITIES)


def _rate_change(p: _Params) -> None:
    target = p.choice("target", ("ALL", "FACILITY", "OTHER_DEBT", "LOANS"))
    if target == "LOANS":
        loans = p.raw.get("loans", [])
        known = sorted(p.base.loan_codes)
        if not isinstance(loans, list) or not loans or any(x not in known for x in loans):
            raise p.fail("loans", "loans: choose one or more of the base's loans: "
                                  f"{', '.join(known) or 'it has none'}.")  # fmt: skip
        p.out["loans"] = sorted(set(loans))
    p.number("points", Decimal(-20), Decimal(20), places=4, nonzero=True)
    p.month("from_month", p.raw.get("from_month") or p.base.months[0].isoformat())


CHECKS: dict[str, Callable[[_Params], None]] = {
    "PCT_CHANGE": _pct_change, "ABS_CHANGE": _abs_change, "TIMING_SHIFT": _timing_shift,
    "NEW_DEBT": _new_debt, "NEW_HIRE": _new_hire, "CAPEX": _capex, "ONE_OFF": _one_off,
    "RATE_CHANGE": _rate_change,
}  # fmt: skip


def clean(kind: str, raw: object, base: Base) -> dict[str, Any]:
    """Validate an override's parameters against the base; return them normalised."""
    if kind not in CHECKS:
        message = f"type: choose one of {', '.join(TYPES)}."
        raise ValidationFailedError(message, field_errors={"type": [message]})
    if not isinstance(raw, dict):
        raise ValidationFailedError("params: expected an object.",
                                    field_errors={"params": ["Expected an object."]})  # fmt: skip
    p = _Params(raw, base)
    CHECKS[kind](p)
    unknown = sorted(set(raw) - set(p.out) - {"start_month", "end_month", "from_month"})
    if unknown:
        raise p.fail(unknown[0], f"{unknown[0]}: not a parameter of {kind}.")
    return p.out
