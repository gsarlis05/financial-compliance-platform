"""calendar module: weeks, months, fiscal years, business days, buckets (M3-1, AC-M3-1)."""

import itertools
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fcp.modules.calendar.api import (
    Adjust,
    BusinessDays,
    FiscalCalendar,
    FiscalYear,
    add_months,
    allocate,
    days_between,
    fiscal_calendar,
    iso_week,
    month_end,
    month_start,
    monthly_buckets,
    quarter,
    week_end,
    week_label,
    week_start,
    weekly_buckets,
    weeks_in_iso_year,
)
from fcp.modules.calendar.dates import total
from fcp.modules.tenancy import services as tenancy

from ..ledger.conftest import books

__all__ = ["books"]

D = date
days = st.dates(min_value=D(1990, 1, 1), max_value=D(2100, 12, 31))


# --- weeks, months, quarters ----------------------------------------------------------------------


def test_iso_week_53_and_year_boundaries() -> None:
    assert weeks_in_iso_year(2026) == 53
    assert weeks_in_iso_year(2025) == 52
    assert weeks_in_iso_year(2020) == 53
    assert iso_week(D(2026, 12, 31)) == (2026, 53)
    assert iso_week(D(2027, 1, 3)) == (2026, 53)  # Sunday: still ISO 2026
    assert iso_week(D(2027, 1, 4)) == (2027, 1)
    assert iso_week(D(2024, 12, 30)) == (2025, 1)  # Monday: already ISO 2025
    assert week_label(D(2027, 1, 1)) == "2026-W53"
    assert week_label(D(2026, 1, 5)) == "2026-W02"


@given(days)
def test_weeks_run_monday_to_sunday(day: date) -> None:
    start, end = week_start(day), week_end(day)
    assert start.weekday() == 0
    assert end.weekday() == 6
    assert start <= day <= end
    assert days_between(start, end) == 6
    assert iso_week(start) == iso_week(day) == iso_week(end)


def test_months_quarters_and_leap_days() -> None:
    assert month_end(D(2028, 2, 10)) == D(2028, 2, 29)
    assert month_end(D(2026, 2, 10)) == D(2026, 2, 28)
    assert month_end(D(2026, 12, 5)) == D(2026, 12, 31)
    assert month_start(D(2026, 7, 19)) == D(2026, 7, 1)
    assert add_months(D(2026, 1, 31), 1) == D(2026, 2, 28)
    assert add_months(D(2028, 1, 31), 1) == D(2028, 2, 29)
    assert add_months(D(2028, 2, 29), 12) == D(2029, 2, 28)
    assert add_months(D(2026, 3, 31), -1) == D(2026, 2, 28)
    assert add_months(D(2026, 11, 15), 3) == D(2027, 2, 15)
    assert add_months(D(2026, 1, 15), -13) == D(2024, 12, 15)
    assert [quarter(D(2026, m, 1)) for m in (1, 3, 4, 6, 7, 9, 10, 12)] == [1, 1, 2, 2, 3, 3, 4, 4]
    assert days_between(D(2028, 2, 28), D(2028, 3, 1)) == 2


@given(days, st.integers(min_value=-600, max_value=600))
def test_add_months_moves_whole_months_and_clamps(day: date, months: int) -> None:
    moved = add_months(day, months)
    assert (moved.year * 12 + moved.month) - (day.year * 12 + day.month) == months
    assert moved.day == min(day.day, month_end(moved).day)


# --- fiscal years ---------------------------------------------------------------------------------


def july_calendar() -> FiscalCalendar:
    return FiscalCalendar((
        FiscalYear("FY2025/26", D(2025, 7, 1), D(2026, 6, 30)),
        FiscalYear("FY2026/27", D(2026, 7, 1), D(2027, 6, 30)),
    ))  # fmt: skip


