"""Date and loan-schedule helpers for the synthetic generators (Decimal-only)."""

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fcp.core.money import FINANCIAL_CONTEXT, Money, split_evenly


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def previous_business_day(day: date) -> date:
    """Move a weekend date back to Friday (payments are made on business days)."""
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def next_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


@dataclass(frozen=True)
class Instalment:
    number: int
    due_date: date
    payment: Money
    interest: Money
    principal: Money
    closing_balance: Money


def annuity_schedule(
    principal: Money, annual_rate_bp: int, months: int, first_due: date
) -> list[Instalment]:
    """Monthly annuity schedule. Interest per period is rounded to cents (HALF_UP); the final
    instalment absorbs rounding so the closing balance is exactly zero."""
    if months < 1:
        raise ValueError("months must be at least 1")
    currency = principal.currency
    if annual_rate_bp == 0:
        parts = split_evenly(principal, months)
        balance = principal
        result = []
        for n, part in enumerate(parts, start=1):
            balance = balance - part
            due = add_months(first_due, n - 1)
            result.append(Instalment(n, due, part, Money.zero(currency), part, balance))
        return result

    ctx = FINANCIAL_CONTEXT
    rate = ctx.divide(Decimal(annual_rate_bp), Decimal(120_000))
    factor = ctx.power(ctx.add(Decimal(1), rate), -months)
    payment = principal.multiply(ctx.divide(rate, ctx.subtract(Decimal(1), factor))).round()

    balance = principal
    schedule = []
    for n in range(1, months + 1):
        interest = balance.multiply(rate).round()
        principal_part = payment - interest if n < months else balance
        instalment_payment = principal_part + interest
        balance = balance - principal_part
        due = add_months(first_due, n - 1)
        schedule.append(Instalment(n, due, instalment_payment, interest, principal_part, balance))
    return schedule
