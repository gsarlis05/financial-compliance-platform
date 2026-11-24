"""Payment schedules: day counts, recurrences, loans against reference tables (M3-4, AC-CW8).

Reference values were computed separately with exact fractions (not with this code), and the
30-year annuity matches the widely published payment of 1,264.14 for 200,000 at 6.5%.
"""

import itertools
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fcp.modules.calendar.api import Adjust, BusinessDays
from fcp.modules.registers.schedules import (
    DayCount,
    Frequency,
    Loan,
    Recurrence,
    Repayment,
    ScheduleError,
    day_count,
    interest,
    level_payment,
    loan_schedule,
    occurrences,
)

D = Decimal


@pytest.mark.parametrize(
    ("start", "end", "convention", "expected"),
    [
        (date(2026, 1, 15), date(2026, 4, 15), DayCount.ACT_360, (90, 360)),
        (date(2026, 1, 15), date(2026, 4, 15), DayCount.ACT_365, (90, 365)),
        (date(2026, 1, 15), date(2026, 4, 15), DayCount.THIRTY_360, (90, 360)),
        (date(2026, 1, 31), date(2026, 2, 28), DayCount.THIRTY_360, (28, 360)),
        (date(2026, 1, 31), date(2026, 3, 31), DayCount.THIRTY_360, (60, 360)),
        (date(2026, 1, 30), date(2026, 3, 31), DayCount.THIRTY_360, (60, 360)),
        (date(2026, 1, 29), date(2026, 3, 31), DayCount.THIRTY_360, (62, 360)),
        (date(2028, 2, 1), date(2028, 3, 1), DayCount.ACT_365, (29, 365)),  # leap year
        (date(2026, 3, 31), date(2026, 9, 30), DayCount.THIRTY_360, (180, 360)),
        (date(2025, 12, 15), date(2026, 12, 15), DayCount.THIRTY_360, (360, 360)),
    ],
)
def test_day_counts(
    start: date, end: date, convention: DayCount, expected: tuple[int, int]
) -> None:
    assert day_count(start, end, convention) == expected


def test_interest_rounds_half_up_once() -> None:
    assert interest(
        D("6000"), D("0.05"), date(2026, 7, 15), date(2026, 10, 15), DayCount.ACT_360
    ) == D("76.67")  # 76.666...
    assert interest(
        D("1000"), D("0.0365"), date(2026, 1, 1), date(2026, 1, 2), DayCount.ACT_365
    ) == D("0.10")


# --- loans against reference tables ---------------------------------------------------------------

SMALL_ANNUITY = [  # 1,200 at 12%, 12 monthly payments, 30/360
    (D("1200.00"), D("12.00"), D("94.62"), D("1105.38")),
    (D("1105.38"), D("11.05"), D("95.57"), D("1009.81")),
    (D("1009.81"), D("10.10"), D("96.52"), D("913.29")),
    (D("913.29"), D("9.13"), D("97.49"), D("815.80")),
    (D("815.80"), D("8.16"), D("98.46"), D("717.34")),
    (D("717.34"), D("7.17"), D("99.45"), D("617.89")),
    (D("617.89"), D("6.18"), D("100.44"), D("517.45")),
    (D("517.45"), D("5.17"), D("101.45"), D("416.00")),
    (D("416.00"), D("4.16"), D("102.46"), D("313.54")),
    (D("313.54"), D("3.14"), D("103.48"), D("210.06")),
    (D("210.06"), D("2.10"), D("104.52"), D("105.54")),
    (D("105.54"), D("1.06"), D("105.54"), D("0.00")),
]


def test_annuity_matches_the_reference_table() -> None:
    loan = Loan(D("1200.00"), date(2026, 1, 15), date(2027, 1, 15), D("0.12"), adjust=Adjust.NONE)
    rows = loan_schedule(loan)
    assert [(r.opening, r.interest, r.principal, r.closing) for r in rows] == SMALL_ANNUITY
    assert {r.payment for r in rows[:-1]} == {D("106.62")}
    assert rows[-1].payment == D("106.60")
    assert [r.number for r in rows] == list(range(1, 13))
    assert rows[0].period_start == date(2026, 1, 15)
    assert rows[0].period_end == date(2026, 2, 15)


