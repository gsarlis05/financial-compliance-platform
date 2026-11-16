"""Public interface of the ``projections`` module and its HTTP routes (M6-2: assumption sets).

Routes are entity-scoped (``/api/w/{slug}/entities/{entity_id}/...``). Values are decimal strings:
amounts in money, percentages as e.g. ``35`` for 35%, days and months as numbers.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import assumptions
from .drivers import DRIVERS
from .models import AssumptionSet

__all__ = ["router"]

router = Router(tags=["projections"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class AssumptionSetIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    cutover: date = Field(description="The last day of the last actual month")
    months: Literal[12, 24, 36] = 24
    start_from: Literal["ACTUALS", "BUDGET", "EMPTY"] = "ACTUALS"
    revenue_growth: str = Field(
        default="0", pattern=r"^-?\d{1,4}(\.\d{1,4})?$", description="% a year (actuals start)"
    )


class AssumptionSetOut(Schema):
    id: UUID
    family_id: UUID
    version: int
    name: str
    cutover: date
    months: int
    start_from: str
    note: str
    status: str = Field(description="DRAFT, APPROVED or SUPERSEDED")
    supersedes_id: UUID | None
    created_at: datetime
    approved_at: datetime | None


def _set_out(s: AssumptionSet) -> AssumptionSetOut:
    return AssumptionSetOut(
        id=s.id, family_id=s.family_id, version=s.version, name=s.name, cutover=s.cutover,
        months=s.months, start_from=s.start_from, note=s.note, status=s.status,
        supersedes_id=s.supersedes_id, created_at=s.created_at, approved_at=s.approved_at,
    )  # fmt: skip


class GridRowOut(Schema):
    driver: str
    line: str = Field(description="Taxonomy line, or empty for a single row")
    unit: str = Field(description="AMOUNT, PERCENT, DAYS or MONTHS")
    values: list[str]
    sources: list[str] = Field(description="ACTUALS, BUDGET, DEFAULT or MANUAL per month")


class GridOut(Schema):
    assumption_set: AssumptionSetOut
    months: list[date]
    rows: list[GridRowOut]
    nature: str = Field(default="FORECAST", description="Every value is a forecast assumption")


class ChangeIn(Schema):
    driver: str = Field(max_length=20)
    line: str = Field(default="", max_length=40)
    month: date
    value: str = Field(pattern=r"^-?\d{1,13}(\.\d{1,6})?$")


class ChangesIn(Schema):
    changes: list[ChangeIn] = Field(min_length=1, max_length=2000)


class RenameIn(Schema):
    name: str = Field(min_length=1, max_length=120)


@router.get(f"{BASE}/assumption-sets", response=list[AssumptionSetOut])
@requires("planning.read")
def list_sets(request: HttpRequest, slug: str, entity_id: UUID) -> list[AssumptionSetOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_set_out(s) for s in assumptions.sets(ctx, entity_id)]


@router.post(f"{BASE}/assumption-sets", response={201: AssumptionSetOut})
@requires("planning.run")
def create_set(request: HttpRequest, slug: str, entity_id: UUID,
               payload: AssumptionSetIn) -> Status[AssumptionSetOut]:  # fmt: skip
    """Start a draft set from last year's actuals, the approved budget, or empty."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = assumptions.create_set(ctx, entity_id, assumptions.NewSet(**payload.dict()))
    return Status(201, _set_out(made))


def _grid_out(g: assumptions.Grid) -> GridOut:
    return GridOut(
        assumption_set=_set_out(g.assumption_set), months=g.months,
        rows=[GridRowOut(driver=k, line=line, unit=unit, values=[f"{v.normalize():f}"
                                                                 for v in vals],
                         sources=srcs) for k, line, unit, vals, srcs in g.rows],
    )  # fmt: skip


@router.get(f"{BASE}/assumption-sets/{{uuid:set_id}}", response=GridOut)
@requires("planning.read")
def get_set(request: HttpRequest, slug: str, entity_id: UUID, set_id: UUID) -> GridOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _grid_out(assumptions.grid(ctx, entity_id, set_id))


@router.put(f"{BASE}/assumption-sets/{{uuid:set_id}}/values", response=GridOut)
@requires("planning.run")
def set_values(request: HttpRequest, slug: str, entity_id: UUID, set_id: UUID,
               payload: ChangesIn) -> GridOut:  # fmt: skip
    """Change values of a draft set (each becomes MANUAL)."""
    ctx = workspace_ctx(request, slug, entity_id)
    assumptions.set_values(ctx, entity_id, set_id, [
        assumptions.Change(c.driver, c.line, c.month, c.value) for c in payload.changes
    ])  # fmt: skip
    return _grid_out(assumptions.grid(ctx, entity_id, set_id))


@router.patch(f"{BASE}/assumption-sets/{{uuid:set_id}}", response=AssumptionSetOut)
@requires("planning.run")
def rename_set(request: HttpRequest, slug: str, entity_id: UUID, set_id: UUID,
               payload: RenameIn) -> AssumptionSetOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _set_out(assumptions.rename(ctx, entity_id, set_id, payload.name))


@router.post(f"{BASE}/assumption-sets/{{uuid:set_id}}/approve", response=AssumptionSetOut)
@requires("planning.publish")
def approve_set(request: HttpRequest, slug: str, entity_id: UUID,
                set_id: UUID) -> AssumptionSetOut:  # fmt: skip
    """Approve a draft: it never changes again; the family's earlier approved version is
    superseded."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _set_out(assumptions.approve(ctx, entity_id, set_id))


@router.post(f"{BASE}/assumption-sets/{{uuid:set_id}}/revise", response={201: AssumptionSetOut})
@requires("planning.run")
def revise_set(request: HttpRequest, slug: str, entity_id: UUID,
               set_id: UUID) -> Status[AssumptionSetOut]:  # fmt: skip
    """A new draft version with the same values."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _set_out(assumptions.revise(ctx, entity_id, set_id)))


class DriverOut(Schema):
    key: str
    unit: str
    lines: list[str]


@router.get(f"{BASE}/assumption-drivers", response=list[DriverOut])
@requires("planning.read")
def list_drivers(request: HttpRequest, slug: str, entity_id: UUID) -> list[DriverOut]:
    workspace_ctx(request, slug, entity_id)
    return [DriverOut(key=d.key, unit=d.unit, lines=list(d.lines)) for d in DRIVERS.values()]