def test_fiscal_year_starting_in_july() -> None:
    cal = july_calendar()
    assert cal.year_of(D(2026, 6, 30)).name == "FY2025/26"
    assert cal.year_of(D(2026, 7, 1)).name == "FY2026/27"
    assert cal.period_of(D(2025, 7, 1)) == 1
    assert cal.period_of(D(2026, 6, 30)) == 12
    assert cal.period_of(D(2027, 1, 15)) == 7
    assert cal.fiscal_quarter_of(D(2026, 9, 30)) == 1
    assert cal.fiscal_quarter_of(D(2027, 4, 1)) == 4


def test_days_outside_the_set_up_years_extend_by_whole_years() -> None:
    cal = july_calendar()
    later = cal.year_of(D(2028, 3, 1))
    assert (later.start, later.end) == (D(2027, 7, 1), D(2028, 6, 30))
    assert later.name.endswith("*")
    earlier = cal.year_of(D(2024, 7, 1))
    assert (earlier.start, earlier.end) == (D(2024, 7, 1), D(2025, 6, 30))
    assert cal.period_of(D(2028, 6, 30)) == 12
    with pytest.raises(ValueError, match="no fiscal years"):
        FiscalCalendar(()).year_of(D(2026, 1, 1))


@given(st.integers(min_value=1, max_value=12), days)
def test_any_start_month_gives_twelve_periods(start_month: int, day: date) -> None:
    start = D(2026, start_month, 1)
    cal = FiscalCalendar((FiscalYear("FY", start, add_months(start, 12) - timedelta(days=1)),))
    year = cal.year_of(day)
    assert year.contains(day)
    assert year.start.month == start_month
    assert year.start.day == 1
    assert add_months(year.start, 12) - timedelta(days=1) == year.end
    assert 1 <= cal.period_of(day) <= 12
    assert 1 <= cal.fiscal_quarter_of(day) <= 4


# --- business days --------------------------------------------------------------------------------

# Synthetic holidays (no real holiday calendar is built in: none are verified).
HOLIDAY = D(2026, 6, 1)  # a Monday
BD = BusinessDays(frozenset({HOLIDAY}))


def test_business_day_conventions() -> None:
    saturday = D(2026, 5, 30)
    assert not BD.is_business_day(saturday)
    assert not BD.is_business_day(HOLIDAY)
    assert BD.is_business_day(D(2026, 6, 2))
    assert BD.adjust(saturday, Adjust.NONE) == saturday
    assert BD.adjust(saturday, Adjust.FOLLOWING) == D(2026, 6, 2)  # skips Sunday and the holiday
    assert BD.adjust(saturday, Adjust.MODIFIED_FOLLOWING) == D(2026, 5, 29)  # stays in May
    assert BD.adjust(saturday, Adjust.PRECEDING) == D(2026, 5, 29)
    sunday_mid_month = D(2026, 5, 17)
    assert BD.adjust(sunday_mid_month, Adjust.MODIFIED_FOLLOWING) == D(2026, 5, 18)
    business = D(2026, 5, 20)
    assert all(BD.adjust(business, c) == business for c in Adjust)


def test_add_business_days() -> None:
    assert BD.add(D(2026, 5, 29), 1) == D(2026, 6, 2)
    assert BD.add(D(2026, 6, 2), -1) == D(2026, 5, 29)
    assert BD.add(D(2026, 5, 20), 0) == D(2026, 5, 20)
    assert BD.add(D(2026, 5, 18), 5) == D(2026, 5, 25)


@given(days, st.sampled_from(list(Adjust)))
def test_adjusted_days_are_business_days(day: date, convention: Adjust) -> None:
    adjusted = BD.adjust(day, convention)
    if convention is Adjust.NONE:
        assert adjusted == day
        return
    assert BD.is_business_day(adjusted)
    assert abs((adjusted - day).days) <= 4
    if convention is Adjust.MODIFIED_FOLLOWING:
        assert adjusted.month == day.month


# --- buckets and allocation -----------------------------------------------------------------------


