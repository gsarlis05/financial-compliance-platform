"""Phasing sums exactly to the annual input, with the residual on the last month (AC-BU2)."""

from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fcp.modules.budgeting.phasing import PhasingError, allocate, phase
from fcp.modules.budgeting.services import quarters

D = Decimal
cents = st.integers(min_value=-(10**14), max_value=10**14).map(lambda n: D(n) / 100)
weights = st.lists(st.integers(min_value=0, max_value=10**6).map(D), min_size=1, max_size=13)


@given(annual=cents, w=weights.filter(any))
def test_allocation_sums_exactly_and_only_the_last_month_absorbs_rounding(
    annual: Decimal, w: list[Decimal]
) -> None:
    months = allocate(annual, w)
    assert len(months) == len(w)
    assert sum(months, D(0)) == annual
    total = sum(w, D(0))
    assert all(m * annual >= 0 for m in months)  # no month has the opposite sign
    for m, weight in zip(months[:-1], w[:-1], strict=True):
        assert m == m.quantize(D("0.01"))
        assert abs(m - annual * weight / total) < D("0.01")
    assert months[-1] == months[-1].quantize(D("0.01"))


@given(annual=cents, n=st.integers(min_value=1, max_value=13))
def test_quarters_are_sums_of_months(annual: Decimal, n: int) -> None:
    months = phase("EVEN", n, {"annual": str(annual)}).amounts
    assert sum(quarters([date(2026, 1, 1)] * n, months), D(0)) == annual


def test_worked_examples() -> None:
    assert phase("EVEN", 12, {"annual": "100000.00"}).amounts == [D("8333.33")] * 11 + [
        D("8333.37")
    ]
    assert phase("EVEN", 3, {"annual": "0.01"}).amounts == [D("0.00"), D("0.00"), D("0.01")]
    # 0.10 / 12 rounds up to 0.01, which would leave -0.01 for December: rounded down instead.
    assert phase("EVEN", 12, {"annual": "0.10"}).amounts == [D("0.00")] * 11 + [D("0.10")]
    assert phase("EVEN", 12, {"annual": "-0.10"}).amounts == [D("0.00")] * 11 + [D("-0.10")]
    assert phase("PROFILE", 4, {"annual": "1000", "weights": ["1", "2", "3", "4"]}).amounts == [
        D("100.00"),
        D("200.00"),
        D("300.00"),
        D("400.00"),
    ]
    driver = phase("DRIVER", 3, {"quantity": ["2", "2", "3"], "rate": "1250.555"})
    assert driver.amounts == [D("2501.11"), D("2501.11"), D("3751.67")]
    seasonal = phase("SEASONAL", 3, {"annual": "900"}, [D(100), D(-50), D(200)])
    assert seasonal.amounts == [D("300.00"), D("0.00"), D("600.00")]  # negative months weigh 0
    assert seasonal.note.startswith("Phased like")
    fallback = phase("SEASONAL", 2, {"annual": "10"}, [D(0), D(0)])
    assert fallback.amounts == [D("5.00"), D("5.00")]
    assert "evenly" in fallback.note
    assert phase("SEASONAL", 2, {"annual": "10"}).amounts == [D("5.00"), D("5.00")]


@pytest.mark.parametrize(
    ("method", "params", "message"),
    [
        ("EVEN", {"annual": "x"}, "must be a number"),
        ("EVEN", {"annual": "1.001"}, "2 decimals"),
        ("EVEN", {"annual": "1e16"}, "fewer than 16"),
        ("EVEN", {}, "must be a number"),
        ("PROFILE", {"annual": "1", "weights": ["1"]}, "needs 3 values"),
        ("PROFILE", {"annual": "1", "weights": "1"}, "needs 3 values"),
        ("PROFILE", {"annual": "1", "weights": ["0", "0", "0"]}, "above zero"),
        ("PROFILE", {"annual": "1", "weights": ["1", "-1", "1"]}, "negative"),
        ("DRIVER", {"quantity": "1"}, "Rate must be a number"),
        ("DRIVER", {"quantity": "1e14", "rate": "1e14"}, "too large"),
        ("GUESS", {}, "Choose"),
    ],
)
def test_invalid_parameters(method: str, params: dict[str, object], message: str) -> None:
    with pytest.raises(PhasingError, match=message):
        phase(method, 3, params)
    with pytest.raises(PhasingError, match="no months"):
        allocate(D(1), [])