def test_thirty_year_annuity() -> None:
    loan = Loan(
        D("200000.00"), date(2026, 1, 15), date(2056, 1, 15), D("0.065"), adjust=Adjust.NONE
    )
    rows = loan_schedule(loan)
    assert len(rows) == 360
    assert (rows[0].payment, rows[0].interest, rows[0].principal) == (
        D("1264.14"),
        D("1083.33"),
        D("180.81"),
    )
    assert (rows[-1].opening, rows[-1].interest, rows[-1].payment) == (
        D("1252.77"),
        D("6.79"),
        D("1259.56"),
    )
    assert sum(r.interest for r in rows) == D("255085.82")
    assert sum(r.principal for r in rows) == D("200000.00")


def test_linear_quarterly_act_360_and_act_365() -> None:
    terms = {
        "principal": D("12000.00"),
        "start": date(2026, 1, 15),
        "maturity": date(2027, 1, 15),
        "annual_rate": D("0.05"),
        "frequency_months": 3,
        "repayment": Repayment.LINEAR,
        "adjust": Adjust.NONE,
    }
    act360 = loan_schedule(Loan(**terms, day_count=DayCount.ACT_360))  # type: ignore[arg-type]
    act365 = loan_schedule(Loan(**terms, day_count=DayCount.ACT_365))  # type: ignore[arg-type]
    assert [r.interest for r in act360] == [D("150.00"), D("113.75"), D("76.67"), D("38.33")]
    assert [r.interest for r in act365] == [D("147.95"), D("112.19"), D("75.62"), D("37.81")]
    assert {r.principal for r in act360} == {D("3000.00")}
    assert [r.closing for r in act360] == [D("9000.00"), D("6000.00"), D("3000.00"), D("0.00")]


def test_bullet_semiannual_thirty_360() -> None:
    rows = loan_schedule(
        Loan(
            D("10000.00"),
            date(2026, 3, 31),
            date(2028, 3, 31),
            D("0.04"),
            frequency_months=6,
            repayment=Repayment.BULLET,
            adjust=Adjust.NONE,
        )
    )
    assert [r.period_end for r in rows] == [
        date(2026, 9, 30),
        date(2027, 3, 31),
        date(2027, 9, 30),
        date(2028, 3, 31),
    ]
    assert {r.interest for r in rows} == {D("200.00")}
    assert [r.principal for r in rows] == [D(0), D(0), D(0), D("10000.00")]
    assert rows[-1].payment == D("10200.00")


def test_interest_only_then_annuity() -> None:
    rows = loan_schedule(
        Loan(
            D("1200.00"),
            date(2025, 10, 15),
            date(2027, 1, 15),
            D("0.12"),
            repayment=Repayment.IO_THEN_ANNUITY,
            interest_only_periods=3,
            adjust=Adjust.NONE,
        )
    )
    assert len(rows) == 15
    assert [(r.interest, r.principal) for r in rows[:3]] == [(D("12.00"), D(0))] * 3
    after = [(r.opening, r.interest, r.principal, r.closing) for r in rows[3:]]
    assert after == SMALL_ANNUITY


