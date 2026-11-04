"""KPI sets: run the library on a period, read the latest set, and list the definitions (M4-4).

A KPI set is a calculation run (``KPI_SET``): reproducible from its watermark and its account
mapping snapshot, and every value explains itself (definition, reference calls, accounts).
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.calendar.api import add_months, month_end
from fcp.modules.metrics.api import (
    CalcRun,
    calc_results,
    completeness,
    current_mapping,
    execute,
    list_calc_runs,
)
from fcp.modules.reporting.api import accounts, posted_since
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .engine import KIND, account_snapshot
from .library import DEFAULT_LIBRARY
from .models import KpiDefinition

MAX_MONTHS = 12


@dataclass(frozen=True)
class KpiSet:
    run: CalcRun
    definitions: dict[str, KpiDefinition]
    values: list[Any]  # CalcResult rows, in library order
    unmapped_accounts: int
    out_of_date: bool  # entries were posted after the run's watermark (checked on reading)


def definitions(library: str = DEFAULT_LIBRARY) -> list[KpiDefinition]:
    return list(KpiDefinition.objects.filter(library=library).order_by("order"))


def _period(date_from: date, date_to: date) -> None:
    if date_from.day != 1 or date_to != month_end(date_to) or date_to < date_from:
        raise ValidationFailedError(
            "KPIs are computed for whole months: from the first day of a month to the last day "
            "of a month.",
            field_errors={"date_from": ["whole months"]},
        )
    if date_to > month_end(add_months(date_from, MAX_MONTHS - 1)):
        raise ValidationFailedError(
            "Choose at most 12 months.", field_errors={"date_to": ["at most 12 months"]}
        )


def _snapshot(ctx: WorkspaceContext, entity_id: UUID) -> dict[str, list[Any]]:
    mapping = current_mapping(entity_id)
    rows = []
    for a in accounts(ctx, entity_id):
        if not a.is_postable:
            continue
        line = mapping.get(a.id)
        rows.append(
            (
                a.id,
                line.code if line else "",
                line.section if line else "",
                a.normal_side == "CREDIT",
                a.type in ("INCOME", "EXPENSE"),
            )
        )
    return account_snapshot(rows)


def _unmapped(ctx: WorkspaceContext, entity_id: UUID, as_of: date) -> int:
    found = completeness(ctx, entity_id, as_of=as_of)
    return len(found.unmapped_blocking) + len(found.unmapped_warning)


def run(ctx: WorkspaceContext, entity_id: UUID, *, date_from: date, date_to: date) -> KpiSet:
    """Compute every KPI of the core library for the period, as a stored, reproducible run."""
    _period(date_from, date_to)
    entity = get_entity(ctx, entity_id, "planning.run")
    refs = {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "library": DEFAULT_LIBRARY,
        "accounts": _snapshot(ctx, entity.id),
    }
    made = execute(ctx, entity.id, KIND, as_of=date_to, refs=refs)
    return _set(ctx, entity.id, made)


def _set(ctx: WorkspaceContext, entity_id: UUID, made: CalcRun) -> KpiSet:
    found = {d.id: d for d in KpiDefinition.objects.filter(library=made.input_refs["library"])}
    as_of = date.fromisoformat(made.input_refs["date_to"])
    newer = posted_since(ctx, entity_id, made.actuals_watermark)
    return KpiSet(
        made, found, calc_results(made), _unmapped(ctx, entity_id, as_of), made.stale or newer
    )


def latest(ctx: WorkspaceContext, entity_id: UUID, *, date_from: date, date_to: date) -> KpiSet:
    """The latest finished KPI set for exactly this period."""
    _period(date_from, date_to)
    for candidate in list_calc_runs(ctx, entity_id, KIND, limit=200):
        refs = candidate.input_refs
        if (
            refs.get("date_from") == date_from.isoformat()
            and refs.get("date_to") == date_to.isoformat()
            and candidate.status != CalcRun.Status.RUNNING
        ):
            return _set(ctx, entity_id, candidate)
    raise NotFoundError("No KPI set for this period yet.")
