"""Exact monetary arithmetic for the whole platform (ADR-0003).

Use ``Money`` for every monetary value. Binary floating point is forbidden for financial values.
"""

from .allocation import allocate, split_evenly
from .currency import EUR, Currency, get_currency
from .errors import (
    CurrencyMismatchError,
    InvalidAllocationError,
    InvalidAmountError,
    MoneyError,
    UnknownCurrencyError,
)
from .money import Money, to_decimal
from .rounding import FINANCIAL_CONTEXT, RoundingMode, RoundingPolicy

__all__ = [
    "EUR",
    "FINANCIAL_CONTEXT",
    "Currency",
    "CurrencyMismatchError",
    "InvalidAllocationError",
    "InvalidAmountError",
    "Money",
    "MoneyError",
    "RoundingMode",
    "RoundingPolicy",
    "UnknownCurrencyError",
    "allocate",
    "get_currency",
    "split_evenly",
    "to_decimal",
]
