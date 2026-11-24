"""Payment schedules: recurring obligations and loans (M3-4, doc 10 §3.2 and §3.5, AC-CW8).

Pure functions over dates and Decimals (no database, no clock):

- ``occurrences`` dates a recurring obligation (weekly, monthly, quarterly or yearly on a day of
  the month, clamped to the month's last day) and moves each date to a business day with the
  chosen convention.
- ``loan_schedule`` builds a loan's instalments for four repayment types: annuity (level payment),
  linear (equal principal), bullet (all principal at maturity) and interest-only then annuity.
  Interest accrues between the unadjusted payment dates with the instrument's day count:
  - ACT/360 and ACT/365 count actual days;
  - 30/360 uses the ISDA bond basis (day 31 counts as 30, and the end day 31 counts as 30 when
    the start day is 30 or 31).

  Payments fall on the business-day adjusted dates. Each period's interest is rounded to cents
  (HALF_UP) once. An annuity's level payment uses the nominal periodic rate (annual rate x months
  / 12), and the last instalment repays whatever balance is left, so the principal always adds up
  to the amount borrowed exactly.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from fcp.modules.calendar.api import Adjust, BusinessDays, add_months, month_end

CENT = Decimal("0.01")
ZERO = Decimal(0)
MAX_INSTALMENTS = 600  # 50 years of monthly payments
MAX_OCCURRENCES = 2000


def cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


class ScheduleError(ValueError):
    """Terms that do not describe a valid schedule (the message says which)."""


# --- day counts -----------------------------------------------------------------------------------


class DayCount(StrEnum):
    ACT_360 = "ACT_360"
    ACT_365 = "ACT_365"
    THIRTY_360 = "30_360"


def day_count(start: date, end: date, convention: DayCount) -> tuple[int, int]:
    """Days in the period and the year basis, under the convention."""
    if convention is DayCount.THIRTY_360:
        d1 = min(start.day, 30)
        d2 = 30 if end.day == 31 and d1 == 30 else end.day
        days = 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)
        return days, 360
    return (end - start).days, 360 if convention is DayCount.ACT_360 else 365


def interest(balance: Decimal, annual_rate: Decimal, start: date, end: date,
             convention: DayCount) -> Decimal:  # fmt: skip
    days, basis = day_count(start, end, convention)
    return cents(balance * annual_rate * days / basis)


# --- recurring obligations ------------------------------------------------------------------------


class Frequency(StrEnum):
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    YEARLY = "YEARLY"


_MONTHS = {Frequency.MONTHLY: 1, Frequency.QUARTERLY: 3, Frequency.YEARLY: 12}


@dataclass(frozen=True)
class Recurrence:
    frequency: Frequency
    start: date
    end: date | None = None
    interval: int = 1  # every N weeks / months / quarters / years
    day_of_month: int | None = None  # 1-31 (31 = the month's last day); default: the start's day
    adjust: Adjust = Adjust.NONE

    def check(self) -> None:
        if not 1 <= self.interval <= 52:
            raise ScheduleError("The interval is from 1 to 52.")
        if self.day_of_month is not None and not 1 <= self.day_of_month <= 31:
            raise ScheduleError("The day of the month is from 1 to 31.")
        if self.day_of_month is not None and self.frequency is Frequency.WEEKLY:
            raise ScheduleError("A weekly schedule repeats on the start date's weekday.")
        if self.end is not None and self.end < self.start:
            raise ScheduleError("The end date is before the start date.")


@dataclass(frozen=True)
class Occurrence:
    scheduled: date  # by the rule
    due: date  # moved to a business day


def _nth(rule: Recurrence, n: int) -> date:
    if rule.frequency is Frequency.WEEKLY:
        return rule.start + timedelta(weeks=n * rule.interval)
    first = add_months(rule.start.replace(day=1), n * rule.interval * _MONTHS[rule.frequency])
    return first.replace(day=min(rule.day_of_month or rule.start.day, month_end(first).day))


_SLACK = timedelta(days=10)  # an adjusted date moves by a few days at most


def occurrences(rule: Recurrence, date_from: date, date_to: date,
                business_days: BusinessDays | None = None) -> list[Occurrence]:  # fmt: skip
    """The occurrences due (after adjustment) from ``date_from`` to ``date_to`` inclusive."""
    rule.check()
    calendar = business_days or BusinessDays()
    found: list[Occurrence] = []
    months = _MONTHS.get(rule.frequency, 0)
    step_days = (
        7 * rule.interval
        if rule.frequency is Frequency.WEEKLY
        else 31 * rule.interval * months  # 31: never jumps past an occurrence
    )
    # Start a little before the window: an adjusted date can move into it.
    n = max(0, (date_from - rule.start - _SLACK).days // step_days - 1)
    while True:
        scheduled = _nth(rule, n)
        n += 1
        if scheduled < rule.start:
            continue  # the first month's day falls before the start date
        if (rule.end is not None and scheduled > rule.end) or scheduled > date_to + _SLACK:
            return found
        due = calendar.adjust(scheduled, rule.adjust)
        if date_from <= due <= date_to:
            found.append(Occurrence(scheduled, due))
            if len(found) > MAX_OCCURRENCES:
                raise ScheduleError("Too many occurrences; shorten the period.")


# --- loans ----------------------------------------------------------------------------------------


class Repayment(StrEnum):
    ANNUITY = "ANNUITY"
    LINEAR = "LINEAR"
    BULLET = "BULLET"
    IO_THEN_ANNUITY = "IO_THEN_ANNUITY"


@dataclass(frozen=True)
class Loan:
    principal: Decimal
    start: date  # drawdown; interest accrues from here
    maturity: date  # the last payment date (unadjusted)
    annual_rate: Decimal  # e.g. 0.05 for 5%
    frequency_months: int = 1  # 1, 3, 6 or 12
    repayment: Repayment = Repayment.ANNUITY
    day_count: DayCount = DayCount.THIRTY_360
    interest_only_periods: int = 0  # IO_THEN_ANNUITY only
    adjust: Adjust = Adjust.MODIFIED_FOLLOWING


@dataclass(frozen=True)
class Instalment:
    number: int
    period_start: date
    period_end: date  # unadjusted payment date: the end of the accrual period
    due: date  # adjusted payment date
    opening: Decimal
    interest: Decimal
    principal: Decimal
    payment: Decimal
    closing: Decimal


def _periods(loan: Loan) -> int:
    if loan.frequency_months not in (1, 3, 6, 12):
        raise ScheduleError("Payments are monthly, quarterly, half-yearly or yearly.")
    months = (loan.maturity.year - loan.start.year) * 12 + loan.maturity.month - loan.start.month
    n, rest = divmod(months, loan.frequency_months)
    if n < 1 or rest or add_months(loan.start, months) != loan.maturity:
        raise ScheduleError("The maturity must be a whole number of payment periods after the "
                            "start date.")  # fmt: skip
    if n > MAX_INSTALMENTS:
        raise ScheduleError(f"At most {MAX_INSTALMENTS} instalments.")
    return n


def _check(loan: Loan, n: int) -> None:
    if loan.principal <= 0 or loan.principal != cents(loan.principal):
        raise ScheduleError("The principal is a positive amount in cents.")
    if not ZERO <= loan.annual_rate < 1:
        raise ScheduleError("The annual rate is a fraction from 0 to 1 (0.05 is 5%).")
    io = loan.interest_only_periods
    if loan.repayment is Repayment.IO_THEN_ANNUITY:
        if not 1 <= io < n:
            raise ScheduleError("The interest-only periods are at least 1 and fewer than all.")
    elif io:
        raise ScheduleError("Interest-only periods apply to IO_THEN_ANNUITY only.")


def level_payment(principal: Decimal, periodic_rate: Decimal, periods: int) -> Decimal:
    """The annuity payment, rounded to cents: P * r / (1 - (1 + r)^-n)."""
    if periodic_rate == 0:
        return cents(principal / periods)
    return cents(principal * periodic_rate / (1 - (1 + periodic_rate) ** -periods))


def loan_schedule(loan: Loan, business_days: BusinessDays | None = None) -> list[Instalment]:
    n = _periods(loan)
    _check(loan, n)
    calendar = business_days or BusinessDays()
    io = loan.interest_only_periods
    amortising = n - io
    periodic = loan.annual_rate * loan.frequency_months / 12
    payment = level_payment(loan.principal, periodic, amortising)
    linear = cents(loan.principal / amortising)
    rows: list[Instalment] = []
    balance = loan.principal
    previous = loan.start
    for k in range(1, n + 1):
        end = add_months(loan.start, k * loan.frequency_months)
        owed = interest(balance, loan.annual_rate, previous, end, loan.day_count)
        if k == n:
            principal = balance
        elif loan.repayment is Repayment.BULLET or k <= io:
            principal = ZERO
        elif loan.repayment is Repayment.LINEAR:
            principal = min(linear, balance)
        else:
            principal = min(max(payment - owed, ZERO), balance)
        rows.append(Instalment(k, previous, end, calendar.adjust(end, loan.adjust), balance,
                               owed, principal, principal + owed, balance - principal))  # fmt: skip
        balance -= principal
        previous = end
    return rows
