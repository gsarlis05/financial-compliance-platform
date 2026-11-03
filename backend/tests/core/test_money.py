"""Tests for fcp.core.money (AC-M0-3, AC-M0-7)."""

from collections.abc import Callable
from decimal import Decimal

import pytest

from fcp.core.money import (
    EUR,
    Currency,
    CurrencyMismatchError,
    InvalidAmountError,
    Money,
    RoundingMode,
    RoundingPolicy,
    UnknownCurrencyError,
    get_currency,
    to_decimal,
)


def eur(value: str) -> Money:
    return Money.of(value, "EUR")


# --- construction ---------------------------------------------------------------------------


def test_decimal_addition_is_exact() -> None:
    assert eur("0.1") + eur("0.2") == eur("0.3")


@pytest.mark.parametrize("bad", [0.1, 1.0, float("nan"), True, None, [1], object()])
def test_non_decimal_inputs_are_rejected_with_type_error(bad: object) -> None:
    with pytest.raises(TypeError, match="ADR-0003"):
        Money.of(bad, "EUR")  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "abc", "", "1,000.00", "sNaN"])
def test_non_finite_or_malformed_amounts_are_rejected(bad: str) -> None:
    with pytest.raises(InvalidAmountError):
        Money.of(bad, "EUR")


def test_decimal_nan_is_rejected() -> None:
    with pytest.raises(InvalidAmountError):
        Money.of(Decimal("NaN"), "EUR")


def test_direct_construction_requires_decimal_and_currency() -> None:
    with pytest.raises(TypeError):
        Money(1, EUR)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        Money(Decimal(1), "EUR")  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        Money(Decimal("Infinity"), EUR)


def test_accepts_int_decimal_and_padded_string() -> None:
    assert Money.of(5, "EUR") == Money.of(Decimal("5.00"), "EUR") == Money.of(" 5 ", EUR)


def test_unknown_currency_is_rejected() -> None:
    with pytest.raises(UnknownCurrencyError):
        Money.of("1", "XXX")
    with pytest.raises(UnknownCurrencyError):
        get_currency("eur")


def test_currency_quantum() -> None:
    assert EUR.quantum == Decimal("0.01")
    assert get_currency("JPY").quantum == Decimal("1")
    assert get_currency("BHD").quantum == Decimal("0.001")
    assert str(EUR) == "EUR"
    assert get_currency(EUR) is EUR


def test_zero_and_total() -> None:
    assert Money.zero("EUR").is_zero()
    assert Money.total([], "EUR") == Money.zero("EUR")
    assert Money.total([eur("1.10"), eur("2.20"), eur("-0.30")], "EUR") == eur("3.00")
    with pytest.raises(CurrencyMismatchError):
        Money.total([eur("1"), Money.of("1", "USD")], "EUR")


# --- arithmetic ----------------------------------------------------------------------------


def test_subtraction_negation_and_abs() -> None:
    assert eur("10.00") - eur("10.01") == eur("-0.01")
    assert -eur("5") == eur("-5")
    assert abs(eur("-5.25")) == eur("5.25")


