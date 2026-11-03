"""Explicit rounding policies (ADR-0003). Every change of scale names its policy."""

import decimal
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

# Arithmetic context for financial calculations: generous precision, and invalid operations,
# division by zero and overflow raise instead of producing NaN or Infinity.
FINANCIAL_CONTEXT = decimal.Context(
    prec=38,
    rounding=decimal.ROUND_HALF_EVEN,
    Emin=-999_999,
    Emax=999_999,
    traps=[decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow],
)


class RoundingMode(Enum):
    """Supported rounding modes, mapped to the decimal module's constants."""

    HALF_UP = decimal.ROUND_HALF_UP
    """Ties away from zero (0.005 -> 0.01, -0.005 -> -0.01). Platform default for posting."""
    HALF_EVEN = decimal.ROUND_HALF_EVEN
    """Banker's rounding (0.005 -> 0.00, 0.015 -> 0.02)."""
    DOWN = decimal.ROUND_DOWN
    """Towards zero (truncation)."""
    UP = decimal.ROUND_UP
    """Away from zero."""
    FLOOR = decimal.ROUND_FLOOR
    """Towards negative infinity."""
    CEILING = decimal.ROUND_CEILING
    """Towards positive infinity."""


@dataclass(frozen=True, slots=True)
class RoundingPolicy:
    """Round to ``scale`` decimal places using ``mode``."""

    scale: int
    mode: RoundingMode = RoundingMode.HALF_UP

    def __post_init__(self) -> None:
        if not 0 <= self.scale <= 10:
            raise ValueError(f"Rounding scale must be between 0 and 10, got {self.scale}")

    def apply(self, value: Decimal) -> Decimal:
        """Return ``value`` rounded to this policy's scale and mode."""
        return value.quantize(
            Decimal(1).scaleb(-self.scale), rounding=self.mode.value, context=FINANCIAL_CONTEXT
        )
