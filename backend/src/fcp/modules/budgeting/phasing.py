"""Phasing an annual amount into months (M4-2, AC-BU2). Pure functions, Decimal only.

Allocation methods (EVEN, SEASONAL, PROFILE) split an annual input by weights. Each month except
the last is ``annual * weight / sum(weights)`` rounded to cents (half up) once; the **last month
takes the rounding residual**, so the months always sum exactly to the annual input. If rounding
half up would leave the last month with the opposite sign (tiny amounts spread over many months),
the other months are rounded toward zero instead, so no month ever has the opposite sign.

DRIVER computes each month as quantity * rate, rounded to cents once; its annual total is the sum
of the months (there is no separate annual input to match).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
MAX_ABS = Decimal("1e15")
ZERO = Decimal(0)
METHODS = ("MANUAL", "EVEN", "SEASONAL", "PROFILE", "DRIVER")


class PhasingError(ValueError):
    """Invalid phasing parameters; the message is shown to the user."""


@dataclass(frozen=True)
class Phased:
    amounts: list[Decimal]
    note: str = ""


def _decimal(value: object, what: str) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise PhasingError(f"{what} must be a number.") from exc
    if not number.is_finite() or abs(number) >= MAX_ABS:
        raise PhasingError(f"{what} must be a number with fewer than 16 digits.")
    return number


def _cents(value: Decimal, what: str) -> Decimal:
    if value != value.quantize(CENT):
        raise PhasingError(f"{what} has at most 2 decimals.")
    return value


def allocate(annual: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """Split ``annual`` by ``weights`` (non-negative, not all zero); residual on the last month."""
    if not weights:
        raise PhasingError("There are no months to phase into.")
    if any(w < 0 for w in weights):
        raise PhasingError("Weights cannot be negative.")
    total = sum(weights, ZERO)
    if total == 0:
        raise PhasingError("At least one weight must be above zero.")
    months = [(annual * w / total).quantize(CENT, rounding=ROUND_HALF_UP) for w in weights[:-1]]
    last = annual - sum(months, ZERO)
    if last * annual < 0:  # tiny amounts: rounding up would push the last month across zero
        months = [(annual * w / total).quantize(CENT, rounding=ROUND_DOWN) for w in weights[:-1]]
        last = annual - sum(months, ZERO)
    return [*months, last]


def _series(raw: object, n: int, what: str) -> list[Decimal]:
    """One value for every month, or a list with exactly one value per month."""
    if isinstance(raw, (list, tuple)):
        if len(raw) != n:
            raise PhasingError(f"{what} needs {n} values, one per month.")
        return [_decimal(v, what) for v in raw]
    return [_decimal(raw, what)] * n


def phase(
    method: str, months: int, params: dict[str, Any], seasonal: Sequence[Decimal] | None = None
) -> Phased:
    """Monthly amounts for an allocation or driver method (not MANUAL).

    ``params``: ``annual`` (EVEN, SEASONAL, PROFILE); ``weights`` (PROFILE, one per month);
    ``quantity`` and ``rate`` (DRIVER; a single value or one per month). ``seasonal`` holds the
    prior year's monthly actuals in the line's natural direction (SEASONAL)."""
    if method == "DRIVER":
        quantity = _series(params.get("quantity"), months, "Quantity")
        rate = _series(params.get("rate"), months, "Rate")
        products = [q * r for q, r in zip(quantity, rate, strict=True)]
        if any(abs(p) >= MAX_ABS for p in products) or abs(sum(products, ZERO)) >= MAX_ABS:
            raise PhasingError("The result is too large.")
        amounts = [p.quantize(CENT, rounding=ROUND_HALF_UP) for p in products]
        return Phased(amounts)
    if method not in ("EVEN", "SEASONAL", "PROFILE"):
        raise PhasingError("Choose even, seasonal, profile or driver phasing.")
    annual = _cents(_decimal(params.get("annual"), "The annual amount"), "The annual amount")
    if method == "EVEN":
        return Phased(allocate(annual, [Decimal(1)] * months))
    if method == "PROFILE":
        weights = _series(params.get("weights"), months, "Weights")
        if not isinstance(params.get("weights"), (list, tuple)):
            raise PhasingError(f"Weights needs {months} values, one per month.")
        return Phased(allocate(annual, weights))
    history = [max(v, ZERO) for v in (seasonal or [])]
    if len(history) != months or sum(history, ZERO) == 0:
        return Phased(
            allocate(annual, [Decimal(1)] * months),
            "No prior-year actuals for this line; phased evenly.",
        )
    return Phased(allocate(annual, history), "Phased like the prior year's actuals.")
