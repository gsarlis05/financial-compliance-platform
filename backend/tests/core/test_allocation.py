"""Tests for deterministic allocation, including property-based tests (AC-M0-3)."""

from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from fcp.core.money import InvalidAllocationError, Money, allocate, split_evenly


def eur(value: str) -> Money:
    return Money.of(value, "EUR")


def test_100_split_three_ways_sums_exactly() -> None:
    parts = split_evenly(eur("100.00"), 3)
    assert parts == [eur("33.34"), eur("33.33"), eur("33.33")]
    assert Money.total(parts, "EUR") == eur("100.00")


def test_proportional_allocation() -> None:
    assert allocate(eur("100.00"), [1, 1, 2]) == [eur("25.00"), eur("25.00"), eur("50.00")]
    # 5 cents at 30/70 = 1.5 and 3.5 cents; equal remainders, so the earlier part gets the cent.
    assert allocate(eur("0.05"), ["0.3", "0.7"]) == [eur("0.02"), eur("0.03")]


def test_ties_go_to_earlier_parts_deterministically() -> None:
    assert allocate(eur("0.02"), [1, 1, 1]) == [eur("0.01"), eur("0.01"), eur("0.00")]


def test_negative_total_allocates_with_sign() -> None:
    parts = split_evenly(eur("-100.00"), 3)
    assert parts == [eur("-33.34"), eur("-33.33"), eur("-33.33")]


def test_zero_ratio_parts_receive_nothing() -> None:
    assert allocate(eur("10.00"), [0, 1]) == [eur("0.00"), eur("10.00")]


def test_zero_currency_minor_units() -> None:
    parts = split_evenly(Money.of("100", "JPY"), 3)
    assert [p.amount for p in parts] == [Decimal(34), Decimal(33), Decimal(33)]


@pytest.mark.parametrize(
    ("total", "ratios", "message"),
    [
        ("10.00", [], "At least one"),
        ("10.00", [1, -1], "negative"),
        ("10.00", [0, 0], "all be zero"),
        ("10.005", [1, 1], "round it first"),
    ],
)
def test_invalid_allocations(total: str, ratios: list[int], message: str) -> None:
    with pytest.raises(InvalidAllocationError, match=message):
        allocate(eur(total), ratios)


def test_split_evenly_requires_at_least_one_part() -> None:
    with pytest.raises(InvalidAllocationError):
        split_evenly(eur("1.00"), 0)


def test_float_ratios_are_rejected() -> None:
    with pytest.raises(TypeError):
        allocate(eur("1.00"), [0.5, 0.5])  # type: ignore[list-item]


amounts = st.decimals(
    min_value=Decimal("-1000000000000"),
    max_value=Decimal("1000000000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
ratio_lists = st.lists(
    st.decimals(min_value=0, max_value=1000, places=4, allow_nan=False, allow_infinity=False),
    min_size=1,
    max_size=12,
).filter(lambda rs: sum(rs) > 0)


@given(total=amounts, ratios=ratio_lists)
def test_allocation_always_sums_exactly_to_total(total: Decimal, ratios: list[Decimal]) -> None:
    parts = allocate(Money.of(total, "EUR"), ratios)
    assert Money.total(parts, "EUR") == Money.of(total, "EUR")
    assert all(p.is_rounded() for p in parts)


@given(total=amounts, ratios=ratio_lists)
def test_each_part_is_within_one_cent_of_its_exact_share(
    total: Decimal, ratios: list[Decimal]
) -> None:
    parts = allocate(Money.of(total, "EUR"), ratios)
    weight_sum = sum(ratios, Decimal(0))
    for part, ratio in zip(parts, ratios, strict=True):
        exact = total * ratio / weight_sum
        assert abs(part.amount - exact) < Decimal("0.01")


@given(total=amounts, ratios=ratio_lists)
def test_allocation_is_deterministic(total: Decimal, ratios: list[Decimal]) -> None:
    money = Money.of(total, "EUR")
    assert allocate(money, ratios) == allocate(money, ratios)


@given(a=amounts, b=amounts, c=amounts)
def test_addition_is_exact_commutative_and_associative(a: Decimal, b: Decimal, c: Decimal) -> None:
    x, y, z = (Money.of(v, "EUR") for v in (a, b, c))
    assert x + y == y + x
    assert (x + y) + z == x + (y + z)
    assert (x + y) - y == x


@given(value=st.decimals(min_value=-(10**13), max_value=10**13, places=6, allow_nan=False))
def test_rounding_is_idempotent_and_within_half_a_cent(value: Decimal) -> None:
    once = Money.of(value, "EUR").round()
    assert once.round() == once
    assert abs(once.amount - value) <= Decimal("0.005")
