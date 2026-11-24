"""Tax capital allowances (M6F-3, #148; owner decision D3): pure functions, no database.

Kept apart from accounting depreciation: an asset's allowances follow the tax rules of its
allowance class, by **tax year**, and never change its depreciation, its book value or any
journal entry. They feed the taxable profit of projections (M6F-5).

Rules (stated on every schedule):
- Each tax year's allowance = cost x the class's annual rate in force at the start of that tax
  year, rounded to cents once, never more than the tax written-down value left.
- In the tax year the asset is first used, the class's first-year rule applies: ``FULL_YEAR`` (the
  whole annual allowance), ``MONTHS_IN_USE`` (months from the month of first use to the end of the
  tax year, over 12) or ``NONE`` (nothing that year).
- Allowances stop in the tax year of disposal (no allowance that year); balancing allowances and
  charges on disposal are not modelled and are shown as such.
- No rates are built in: classes and rates are entered with their source by the user or a tax
  professional, because none has been verified for the platform (owner decision #93).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fcp.core.money.rounding import RoundingMode, RoundingPolicy

CENTS = RoundingPolicy(2, RoundingMode.HALF_UP)
FULL_YEAR, MONTHS_IN_USE, NONE = "FULL_YEAR", "MONTHS_IN_USE", "NONE"
FIRST_YEAR_RULES = (FULL_YEAR, MONTHS_IN_USE, NONE)
RULES_NOTE = (
    "By tax year: cost x the annual rate in force at the start of the year, capped at the tax "
    "written-down value; first-year rule as set on the class; none in the year of disposal; "
    "balancing allowances and charges are not modelled."
)


@dataclass(frozen=True)
class AllowanceRate:
    effective_from: date  # the first tax year (its first day) the rate applies to
    annual_rate: Decimal  # 0.1 for 10% a year
    first_year: str = FULL_YEAR


@dataclass(frozen=True)
class AllowanceRow:
    tax_year: int  # the calendar year in which the tax year starts
    rate: Decimal
    allowance: Decimal
    written_down: Decimal  # tax written-down value at the end of the tax year


def _tax_year_of(day: date, start_month: int) -> int:
    return day.year if day.month >= start_month else day.year - 1


def _rate_for(rates: list[AllowanceRate], first_day: date) -> AllowanceRate | None:
    applicable = [r for r in rates if r.effective_from <= first_day]
    return max(applicable, key=lambda r: r.effective_from) if applicable else None


def allowance_schedule(cost: Decimal, first_used: date, rates: list[AllowanceRate], *,
                       disposed_on: date | None = None, start_month: int = 1,
                       until_year: int | None = None) -> list[AllowanceRow]:  # fmt: skip
    """Allowances by tax year from the year of first use until the cost is used up, the asset is
    disposed of, or ``until_year`` (inclusive)."""
    if cost < 0:
        raise ValueError("The cost cannot be negative.")
    for r in rates:
        if r.first_year not in FIRST_YEAR_RULES or not Decimal(0) <= r.annual_rate <= 1:
            raise ValueError("Each rate is between 0 and 100% with a known first-year rule.")
    year = _tax_year_of(first_used, start_month)
    stop = _tax_year_of(disposed_on, start_month) if disposed_on else None
    rows: list[AllowanceRow] = []
    left = cost
    while left > 0 and (until_year is None or year <= until_year):
        if stop is not None and year >= stop:
            break
        first_day = date(year, start_month, 1)
        rate = _rate_for(rates, first_day)
        if rate is None or rate.annual_rate == 0:
            if not any(r.effective_from > first_day for r in rates):
                break  # nothing more will ever be allowed
            rows.append(AllowanceRow(year, Decimal(0), Decimal("0.00"), left))
            year += 1
            continue
        share = Decimal(1)
        if year == _tax_year_of(first_used, start_month):
            if rate.first_year == NONE:
                share = Decimal(0)
            elif rate.first_year == MONTHS_IN_USE:
                months_used = (start_month - first_used.month - 1) % 12 + 1
                share = Decimal(months_used) / 12
        allowance = min(CENTS.apply(cost * rate.annual_rate * share), left)
        left -= allowance
        rows.append(AllowanceRow(year, rate.annual_rate, allowance, left))
        year += 1
    return rows
