"""Deterministic allocation of an amount into parts that sum exactly to the total.

Uses the largest-remainder method in the currency's minor units. Ties are broken by position
(earlier parts receive the extra unit first), so results are reproducible.
"""

from collections.abc import Sequence
from decimal import ROUND_FLOOR, Decimal

from .errors import InvalidAllocationError
from .money import FactorInput, Money, to_decimal
from .rounding import FINANCIAL_CONTEXT


def allocate(total: Money, ratios: Sequence[FactorInput]) -> list[Money]:
    """Split ``total`` proportionally to ``ratios``; the parts always sum exactly to ``total``.

    ``total`` must already be rounded to the currency's minor units (round it explicitly first,
    so the rounding decision is visible). Ratios must be non-negative with a positive sum.
    """
    if not ratios:
        raise InvalidAllocationError("At least one ratio is required.")
    weights = [to_decimal(r) for r in ratios]
    if any(w < 0 for w in weights):
        raise InvalidAllocationError("Ratios must not be negative.")
    weight_sum = sum(weights, Decimal(0))
    if weight_sum == 0:
        raise InvalidAllocationError("Ratios must not all be zero.")
    if not total.is_rounded():
        raise InvalidAllocationError(
            f"Total {total} has more decimals than {total.currency.code} allows; round it first."
        )

    sign = -1 if total.is_negative() else 1
    # Exact: total is rounded to the currency's quantum, so this is an integer number of units.
    units = int(FINANCIAL_CONTEXT.divide(abs(total.amount), total.currency.quantum))

    exact = [
        FINANCIAL_CONTEXT.divide(FINANCIAL_CONTEXT.multiply(units, w), weight_sum) for w in weights
    ]
    floors = [int(e.to_integral_value(rounding=ROUND_FLOOR)) for e in exact]
    remainder = units - sum(floors)
    # Largest fractional remainder first; ties resolved by original position.
    order = sorted(range(len(weights)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:remainder]:
        floors[i] += 1

    quantum = total.currency.quantum
    return [Money(FINANCIAL_CONTEXT.multiply(quantum, sign * n), total.currency) for n in floors]


def split_evenly(total: Money, parts: int) -> list[Money]:
    """Split ``total`` into ``parts`` near-equal amounts summing exactly to ``total``."""
    if parts < 1:
        raise InvalidAllocationError("parts must be at least 1.")
    return allocate(total, [1] * parts)
