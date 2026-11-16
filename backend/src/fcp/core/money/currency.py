"""ISO 4217 currencies supported by the platform.

The table is deliberately small and explicit; add currencies when a real need arises.
"""

from dataclasses import dataclass
from decimal import Decimal

from .errors import UnknownCurrencyError


@dataclass(frozen=True, slots=True)
class Currency:
    """An ISO 4217 currency with its number of minor units (decimal places)."""

    code: str
    minor_units: int

    @property
    def quantum(self) -> Decimal:
        """The smallest unit, e.g. Decimal('0.01') for EUR and Decimal('1') for JPY."""
        return Decimal(1).scaleb(-self.minor_units)

    def __str__(self) -> str:
        return self.code


_CURRENCIES: dict[str, Currency] = {
    c.code: c
    for c in (
        Currency("EUR", 2),
        Currency("USD", 2),
        Currency("GBP", 2),
        Currency("CHF", 2),
        Currency("SEK", 2),
        Currency("NOK", 2),
        Currency("DKK", 2),
        Currency("PLN", 2),
        Currency("CZK", 2),
        Currency("HUF", 2),
        Currency("RON", 2),
        Currency("BGN", 2),
        Currency("ILS", 2),
        Currency("AED", 2),
        Currency("RUB", 2),
        Currency("CNY", 2),
        Currency("JPY", 0),
        Currency("KWD", 3),
        Currency("BHD", 3),
    )
}

EUR = _CURRENCIES["EUR"]


def get_currency(code: str | Currency) -> Currency:
    """Return the Currency for an ISO 4217 code (case-sensitive, upper-case)."""
    if isinstance(code, Currency):
        return code
    try:
        return _CURRENCIES[code]
    except KeyError:
        raise UnknownCurrencyError(f"Unsupported currency code: {code!r}") from None
