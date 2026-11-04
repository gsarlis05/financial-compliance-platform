"""Public interface of the ``kpi`` module and its HTTP routes (M4-4: the core KPI library).

Every KPI value is ACTUAL, belongs to a stored calculation run, and names the definition version it
was computed with. Not-meaningful values have no number, only a reason (doc 10 §2.2, AC-KP2).
Drill-down: ``calc-runs/{run}/results/{result}/explain`` lists the reference calls and accounts.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .engine import KIND, reference_functions
from .models import KpiDefinition
from .services import KpiSet

__all__ = ["KIND", "KpiDefinition", "KpiSet", "reference_functions", "router"]

router = Router(tags=["kpi"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class KpiDefinitionOut(Schema):
    id: str = Field(description="Library version and key, e.g. CORE@1.0:DSO")
    key: str
    name: str
    name_el: str
    category: str
    formula: str
    display: str
    direction: str
    convention: str
    nm_note: str
    example: str


@router.get(f"{BASE}/kpi-definitions", response=list[KpiDefinitionOut])
@requires("planning.read")
def list_definitions(request: HttpRequest, slug: str, entity_id: UUID) -> list[KpiDefinition]:
    workspace_ctx(request, slug, entity_id)
    return services.definitions()


class KpiValueOut(Schema):
    result_id: UUID = Field(description="For calc-runs/{run}/results/{result}/explain")
    definition_id: str
    key: str
    name: str
    name_el: str
    category: str
    display: str
    direction: str
    convention: str
    nature: Literal["ACTUAL"] = "ACTUAL"
    value: str | None = Field(description="Unrounded (up to 20 places); None if not meaningful")
    unit: str
    nm_reason: str


class KpiSetOut(Schema):
    run_id: UUID
    status: str
    stale: bool = Field(description="Entries were posted after this set was calculated")
    library: str
    date_from: date
    date_to: date
    actuals_watermark: int
    created_at: datetime
    unmapped_accounts: int = Field(description="Accounts with activity but no taxonomy line")
    values: list[KpiValueOut]


def _out(kpis: KpiSet) -> KpiSetOut:
    run = kpis.run
    library = run.input_refs["library"]
    values = []
    for r in kpis.values:
        definition = kpis.definitions.get(f"{library}:{r.series_key.removeprefix('kpi.')}")
        if definition is None:  # pragma: no cover (library versions are never edited)
            continue
        values.append(
            KpiValueOut(
                result_id=r.id,
                definition_id=definition.id,
                key=definition.key,
                name=definition.name,
                name_el=definition.name_el,
                category=definition.category,
                display=definition.display,
                direction=definition.direction,
                convention=definition.convention,
                value=None if r.value is None else format(r.value.normalize(), "f"),
                unit=r.unit,
                nm_reason=r.nm_reason,
            )
        )
    return KpiSetOut(
        run_id=run.id,
        status=run.status,
        stale=kpis.out_of_date,
        library=library,
        date_from=date.fromisoformat(run.input_refs["date_from"]),
        date_to=date.fromisoformat(run.input_refs["date_to"]),
        actuals_watermark=run.actuals_watermark,
        created_at=run.created_at,
        unmapped_accounts=kpis.unmapped_accounts,
        values=values,
    )


class PeriodIn(Schema):
    date_from: date = Field(description="First day of a month")
    date_to: date = Field(description="Last day of a month; at most 12 months")


@router.post(f"{BASE}/kpi-sets", response={201: KpiSetOut})
@requires("planning.run")
def run_kpis(
    request: HttpRequest, slug: str, entity_id: UUID, payload: PeriodIn
) -> Status[KpiSetOut]:
    """Compute the core KPIs for a period, as a stored and reproducible calculation run."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(
        201,
        _out(services.run(ctx, entity_id, date_from=payload.date_from, date_to=payload.date_to)),
    )


@router.get(f"{BASE}/kpi-sets/latest", response=KpiSetOut)
@requires("planning.read")
def latest_kpis(request: HttpRequest, slug: str, entity_id: UUID, q: Query[PeriodIn]) -> KpiSetOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.latest(ctx, entity_id, date_from=q.date_from, date_to=q.date_to))
