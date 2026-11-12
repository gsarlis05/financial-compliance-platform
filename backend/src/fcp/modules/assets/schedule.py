"""Depreciation schedules (M6-1): pure functions, no database.

Conventions (stated on every schedule):
- Depreciation is monthly. It starts in the month **after** acquisition and stops before the month
  of disposal.
- Each month is rounded to cents (half up) once. The last month of the useful life takes the
  remainder, so the months always add up to cost - residual value exactly, with no rounding plug.
- **Straight-line:** (cost - residual) / useful life in months.
- **Declining balance:** net book value x annual rate / 12, never taking the book value below the
  residual value; the last month of the useful life depreciates whatever is left down to the
  residual value.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from fcp.core.money.rounding import RoundingMode, RoundingPolicy
from fcp.modules.calendar.api import add_months, month_start

CENTS = RoundingPolicy(2, RoundingMode.HALF_UP)
STRAIGHT_LINE, DECLINING_BALANCE = "STRAIGHT_LINE", "DECLINING_BALANCE"
CONVENTION = (
    "Monthly; starts the month after acquisition and stops before the month of disposal; "
    "each month rounded to cents, the last month takes the remainder."
)


@dataclass(frozen=True)
class AssetTerms:
    acquired_on: date
    cost: Decimal
    residual: Decimal
    life_months: int
    method: str = STRAIGHT_LINE
    annual_rate: Decimal | None = None  # declining balance, e.g. Decimal("0.25")
    disposed_on: date | None = None


@dataclass(frozen=True)
class ScheduleRow:
    month: date  # first day of the month
    opening: Decimal  # net book value at the start of the month
    depreciation: Decimal
    closing: Decimal
    accumulated: Decimal


def first_month(terms: AssetTerms) -> date:
    return add_months(month_start(terms.acquired_on), 1)


def schedule(terms: AssetTerms) -> list[ScheduleRow]:
    """The full schedule over the useful life, cut at disposal (see the module text)."""
    if terms.life_months < 1:
        raise ValueError("The useful life must be at least one month.")
    if terms.cost < 0 or terms.residual < 0 or terms.residual > terms.cost:
        raise ValueError("Cost and residual value must be positive, residual not above cost.")
    if terms.method == DECLINING_BALANCE and not (terms.annual_rate and terms.annual_rate > 0):
        raise ValueError("Declining balance needs an annual rate above 0.")
    depreciable = terms.cost - terms.residual
    even = CENTS.apply(depreciable / terms.life_months)
    start = first_month(terms)
    stop = month_start(terms.disposed_on) if terms.disposed_on else None
    rows: list[ScheduleRow] = []
    book, accumulated = terms.cost, Decimal("0.00")
    for n in range(terms.life_months):
        month = add_months(start, n)
        if stop is not None and month >= stop:
            break
        last = n == terms.life_months - 1
        if last:
            amount = book - terms.residual
        elif terms.method == STRAIGHT_LINE:
            amount = even
        else:
            rate = terms.annual_rate or Decimal(0)
            amount = CENTS.apply(book * rate / 12)
        amount = max(Decimal("0.00"), min(amount, book - terms.residual))
        accumulated += amount
        rows.append(ScheduleRow(month, book, amount, book - amount, accumulated))
        book -= amount
    return rows


def depreciation_for(terms: AssetTerms, month: date) -> Decimal:
    """Depreciation in one month (0 outside the schedule)."""
    target = month_start(month)
    return next((r.depreciation for r in schedule(terms) if r.month == target), Decimal("0.00"))


def book_value(terms: AssetTerms, at: date) -> Decimal:
    """Net book value at the end of the month containing ``at``."""
    target = month_start(at)
    value = terms.cost if month_start(terms.acquired_on) <= target else Decimal("0.00")
    for row in schedule(terms):
        if row.month > target:
            break
        value = row.closing
    return value


@dataclass(frozen=True)
class Disposal:
    book_value: Decimal
    proceeds: Decimal
    gain: Decimal  # negative: a loss


def disposal_result(terms: AssetTerms, proceeds: Decimal) -> Disposal:
    """Gain or loss on disposal: proceeds - book value at the end of the month before."""
    if terms.disposed_on is None:
        raise ValueError("The asset is not disposed of.")
    before = add_months(month_start(terms.disposed_on), -1)
    value = book_value(terms, before) if before >= month_start(terms.acquired_on) else terms.cost
    return Disposal(value, proceeds, proceeds - value)
