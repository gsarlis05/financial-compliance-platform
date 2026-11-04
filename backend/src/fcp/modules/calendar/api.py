"""Public interface of the ``calendar`` module (M3-1, doc 10 P8): the one calendar for planning.

Pure date functions are re-exported from ``dates``; ``fiscal_calendar`` loads an entity's fiscal
years from the ledger (planning modules call this instead of importing the ledger).
"""

from uuid import UUID

from fcp.modules.ledger.api import fiscal_year_list
from fcp.modules.tenancy.api import WorkspaceContext

from .dates import (
    Adjust,
    Allocation,
    Bucket,
    BusinessDays,
    FiscalCalendar,
    FiscalYear,
    add_months,
    allocate,
    days_between,
    iso_week,
    month_end,
    month_start,
    monthly_buckets,
    quarter,
    week_end,
    week_label,
    week_start,
    weekly_buckets,
    weeks_in_iso_year,
)

__all__ = [
    "Adjust",
    "Allocation",
    "Bucket",
    "BusinessDays",
    "FiscalCalendar",
    "FiscalYear",
    "add_months",
    "allocate",
    "days_between",
    "fiscal_calendar",
    "iso_week",
    "month_end",
    "month_start",
    "monthly_buckets",
    "quarter",
    "week_end",
    "week_label",
    "week_start",
    "weekly_buckets",
    "weeks_in_iso_year",
]


def fiscal_calendar(ctx: WorkspaceContext, entity_id: UUID) -> FiscalCalendar:
    """The entity's fiscal years (requires ``ledger.period.read``)."""
    years = fiscal_year_list(ctx, entity_id)
    return FiscalCalendar(tuple(FiscalYear(y.name, y.start_date, y.end_date) for y in years))