def test_thirteen_weekly_buckets_from_a_wednesday() -> None:
    buckets = weekly_buckets(D(2026, 11, 4))
    assert len(buckets) == 13
    assert (buckets[0].start, buckets[0].end, buckets[0].label) == (
        D(2026, 11, 4), D(2026, 11, 8), "2026-W45")  # fmt: skip
    assert buckets[-1].end == D(2027, 1, 31)
    assert [b.label for b in buckets][-5:] == [
        "2026-W53", "2027-W01", "2027-W02", "2027-W03", "2027-W04"]  # fmt: skip
    assert [b.index for b in buckets] == list(range(1, 14))
    with pytest.raises(ValueError, match="at least 1"):
        weekly_buckets(D(2026, 11, 4), 0)


@given(days, st.integers(min_value=1, max_value=60))
def test_weekly_buckets_are_contiguous(as_of: date, weeks: int) -> None:
    buckets = weekly_buckets(as_of, weeks)
    assert buckets[0].start == as_of
    assert len(buckets) == weeks
    for previous, current in itertools.pairwise(buckets):
        assert current.start == previous.end + timedelta(days=1)
        assert current.start.weekday() == 0
        assert days_between(current.start, current.end) == 6
    assert all(b.end.weekday() == 6 for b in buckets)


def test_monthly_buckets() -> None:
    buckets = monthly_buckets(D(2026, 11, 15), 3)
    assert [(b.start, b.end, b.label) for b in buckets] == [
        (D(2026, 11, 15), D(2026, 11, 30), "2026-11"),
        (D(2026, 12, 1), D(2026, 12, 31), "2026-12"),
        (D(2027, 1, 1), D(2027, 1, 31), "2027-01"),
    ]
    with pytest.raises(ValueError, match="at least 1"):
        monthly_buckets(D(2026, 1, 1), 0)


def test_allocate_puts_each_flow_in_one_bucket() -> None:
    buckets = weekly_buckets(D(2026, 11, 4), 2)  # 4-8 Nov, 9-15 Nov
    flows = [(D(2026, 11, 3), Decimal("1")), (D(2026, 11, 4), Decimal("2")),
             (D(2026, 11, 8), Decimal("3")), (D(2026, 11, 9), Decimal("4")),
             (D(2026, 11, 16), Decimal("5"))]  # fmt: skip
    result = allocate(flows, buckets, lambda f: f[0])
    assert [a for _, a in result.before] == [Decimal("1")]
    assert [a for _, a in result.within[1]] == [Decimal("2"), Decimal("3")]
    assert [a for _, a in result.within[2]] == [Decimal("4")]
    assert [a for _, a in result.after] == [Decimal("5")]
    with pytest.raises(ValueError, match="no buckets"):
        allocate(flows, [], lambda f: f[0])


amounts = st.decimals(min_value=-(10**9), max_value=10**9, places=2, allow_nan=False)


@given(days, st.integers(min_value=1, max_value=20),
       st.lists(st.tuples(days, amounts), max_size=60))  # fmt: skip
def test_allocation_never_loses_or_splits_flows(
    as_of: date, weeks: int, flows: list[tuple[date, Decimal]]
) -> None:
    buckets = weekly_buckets(as_of, weeks)
    result = allocate(flows, buckets, lambda f: f[0])
    placed = [f for b in buckets for f in result.within[b.index]] + result.before + result.after
    assert sorted(placed) == sorted(flows)  # each flow exactly once, unchanged (never pro-rated)
    inside = total(a for d, a in flows if buckets[0].start <= d <= buckets[-1].end)
    assert total(a for b in buckets for _, a in result.within[b.index]) == inside
    for bucket in buckets:
        assert all(bucket.contains(d) for d, _ in result.within[bucket.index])


# --- loading an entity's fiscal years -------------------------------------------------------------


@pytest.mark.django_db
def test_fiscal_calendar_loads_the_entity_years(books: dict[str, Any]) -> None:
    ctx = tenancy.enter_workspace(books["owner"], books["ws"]["slug"])
    cal = fiscal_calendar(ctx, UUID(books["entity"]["id"]))
    assert [(y.start, y.end) for y in cal.years] == [(D(2026, 1, 1), D(2026, 12, 31))]
    assert cal.period_of(D(2026, 11, 4)) == 11
    assert cal.year_of(D(2027, 3, 1)).start == D(2027, 1, 1)
