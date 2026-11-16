"""Depreciation schedules (M6-1, AC-FA1): hand-computed tables to the cent, and properties that
hold for any asset (months add up to cost - residual exactly, never below the residual)."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fcp.modules.assets.schedule import (
    DECLINING_BALANCE,
    AssetTerms,
    book_value,
    depreciation_for,
    disposal_result,
    schedule,
)

D = Decimal


def test_straight_line_by_hand() -> None:
    # 10,000 cost, 1,000 residual, 36 months: 9,000 / 36 = 250.00 a month, from February.
    rows = schedule(AssetTerms(date(2026, 1, 15), D("10000.00"), D("1000.00"), 36))
    assert len(rows) == 36
    assert rows[0].month == date(2026, 2, 1)
    assert {r.depreciation for r in rows} == {D("250.00")}
    assert rows[-1].month == date(2029, 1, 1)
    assert (rows[-1].closing, rows[-1].accumulated) == (D("1000.00"), D("9000.00"))


def test_straight_line_remainder_goes_to_the_last_month() -> None:
    # 1,000 over 3 months: 333.33, 333.33, then 333.34 so the total is exact.
    rows = schedule(AssetTerms(date(2026, 3, 31), D("1000.00"), D("0"), 3))
    assert [r.depreciation for r in rows] == [D("333.33"), D("333.33"), D("333.34")]
    assert [r.month for r in rows] == [date(2026, 4, 1), date(2026, 5, 1), date(2026, 6, 1)]


def test_declining_balance_by_hand() -> None:
    # 10,000 cost, 1,000 residual, 30% a year (2.5% a month), 24 months.
    terms = AssetTerms(date(2026, 1, 10), D("10000.00"), D("1000.00"), 24, DECLINING_BALANCE,
                       D("0.30"))  # fmt: skip
    rows = schedule(terms)
    # 10,000 x 2.5% = 250.00; 9,750 x 2.5% = 243.75; 9,506.25 x 2.5% = 237.65625 -> 237.66
    assert [r.depreciation for r in rows[:3]] == [D("250.00"), D("243.75"), D("237.66")]
    assert rows[2].closing == D("9268.59")
    # The last month takes the book value down to the residual exactly.
    assert rows[-1].closing == D("1000.00")
    assert sum(r.depreciation for r in rows) == D("9000.00")
    assert rows[-1].depreciation > rows[-2].depreciation  # the catch-up is visible


def test_disposal_stops_depreciation_and_gives_the_gain_or_loss() -> None:
    terms = AssetTerms(date(2026, 1, 15), D("12000.00"), D("0"), 24, disposed_on=date(2026, 7, 20))
    rows = schedule(terms)
    # February to June: 5 months of 500.00; nothing from July, the month of disposal.
    assert [r.month.month for r in rows] == [2, 3, 4, 5, 6]
    assert depreciation_for(terms, date(2026, 7, 1)) == D("0.00")
    assert book_value(terms, date(2026, 6, 30)) == D("9500.00")
    result = disposal_result(terms, D("9000.00"))
    assert (result.book_value, result.gain) == (D("9500.00"), D("-500.00"))


def test_book_value_before_acquisition_and_during_the_first_month() -> None:
    terms = AssetTerms(date(2026, 5, 20), D("600.00"), D("0"), 6)
    assert book_value(terms, date(2026, 4, 30)) == D("0.00")
    assert book_value(terms, date(2026, 5, 31)) == D("600.00")  # no depreciation yet
    assert book_value(terms, date(2026, 6, 30)) == D("500.00")
    assert book_value(terms, date(2030, 1, 1)) == D("0.00")


@pytest.mark.parametrize(
    "bad",
    [
        AssetTerms(date(2026, 1, 1), D("100"), D("0"), 0),
        AssetTerms(date(2026, 1, 1), D("100"), D("200"), 12),
        AssetTerms(date(2026, 1, 1), D("-1"), D("0"), 12),
        AssetTerms(date(2026, 1, 1), D("100"), D("0"), 12, DECLINING_BALANCE, None),
    ],
)
def test_invalid_terms_are_refused(bad: AssetTerms) -> None:
    with pytest.raises(ValueError, match=r"must|needs"):
        schedule(bad)


cents = st.integers(min_value=0, max_value=10**10).map(lambda c: D(c) / 100)


@given(
    cost=cents,
    residual_share=st.integers(min_value=0, max_value=100),
    life=st.integers(min_value=1, max_value=600),
    declining=st.booleans(),
    rate=st.integers(min_value=1, max_value=200).map(lambda p: D(p) / 100),
)
def test_any_schedule_adds_up_exactly(cost: Decimal, residual_share: int, life: int,
                                      declining: bool, rate: Decimal) -> None:  # fmt: skip
    residual = (cost * residual_share / 100).quantize(D("0.01"))
    terms = AssetTerms(date(2026, 2, 28), cost, residual, life,
                       DECLINING_BALANCE if declining else "STRAIGHT_LINE", rate)  # fmt: skip
    rows = schedule(terms)
    assert len(rows) == life
    assert sum(r.depreciation for r in rows) == cost - residual
    assert rows[-1].closing == residual
    for prev, row in zip([None, *rows], rows, strict=False):
        assert row.depreciation >= 0
        assert row.depreciation == row.depreciation.quantize(D("0.01"))
        assert row.closing == row.opening - row.depreciation >= residual
        if prev is not None:
            assert row.opening == prev.closing
