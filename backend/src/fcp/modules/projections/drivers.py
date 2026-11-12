"""The drivers of an assumption set (M6-2, brief §3): what each one means and its unit.

Every driver has one value per month of the horizon. Line drivers (revenue, operating costs) have
one row per taxonomy line; the others have a single row. Values are stored unrounded; the engine
rounds each statement line to cents once (doc 10 §2.4).
"""

from dataclasses import dataclass
from enum import StrEnum

REVENUE_LINES = ("REV.SALES", "REV.SERVICES", "REV.OTHER")
OPEX_LINES = (
    "OPEX.PAYROLL",
    "OPEX.RENT",
    "OPEX.UTILITIES",
    "OPEX.PROFESSIONAL",
    "OPEX.MARKETING",
    "OPEX.TRAVEL",
    "OPEX.INSURANCE",
    "OPEX.OTHER",
)


class Unit(StrEnum):
    AMOUNT = "AMOUNT"  # money per month
    PERCENT = "PERCENT"  # e.g. 35 for 35 %
    DAYS = "DAYS"
    MONTHS = "MONTHS"


@dataclass(frozen=True)
class Driver:
    key: str
    unit: Unit
    lines: tuple[str, ...] = ("",)  # taxonomy lines, or "" for a single row
    minimum: int | None = 0  # None: negative values allowed


DRIVERS: dict[str, Driver] = {
    d.key: d
    for d in (
        Driver("revenue", Unit.AMOUNT, REVENUE_LINES),
        Driver("gross_margin", Unit.PERCENT, minimum=None),  # on sales and services revenue
        Driver("opex", Unit.AMOUNT, OPEX_LINES),
        Driver("capex", Unit.AMOUNT),
        Driver("capex_life", Unit.MONTHS),
        Driver("dso", Unit.DAYS),
        Driver("dio", Unit.DAYS),
        Driver("dpo", Unit.DAYS),
        Driver("tax_rate", Unit.PERCENT),  # on profit before tax; paid the following year
        Driver("borrowing", Unit.AMOUNT),
        Driver("repayment", Unit.AMOUNT),
        Driver("interest_rate", Unit.PERCENT),  # a year, on opening debt
        Driver("dividends", Unit.AMOUNT),
        Driver("share_capital", Unit.AMOUNT),
        Driver("minimum_cash", Unit.AMOUNT),
        Driver("revolver_limit", Unit.AMOUNT),
        Driver("revolver_rate", Unit.PERCENT),  # a year
    )
}

DEFAULT_CAPEX_LIFE = 60  # months, when a set starts empty or from actuals
