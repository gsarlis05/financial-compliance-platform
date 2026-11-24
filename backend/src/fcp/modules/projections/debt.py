"""Loans in projections (M6F-4, #149; owner decision D5): pure functions, no database.

Conventions (stated with every projection):
- **Interest** each month on the balance at the **start** of the month (the owner's confirmed
  default): ``round(opening x annual rate / 12)`` for the month's rate. A variable rate is a rate
  path by month; a month without a path value keeps the last rate.
- **Drawdowns, scheduled repayments and early repayments** happen at the **end** of the month, so
  they change interest from the next month.
- **Repayment structures** (from the first repayment month):
  - ``ANNUITY``: a level payment worked out each month on the opening balance over the months
    left at the month's rate (rounded to cents); principal = payment - interest. An early
    repayment therefore lowers later payments and keeps the end date.
  - ``EQUAL_PRINCIPAL``: opening balance / months left (rounded); later payments keep the end date.
  - ``BULLET``: nothing until the last month, which repays the balance.
  Interest-only months come first, before the structure starts. The last month repays whatever
  is left, so a loan always ends at zero on its maturity month.
- An early repayment is capped at what is owed after the scheduled principal.
- **Current portion** (IAS 1.69): the scheduled principal of the next 12 months, worked out from the
  month-end balance with the current rate and no further drawdowns or early repayments.
- Every amount is rounded to cents once; balances are sums of rounded amounts, so each loan's
  roll-forward ties exactly (opening + drawdowns - principal - early repayment = closing).
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fcp.modules.calendar.api import add_months

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ANNUITY, EQUAL_PRINCIPAL, BULLET = "ANNUITY", "EQUAL_PRINCIPAL", "BULLET"
STRUCTURES = (ANNUITY, EQUAL_PRINCIPAL, BULLET)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class LoanTerms:
    """One loan. An existing loan has an ``opening`` balance at the cut-over and starts its
    remaining ``term_months`` with the first projected month; a new loan is drawn (``amount``) at
    the end of ``drawdown_month`` and its term starts the month after."""

    code: str
    structure: str
    term_months: int  # months of repayment, interest-only months included
    annual_rate: Decimal  # percent a year, e.g. 5.5 (the starting rate)
    opening: Decimal = ZERO
    amount: Decimal = ZERO
    drawdown_month: date | None = None
    interest_only_months: int = 0
    rate_path: dict[date, Decimal] = field(default_factory=dict)  # variable rate by month
    prepayments: dict[date, Decimal] = field(default_factory=dict)
    drawdowns: dict[date, Decimal] = field(default_factory=dict)  # extra drawdowns


@dataclass(frozen=True)
class LoanMonth:
    month: date
    opening: Decimal
    rate: Decimal  # percent a year
    interest: Decimal
    drawdown: Decimal
    principal: Decimal  # scheduled
    prepayment: Decimal
    closing: Decimal
    current: Decimal  # principal due within 12 months of the month end


def level_payment(balance: Decimal, monthly_rate: Decimal, months: int) -> Decimal:
    if months <= 0:
        return balance
    if monthly_rate == 0:
        return cents(balance / months)
    factor = (1 + monthly_rate) ** months
    return cents(balance * monthly_rate * factor / (factor - 1))


def _principal(structure: str, balance: Decimal, interest: Decimal, monthly_rate: Decimal,
               left: int, interest_only: bool) -> Decimal:  # fmt: skip
    """Scheduled principal for a month with ``left`` repayment months left (this one included)."""
    if balance <= 0 or left <= 0:
        return ZERO
    if left == 1:
        return balance
    if interest_only:
        return ZERO
    if structure == BULLET:
        return ZERO
    if structure == EQUAL_PRINCIPAL:
        return min(cents(balance / left), balance)
    payment = level_payment(balance, monthly_rate, left)
    return min(max(payment - interest, ZERO), balance)


def _current_portion(terms: LoanTerms, balance: Decimal, rate: Decimal, start_index: int,
                     total: int) -> Decimal:  # fmt: skip
    """Scheduled principal of the next 12 months from a month-end balance (no further changes)."""
    due = ZERO
    for k in range(12):
        index = start_index + k  # the repayment month number of that future month (0-based)
        if balance <= 0 or index >= total:
            break
        interest = cents(balance * rate / 100 / 12)
        left = total - index
        principal = _principal(terms.structure, balance, interest, rate / 100 / 12, left,
                               index < terms.interest_only_months)  # fmt: skip
        due += principal
        balance -= principal
    return due


def project_loan(terms: LoanTerms, months: list[date]) -> list[LoanMonth]:
    """The loan month by month over ``months`` (see the module text)."""
    if terms.structure not in STRUCTURES:
        raise ValueError(f"Unknown repayment structure {terms.structure}.")
    if terms.term_months < 1 or not 0 <= terms.interest_only_months < terms.term_months:
        raise ValueError("A loan needs a term of at least a month, longer than its interest-only "
                         "months.")  # fmt: skip
    new = terms.drawdown_month is not None
    first_repayment = (add_months(terms.drawdown_month, 1) if terms.drawdown_month
                       else months[0])  # fmt: skip
    balance = ZERO if new else cents(terms.opening)
    rate = terms.annual_rate
    rows: list[LoanMonth] = []
    for month in months:
        rate = terms.rate_path.get(month, rate)
        opening = balance
        interest = cents(opening * rate / 100 / 12)
        index = _index(first_repayment, month)
        left = terms.term_months - index
        principal = ZERO
        if index >= 0 and opening > 0:
            principal = _principal(terms.structure, opening, interest, rate / 100 / 12, left,
                                   index < terms.interest_only_months)  # fmt: skip
        prepayment = min(cents(terms.prepayments.get(month, ZERO)), opening - principal)
        prepayment = max(prepayment, ZERO)
        drawdown = cents(terms.drawdowns.get(month, ZERO))
        if new and month == terms.drawdown_month:
            drawdown += cents(terms.amount)
        balance = opening - principal - prepayment + drawdown
        current = _current_portion(terms, balance, rate, index + 1, terms.term_months)
        rows.append(LoanMonth(month, opening, rate, interest, drawdown, principal, prepayment,
                              balance, current))  # fmt: skip
    return rows


def _index(first: date, month: date) -> int:
    """The repayment month number of ``month`` (0 for the first), negative before it."""
    return (month.year - first.year) * 12 + month.month - first.month


def opening_current(terms: LoanTerms, first_month: date) -> Decimal:
    """The current portion of an existing loan at the cut-over (zero for a new loan)."""
    if terms.drawdown_month is not None:
        return ZERO
    rate = terms.rate_path.get(first_month, terms.annual_rate)
    return _current_portion(terms, cents(terms.opening), rate, 0, terms.term_months)
