"""Date arithmetic for planning (M3-1). Pure functions: no clock reads, no floats, dates only.

- ISO weeks (Monday to Sunday, including week 53 years) and labels such as ``2026-W45``.
- Months, quarters and fiscal years starting in any month.
- Business days: Monday to Friday plus a holiday list supplied as data (no built-in holidays: none
  are verified), with FOLLOWING, MODIFIED FOLLOWING and PRECEDING adjustment.
- Buckets: contiguous date ranges. Dated flows are allocated to the bucket containing their date,
  never pro-rated; the sum over the buckets equals the sum of the flows inside the horizon.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import TypeVar

ONE_DAY = timedelta(days=1)
T = TypeVar("T")


# --- weeks, months, quarters ----------------------------------------------------------------------


def iso_week(day: date) -> tuple[int, int]:
    """ISO year and week number (the ISO year differs from the calendar year around 1 January)."""
    year, week, _ = day.isocalendar()
    return year, week


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_end(day: date) -> date:
    return week_start(day) + timedelta(days=6)


def week_label(day: date) -> str:
    year, week = iso_week(day)
    return f"{year}-W{week:02d}"


def weeks_in_iso_year(year: int) -> int:
    """52 or 53: 28 December always falls in the last ISO week of its year."""
    return date(year, 12, 28).isocalendar()[1]


def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return following - ONE_DAY


def add_months(day: date, months: int) -> date:
    """The same day ``months`` later, clamped to the month's last day (31 Jan + 1 = 28/29 Feb)."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    last = month_end(date(year, month + 1, 1))
    return last.replace(day=min(day.day, last.day))


def quarter(day: date) -> int:
    return (day.month - 1) // 3 + 1


def days_between(start: date, end: date) -> int:
    """Calendar days from start (inclusive) to end (exclusive)."""
    return (end - start).days


# --- fiscal years ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class FiscalYear:
    name: str
    start: date
    end: date

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


@dataclass(frozen=True)
class FiscalCalendar:
    """The fiscal years of an entity, in order. Days outside them extend the nearest year by whole
    years (a forecast may run past the last year set up)."""

    years: tuple[FiscalYear, ...]

    def year_of(self, day: date) -> FiscalYear:
        if not self.years:
            raise ValueError("no fiscal years")
        for year in self.years:
            if year.contains(day):
                return year
        anchor = self.years[0] if day < self.years[0].start else self.years[-1]
        start = anchor.start
        while start > day:
            start = add_months(start, -12)
        while add_months(start, 12) <= day:
            start = add_months(start, 12)
        return FiscalYear(f"FY{start.year}*", start, add_months(start, 12) - ONE_DAY)

    def period_of(self, day: date) -> int:
        """1-based monthly period of the fiscal year containing ``day``."""
        start = self.year_of(day).start
        return (day.year - start.year) * 12 + day.month - start.month + 1

    def fiscal_quarter_of(self, day: date) -> int:
        return (self.period_of(day) - 1) // 3 + 1


# --- business days --------------------------------------------------------------------------------


class Adjust(StrEnum):
    NONE = "NONE"
    FOLLOWING = "FOLLOWING"
    MODIFIED_FOLLOWING = "MODIFIED_FOLLOWING"  # following, unless that crosses into the next month
    PRECEDING = "PRECEDING"


@dataclass(frozen=True)
class BusinessDays:
    holidays: frozenset[date] = frozenset()

    def is_business_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def next(self, day: date) -> date:
        while not self.is_business_day(day):
            day += ONE_DAY
        return day

    def previous(self, day: date) -> date:
        while not self.is_business_day(day):
            day -= ONE_DAY
        return day

    def adjust(self, day: date, convention: Adjust) -> date:
        if convention is Adjust.NONE or self.is_business_day(day):
            return day
        if convention is Adjust.PRECEDING:
            return self.previous(day)
        following = self.next(day)
        if convention is Adjust.MODIFIED_FOLLOWING and following.month != day.month:
            return self.previous(day)
        return following

    def add(self, day: date, count: int) -> date:
        """``count`` business days after (or, negative, before) ``day``."""
        step = ONE_DAY if count >= 0 else -ONE_DAY
        remaining = abs(count)
        while remaining:
            day += step
            if self.is_business_day(day):
                remaining -= 1
        return day


# --- buckets --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Bucket:
    index: int
    start: date
    end: date
    label: str

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def weekly_buckets(as_of: date, weeks: int = 13) -> list[Bucket]:
    """``weeks`` contiguous buckets: the first runs from ``as_of`` to the end of its ISO week, the
    others are whole ISO weeks (doc 16 §3)."""
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    buckets = []
    start = as_of
    for index in range(weeks):
        end = week_end(start)
        buckets.append(Bucket(index + 1, start, end, week_label(start)))
        start = end + ONE_DAY
    return buckets


def monthly_buckets(first: date, months: int) -> list[Bucket]:
    if months < 1:
        raise ValueError("months must be at least 1")
    buckets = []
    start = first
    for index in range(months):
        end = month_end(start)
        buckets.append(Bucket(index + 1, start, end, f"{start:%Y-%m}"))
        start = end + ONE_DAY
    return buckets


@dataclass(frozen=True)
class Allocation[T]:
    """Flows per bucket, plus those before the first bucket (overdue) and after the last."""

    buckets: list[Bucket]
    within: dict[int, list[T]]
    before: list[T]
    after: list[T]


def allocate[T](items: Iterable[T], buckets: Sequence[Bucket],
                date_of: Callable[[T], date]) -> Allocation[T]:  # fmt: skip
    """Put each dated item in the bucket containing its date: never split, never pro-rated."""
    if not buckets:
        raise ValueError("no buckets")
    within: dict[int, list[T]] = {b.index: [] for b in buckets}
    before: list[T] = []
    after: list[T] = []
    first, last = buckets[0].start, buckets[-1].end
    for item in items:
        day = date_of(item)
        if day < first:
            before.append(item)
        elif day > last:
            after.append(item)
        else:
            within[next(b.index for b in buckets if b.contains(day))].append(item)
    return Allocation(list(buckets), within, before, after)


def total(amounts: Iterable[Decimal]) -> Decimal:
    return sum(amounts, Decimal(0))