def test_zero_rate_and_payment_dates_on_business_days() -> None:
    rows = loan_schedule(
        Loan(D("100.00"), date(2026, 1, 31), date(2026, 4, 30), D("0"), repayment=Repayment.ANNUITY)
    )
    assert [r.principal for r in rows] == [D("33.33"), D("33.33"), D("33.34")]
    assert {r.interest for r in rows} == {D(0)}
    # 28 Feb 2026 is a Saturday: modified following would cross into March, so Friday 27 Feb.
    assert [r.due for r in rows] == [date(2026, 2, 27), date(2026, 3, 31), date(2026, 4, 30)]
    assert rows[0].period_end == date(2026, 2, 28)
    assert level_payment(D("100"), D(0), 3) == D("33.33")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"maturity": date(2026, 2, 20)}, "whole number of payment periods"),
        ({"maturity": date(2026, 1, 15)}, "whole number of payment periods"),
        ({"frequency_months": 2}, "monthly, quarterly"),
        ({"principal": D("-1")}, "positive amount in cents"),
        ({"principal": D("1.005")}, "positive amount in cents"),
        ({"annual_rate": D("5")}, "fraction from 0 to 1"),
        ({"annual_rate": D("-0.01")}, "fraction from 0 to 1"),
        ({"interest_only_periods": 2}, "IO_THEN_ANNUITY only"),
        ({"repayment": Repayment.IO_THEN_ANNUITY}, "at least 1 and fewer"),
        (
            {"repayment": Repayment.IO_THEN_ANNUITY, "interest_only_periods": 12},
            "at least 1 and fewer",
        ),
        ({"maturity": date(2077, 1, 15)}, "At most 600"),
    ],
)
def test_invalid_loans(changes: dict[str, object], message: str) -> None:
    terms: dict[str, object] = {
        "principal": D("1200.00"),
        "start": date(2026, 1, 15),
        "maturity": date(2027, 1, 15),
        "annual_rate": D("0.12"),
    }
    with pytest.raises(ScheduleError, match=message):
        loan_schedule(Loan(**{**terms, **changes}))  # type: ignore[arg-type]


@given(
    principal=st.decimals(min_value=1, max_value=10_000_000, places=2),
    rate=st.decimals(min_value=0, max_value=Decimal("0.25"), places=4),
    years=st.integers(min_value=1, max_value=10),
    frequency=st.sampled_from([1, 3, 6, 12]),
    repayment=st.sampled_from(list(Repayment)),
    convention=st.sampled_from(list(DayCount)),
    start=st.dates(min_value=date(2020, 1, 1), max_value=date(2035, 12, 31)),
)
def test_schedules_always_repay_exactly(
    *,
    principal: Decimal,
    rate: Decimal,
    years: int,
    frequency: int,
    repayment: Repayment,
    convention: DayCount,
    start: date,
) -> None:
    from fcp.modules.calendar.api import add_months  # noqa: PLC0415

    n = years * 12 // frequency
    io = 1 if repayment is Repayment.IO_THEN_ANNUITY and n > 1 else 0
    if repayment is Repayment.IO_THEN_ANNUITY and n == 1:
        repayment = Repayment.ANNUITY
    loan = Loan(
        principal, start, add_months(start, years * 12), rate, frequency, repayment, convention, io
    )
    rows = loan_schedule(loan, BusinessDays())
    assert len(rows) == n
    assert sum(r.principal for r in rows) == principal
    assert rows[-1].closing == 0
    for previous, row in itertools.pairwise(rows):
        assert row.opening == previous.closing
        assert row.period_start == previous.period_end
    for row in rows:
        assert row.payment == row.principal + row.interest
        assert row.principal >= 0
        assert row.interest >= 0
        assert row.due.weekday() < 5


# --- recurring obligations ------------------------------------------------------------------------


def test_monthly_on_a_day_clamped_to_month_end() -> None:
    rule = Recurrence(Frequency.MONTHLY, date(2026, 1, 31), day_of_month=31)
    found = occurrences(rule, date(2026, 1, 1), date(2026, 4, 30))
    assert [o.scheduled for o in found] == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]
    assert [o.due for o in found] == [o.scheduled for o in found]


def test_business_day_adjustment_and_holidays() -> None:
    holidays = BusinessDays(frozenset({date(2026, 6, 1)}))  # synthetic
    rule = Recurrence(Frequency.MONTHLY, date(2026, 1, 1), day_of_month=1, adjust=Adjust.FOLLOWING)
    found = occurrences(rule, date(2026, 5, 1), date(2026, 8, 31), holidays)
    # 1 Aug 2026 is a Saturday; 1 June is the synthetic holiday.
    assert [(o.scheduled, o.due) for o in found] == [
        (date(2026, 5, 1), date(2026, 5, 1)),
        (date(2026, 6, 1), date(2026, 6, 2)),
        (date(2026, 7, 1), date(2026, 7, 1)),
        (date(2026, 8, 1), date(2026, 8, 3)),
    ]
    preceding = Recurrence(
        Frequency.MONTHLY, date(2026, 1, 1), day_of_month=1, adjust=Adjust.PRECEDING
    )
    # Adjusted out of the window (1 Aug -> 31 Jul) and into it.
    assert [o.due for o in occurrences(preceding, date(2026, 7, 2), date(2026, 7, 31))] == [
        date(2026, 7, 31)
    ]


