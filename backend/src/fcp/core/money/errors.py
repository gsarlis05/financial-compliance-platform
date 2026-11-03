"""Money errors. Each has a stable ``code`` for API problem responses."""


class MoneyError(ValueError):
    """Base class for money-related errors."""

    code = "money.invalid"


class InvalidAmountError(MoneyError):
    """The amount is not a finite, exactly representable decimal value."""

    code = "money.invalid_amount"


class UnknownCurrencyError(MoneyError):
    """The currency code is not a supported ISO 4217 code."""

    code = "money.unknown_currency"


class CurrencyMismatchError(MoneyError):
    """An operation combined amounts in different currencies."""

    code = "money.currency_mismatch"


class InvalidAllocationError(MoneyError):
    """An allocation request is invalid (e.g. no ratios, negative ratios, zero total ratio)."""

    code = "money.invalid_allocation"
