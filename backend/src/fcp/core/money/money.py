"""The Money value object (ADR-0003).

Rules:
- Amounts are ``Decimal``. ``float`` (and ``bool``) inputs are rejected with ``TypeError``.
- NaN and infinities are rejected.
- Addition, subtraction and comparison require the same currency.
- Multiplication by a factor is exact (no rounding). Rounding happens only when ``round()`` is
  called with an explicit or default (currency minor units, HALF_UP) policy.
- ``Money`` has no truth value: use ``is_zero()``, so ``if amount:`` cannot hide a bug.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Self

from .currency import Currency, get_currency
from .errors import CurrencyMismatchError, InvalidAmountError
from .rounding import FINANCIAL_CONTEXT, RoundingMode, RoundingPolicy

type AmountInput = Decimal | int | str
type FactorInput = Decimal | int | str


def to_decimal(value: object) -> Decimal:
    """Convert an allowed input (Decimal, int, numeric string) to a finite Decimal.

    Raises TypeError for float/bool/other types and InvalidAmountError for non-numeric strings,
    NaN and infinities.
    """
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise TypeError(
            f"Monetary values must be Decimal, int or str, not {type(value).__name__}. "
            "Binary floating point is forbidden for financial values (ADR-0003)."
        )
    if isinstance(value, Decimal):
        result = value
    else:
        try:
            result = Decimal(value.strip() if isinstance(value, str) else value)
        except InvalidOperation:
            raise InvalidAmountError(f"Not a decimal number: {value!r}") from None
    if not result.is_finite():
        raise InvalidAmountError(f"Amount must be finite, got {value!r}")
    return result


@dataclass(frozen=True, slots=True)
class Money:
    """An exact amount in a specific currency."""

    amount: Decimal
    currency: Currency

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise TypeError("Use Money.of(...) to construct Money from non-Decimal amounts.")
        if not self.amount.is_finite():
            raise InvalidAmountError(f"Amount must be finite, got {self.amount!r}")
        if not isinstance(self.currency, Currency):
            raise TypeError("currency must be a Currency; use Money.of(amount, 'EUR').")

    # --- construction ----------------------------------------------------------------------

    @classmethod
    def of(cls, amount: AmountInput, currency: str | Currency) -> Self:
        """Create Money from a Decimal, int or numeric string, e.g. ``Money.of("10.50", "EUR")``."""
        return cls(to_decimal(amount), get_currency(currency))

    @classmethod
    def zero(cls, currency: str | Currency) -> Self:
        return cls(Decimal(0), get_currency(currency))

    @classmethod
    def total(cls, items: Iterable["Money"], currency: str | Currency) -> "Money":
        """Sum ``items`` (which may be empty) in ``currency``; mixed currencies raise."""
        result: Money = cls.zero(currency)
        for item in items:
            result = result + item
        return result

    # --- arithmetic --------------------------------------------------------------------------

    def _check_same_currency(self, other: "Money") -> None:
        if other.currency != self.currency:
            raise CurrencyMismatchError(
                f"Cannot combine {self.currency.code} and {other.currency.code} amounts "
                "without an explicit FX conversion."
            )

    # Signatures accept only Money so mypy rejects misuse statically; the runtime checks remain
    # for untyped callers.
    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._check_same_currency(other)
        return Money(FINANCIAL_CONTEXT.add(self.amount, other.amount), self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._check_same_currency(other)
        return Money(FINANCIAL_CONTEXT.subtract(self.amount, other.amount), self.currency)

    def __neg__(self) -> "Money":
        return Money(FINANCIAL_CONTEXT.minus(self.amount), self.currency)

    def __abs__(self) -> "Money":
        return Money(FINANCIAL_CONTEXT.abs(self.amount), self.currency)

    def multiply(self, factor: FactorInput) -> "Money":
        """Exact multiplication by a factor (e.g. a tax rate or FX rate). Not rounded."""
        return Money(FINANCIAL_CONTEXT.multiply(self.amount, to_decimal(factor)), self.currency)

    def __mul__(self, factor: FactorInput) -> "Money":
        if isinstance(factor, Money):
            return NotImplemented
        return self.multiply(factor)

    __rmul__ = __mul__

    def ratio_to(self, other: "Money") -> Decimal:
        """Return self / other as a Decimal (same currency). Raises on division by zero."""
        self._check_same_currency(other)
        if other.amount.is_zero():
            raise InvalidAmountError("Cannot compute a ratio to a zero amount.")
        return FINANCIAL_CONTEXT.divide(self.amount, other.amount)

    # --- rounding ----------------------------------------------------------------------------

    def round(self, policy: RoundingPolicy | None = None) -> "Money":
        """Round to ``policy`` (default: the currency's minor units, HALF_UP)."""
        policy = policy or RoundingPolicy(self.currency.minor_units, RoundingMode.HALF_UP)
        return Money(policy.apply(self.amount), self.currency)

    def is_rounded(self) -> bool:
        """True if the amount has no more decimal places than the currency's minor units."""
        return self.amount == self.amount.quantize(self.currency.quantum, context=FINANCIAL_CONTEXT)

    # --- predicates and comparison -------------------------------------------------------------

    def is_zero(self) -> bool:
        return self.amount.is_zero()

    def is_positive(self) -> bool:
        return self.amount > 0

    def is_negative(self) -> bool:
        return self.amount < 0

    def __bool__(self) -> bool:
        raise TypeError("Money has no truth value; use is_zero(), is_positive() or is_negative().")

    def __lt__(self, other: "Money") -> bool:
        self._check_same_currency(other)
        return self.amount < other.amount

    def __le__(self, other: "Money") -> bool:
        self._check_same_currency(other)
        return self.amount <= other.amount

    def __gt__(self, other: "Money") -> bool:
        self._check_same_currency(other)
        return self.amount > other.amount

    def __ge__(self, other: "Money") -> bool:
        self._check_same_currency(other)
        return self.amount >= other.amount

    # --- serialisation -----------------------------------------------------------------------

    def amount_str(self) -> str:
        """Plain (non-scientific) string of the amount, e.g. '1234.50'. Used for JSON."""
        return format(self.amount, "f")

    def to_dict(self) -> dict[str, str]:
        """API representation: amounts travel as strings, never JSON numbers."""
        return {"amount": self.amount_str(), "currency": self.currency.code}

    def __str__(self) -> str:
        return f"{self.currency.code} {self.amount_str()}"