def test_currency_mismatch_raises_for_arithmetic_and_comparison() -> None:
    usd = Money.of("1", "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = eur("1") + usd
    with pytest.raises(CurrencyMismatchError):
        _ = eur("1") - usd
    comparisons: list[Callable[[], bool]] = [
        lambda: eur("1") < usd,
        lambda: eur("1") <= usd,
        lambda: eur("1") > usd,
        lambda: eur("1") >= usd,
    ]
    for compare in comparisons:
        with pytest.raises(CurrencyMismatchError):
            compare()


def test_adding_non_money_is_a_type_error() -> None:
    with pytest.raises(TypeError):
        _ = eur("1") + 1  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = eur("1") - Decimal(1)  # type: ignore[operator]


def test_multiplication_is_exact_and_rejects_float() -> None:
    assert eur("100.00").multiply("0.19") == eur("19.0000")
    assert eur("33.33") * 3 == eur("99.99")
    assert 3 * eur("33.33") == eur("99.99")
    assert eur("1") * Decimal("1.0837") == eur("1.0837")
    with pytest.raises(TypeError):
        _ = eur("1") * 1.5  # type: ignore[operator]
    with pytest.raises(TypeError):
        _ = eur("1") * eur("2")  # type: ignore[operator]


def test_ratio_to() -> None:
    assert eur("25").ratio_to(eur("100")) == Decimal("0.25")
    with pytest.raises(InvalidAmountError):
        eur("1").ratio_to(eur("0"))
    with pytest.raises(CurrencyMismatchError):
        eur("1").ratio_to(Money.of("1", "USD"))


def test_large_amounts_keep_full_precision() -> None:
    big = eur("9999999999999.99")  # ~10^13
    assert big + eur("0.01") == eur("10000000000000.00")
    assert (big * 1000).amount_str() == "9999999999999990.00"
    assert (big - big).is_zero()


# --- rounding -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "half_up", "half_even"),
    [
        ("0.005", "0.01", "0.00"),
        ("0.015", "0.02", "0.02"),
        ("0.025", "0.03", "0.02"),
        ("-0.005", "-0.01", "0.00"),
        ("-0.015", "-0.02", "-0.02"),
        ("2.675", "2.68", "2.68"),  # the classic float failure (float gives 2.67)
        ("1.0049999", "1.00", "1.00"),
    ],
)
def test_half_up_vs_half_even_at_boundaries(value: str, half_up: str, half_even: str) -> None:
    assert eur(value).round() == eur(half_up)
    assert eur(value).round(RoundingPolicy(2, RoundingMode.HALF_EVEN)) == eur(half_even)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (RoundingMode.DOWN, "-1.23"),
        (RoundingMode.UP, "-1.24"),
        (RoundingMode.FLOOR, "-1.24"),
        (RoundingMode.CEILING, "-1.23"),
    ],
)
def test_directional_rounding_modes(mode: RoundingMode, expected: str) -> None:
    assert eur("-1.2345").round(RoundingPolicy(2, mode)) == eur(expected)


def test_default_rounding_uses_currency_minor_units() -> None:
    assert Money.of("1234.5", "JPY").round() == Money.of("1235", "JPY")
    assert Money.of("1.2345", "BHD").round() == Money.of("1.235", "BHD")


def test_is_rounded() -> None:
    assert eur("1.20").is_rounded()
    assert eur("1.2").is_rounded()
    assert not eur("1.205").is_rounded()


def test_rounding_policy_scale_is_validated() -> None:
    with pytest.raises(ValueError, match="scale"):
        RoundingPolicy(-1)
    with pytest.raises(ValueError, match="scale"):
        RoundingPolicy(11)


# --- predicates, truthiness, serialisation ------------------------------------------------


def test_predicates() -> None:
    assert eur("0.00").is_zero()
    assert eur("0.01").is_positive()
    assert eur("-0.01").is_negative()
    assert not eur("0").is_positive()
    assert not eur("0").is_negative()


def test_money_has_no_truth_value() -> None:
    with pytest.raises(TypeError, match="truth value"):
        bool(eur("0"))


def test_ordering_within_currency() -> None:
    assert eur("1") < eur("2") <= eur("2") < eur("3")
    assert eur("3") > eur("2") >= eur("2")


def test_equality_ignores_trailing_zeros_and_hash_is_consistent() -> None:
    assert eur("1.5") == eur("1.50")
    assert hash(eur("1.5")) == hash(eur("1.50"))
    assert eur("1") != Money.of("1", "USD")


def test_serialisation_uses_strings_never_numbers() -> None:
    m = eur("1234.50")
    assert m.to_dict() == {"amount": "1234.50", "currency": "EUR"}
    assert str(m) == "EUR 1234.50"
    assert Money.of("1E+3", "EUR").amount_str() == "1000"
    assert Money.of("1E-7", "EUR").amount_str() == "0.0000001"


def test_to_decimal_helper() -> None:
    assert to_decimal("1.10") == Decimal("1.10")
    assert to_decimal(3) == Decimal(3)
    with pytest.raises(TypeError):
        to_decimal(1.1)


def test_currency_is_a_value_object() -> None:
    assert Currency("EUR", 2) == EUR