def test_weekly_quarterly_yearly_and_end_dates() -> None:
    weekly = Recurrence(Frequency.WEEKLY, date(2026, 11, 6), interval=2)  # every other Friday
    assert [o.due for o in occurrences(weekly, date(2026, 11, 1), date(2026, 12, 31))] == [
        date(2026, 11, 6),
        date(2026, 11, 20),
        date(2026, 12, 4),
        date(2026, 12, 18),
    ]
    quarterly = Recurrence(Frequency.QUARTERLY, date(2026, 1, 15), end=date(2026, 12, 31))
    assert [o.due for o in occurrences(quarterly, date(2025, 1, 1), date(2028, 1, 1))] == [
        date(2026, 1, 15),
        date(2026, 4, 15),
        date(2026, 7, 15),
        date(2026, 10, 15),
    ]
    yearly = Recurrence(Frequency.YEARLY, date(2024, 2, 29))
    assert [o.due for o in occurrences(yearly, date(2025, 1, 1), date(2028, 12, 31))] == [
        date(2025, 2, 28),
        date(2026, 2, 28),
        date(2027, 2, 28),
        date(2028, 2, 29),
    ]
    late_start = Recurrence(Frequency.MONTHLY, date(2026, 1, 20), day_of_month=5)
    assert occurrences(late_start, date(2026, 1, 1), date(2026, 2, 28))[0].due == date(2026, 2, 5)
    far = occurrences(
        Recurrence(Frequency.MONTHLY, date(1990, 1, 10)), date(2026, 3, 1), date(2026, 3, 31)
    )
    assert [o.due for o in far] == [date(2026, 3, 10)]


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (Recurrence(Frequency.MONTHLY, date(2026, 1, 1), interval=0), "interval"),
        (Recurrence(Frequency.MONTHLY, date(2026, 1, 1), day_of_month=32), "day of the month"),
        (Recurrence(Frequency.WEEKLY, date(2026, 1, 1), day_of_month=3), "weekday"),
        (Recurrence(Frequency.MONTHLY, date(2026, 1, 2), end=date(2026, 1, 1)), "end date"),
    ],
)
def test_invalid_recurrences(rule: Recurrence, message: str) -> None:
    with pytest.raises(ScheduleError, match=message):
        occurrences(rule, date(2026, 1, 1), date(2026, 12, 31))


def test_too_many_occurrences() -> None:
    with pytest.raises(ScheduleError, match="Too many"):
        occurrences(
            Recurrence(Frequency.WEEKLY, date(2000, 1, 3)), date(2000, 1, 1), date(2100, 1, 1)
        )


@given(
    frequency=st.sampled_from(list(Frequency)),
    interval=st.integers(min_value=1, max_value=4),
    start=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    window_start=st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)),
    length=st.integers(min_value=0, max_value=400),
    adjust=st.sampled_from(list(Adjust)),
)
def test_occurrences_are_in_the_window_ordered_and_split_consistently(
    frequency: Frequency,
    interval: int,
    start: date,
    window_start: date,
    length: int,
    adjust: Adjust,
) -> None:
    from datetime import timedelta  # noqa: PLC0415

    rule = Recurrence(frequency, start, interval=interval, adjust=adjust)
    end = window_start + timedelta(days=length)
    found = occurrences(rule, window_start, end)
    assert all(window_start <= o.due <= end and o.scheduled >= start for o in found)
    assert [o.scheduled for o in found] == sorted({o.scheduled for o in found})
    middle = window_start + timedelta(days=length // 2)
    split = occurrences(rule, window_start, middle) + occurrences(
        rule, middle + timedelta(days=1), end
    )
    assert split == found
