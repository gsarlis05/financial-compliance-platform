"""Public interface of the ``scenarios`` module and its HTTP routes (M7-1: scenarios and their
typed overrides).

Routes are entity-scoped (``/api/w/{slug}/entities/{entity_id}/scenarios``). Reading needs
``planning.read``; changes need ``planning.run`` (archiving someone else's shared scenario also
``planning.publish``). Every figure a scenario produces is ``HYPOTHETICAL`` (runs: M7-2).
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import Scenario, ScenarioOverride
from .overrides import MAX_OVERRIDES

__all__ = ["OverrideType", "router"]

router = Router(tags=["scenarios"])
BASE = "/w/{slug}/entities/{uuid:entity_id}/scenarios"
OverrideType = Literal[
    "PCT_CHANGE", "ABS_CHANGE", "TIMING_SHIFT", "NEW_DEBT",
    "NEW_HIRE", "CAPEX", "ONE_OFF", "RATE_CHANGE",
]  # fmt: skip


class ScenarioIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    base_set_id: UUID = Field(description="An approved assumption set of the entity")
    description: str = Field(default="", max_length=1000)


class ScenarioRenameIn(Schema):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class ScenarioCopyIn(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    base_set_id: UUID | None = Field(
        default=None, description="Another approved assumption set (rebase); default: the same"
    )


class ScenarioOverrideIn(Schema):
    type: OverrideType
    params: dict[str, Any] = Field(description="Parameters of the type (see the user guide)")
    rationale: str = Field(default="", max_length=1000)


class ScenarioOverrideOrderIn(Schema):
    order: list[UUID] = Field(min_length=1, max_length=MAX_OVERRIDES)


class ScenarioOverrideOut(Schema):
    id: UUID
    seq: int = Field(description="The order in which the override applies (1 first)")
    type: str
    params: dict[str, Any]
    rationale: str


class ScenarioOut(Schema):
    id: UUID
    name: str
    description: str
    status: str = Field(description="DRAFT, SHARED or ARCHIVED")
    base_set_id: UUID
    copied_from_id: UUID | None
    created_by_id: UUID
    created_at: datetime
    shared_at: datetime | None
    archived_at: datetime | None
    nature: str = Field(default="HYPOTHETICAL", description="Every scenario figure is hypothetical")


class ScenarioBaseOut(Schema):
    id: UUID
    name: str
    version: int
    status: str = Field(description="APPROVED, or SUPERSEDED when a newer version is approved")
    newer_version_approved: bool
    first_month: date
    last_month: date
    loans: list[str]


class ScenarioDetailOut(Schema):
    scenario: ScenarioOut
    base: ScenarioBaseOut
    overrides: list[ScenarioOverrideOut]


def _out(s: Scenario) -> ScenarioOut:
    return ScenarioOut(
        id=s.id, name=s.name, description=s.description, status=s.status,
        base_set_id=s.base_set_id, copied_from_id=s.copied_from_id, created_by_id=s.created_by_id,
        created_at=s.created_at, shared_at=s.shared_at, archived_at=s.archived_at,
    )  # fmt: skip


def _override_out(o: ScenarioOverride) -> ScenarioOverrideOut:
    return ScenarioOverrideOut(
        id=o.id, seq=o.seq, type=o.type, params=o.params, rationale=o.rationale
    )


def _detail_out(d: services.Detail) -> ScenarioDetailOut:
    b = d.base
    return ScenarioDetailOut(
        scenario=_out(d.scenario),
        base=ScenarioBaseOut(
            id=b.id, name=b.name, version=b.version, status=b.status,
            newer_version_approved=b.status == "SUPERSEDED", first_month=b.months[0],
            last_month=b.months[-1], loans=sorted(b.loan_codes),
        ),
        overrides=[_override_out(o) for o in d.overrides],
    )  # fmt: skip


@router.get(BASE, response=list[ScenarioOut])
@requires("planning.read")
def list_scenarios(request: HttpRequest, slug: str, entity_id: UUID) -> list[ScenarioOut]:
    """Your drafts, and every shared or archived scenario of the entity."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_out(s) for s in services.scenarios(ctx, entity_id)]


@router.post(BASE, response={201: ScenarioOut})
@requires("planning.run")
def create_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                    payload: ScenarioIn) -> Status[ScenarioOut]:  # fmt: skip
    """Start a draft scenario on an approved assumption set."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _out(services.create(ctx, entity_id, **payload.dict())))


@router.get(f"{BASE}/{{uuid:scenario_id}}", response=ScenarioDetailOut)
@requires("planning.read")
def get_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                 scenario_id: UUID) -> ScenarioDetailOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail_out(services.detail(ctx, entity_id, scenario_id))


@router.patch(f"{BASE}/{{uuid:scenario_id}}", response=ScenarioOut)
@requires("planning.run")
def rename_scenario(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                    payload: ScenarioRenameIn) -> ScenarioOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.rename(ctx, entity_id, scenario_id, **payload.dict()))


@router.post(f"{BASE}/{{uuid:scenario_id}}/overrides", response={201: ScenarioOverrideOut})
@requires("planning.run")
def add_override(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                 payload: ScenarioOverrideIn) -> Status[ScenarioOverrideOut]:  # fmt: skip
    """Add an override at the end of the list (it applies after the others)."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.add_override(ctx, entity_id, scenario_id, kind=payload.type,
                                 params=payload.params, rationale=payload.rationale)  # fmt: skip
    return Status(201, _override_out(made))


@router.put(
    f"{BASE}/{{uuid:scenario_id}}/overrides/{{uuid:override_id}}", response=ScenarioOverrideOut
)
@requires("planning.run")
def change_override(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                    override_id: UUID,
                    payload: ScenarioOverrideIn) -> ScenarioOverrideOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _override_out(services.change_override(
        ctx, entity_id, scenario_id, override_id, kind=payload.type, params=payload.params,
        rationale=payload.rationale))  # fmt: skip


@router.delete(f"{BASE}/{{uuid:scenario_id}}/overrides/{{uuid:override_id}}",
               response={204: None})  # fmt: skip
@requires("planning.run")
def remove_override(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                    override_id: UUID) -> Status[None]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    services.remove_override(ctx, entity_id, scenario_id, override_id)
    return Status(204, None)


@router.put(f"{BASE}/{{uuid:scenario_id}}/overrides", response=list[ScenarioOverrideOut])
@requires("planning.run")
def reorder_overrides(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                      payload: ScenarioOverrideOrderIn) -> list[ScenarioOverrideOut]:  # fmt: skip
    """Put the overrides in a new order: list every override's id once."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_override_out(o) for o in services.reorder(ctx, entity_id, scenario_id,
                                                       payload.order)]  # fmt: skip


@router.post(f"{BASE}/{{uuid:scenario_id}}/share", response=ScenarioOut)
@requires("planning.run")
def share_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                   scenario_id: UUID) -> ScenarioOut:  # fmt: skip
    """Make a draft visible to everyone who can read plans; it then never changes."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.share(ctx, entity_id, scenario_id))


@router.post(f"{BASE}/{{uuid:scenario_id}}/archive", response=ScenarioOut)
@requires("planning.run")
def archive_scenario(request: HttpRequest, slug: str, entity_id: UUID,
                     scenario_id: UUID) -> ScenarioOut:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.archive(ctx, entity_id, scenario_id))


@router.post(f"{BASE}/{{uuid:scenario_id}}/copy", response={201: ScenarioOut})
@requires("planning.run")
def copy_scenario(request: HttpRequest, slug: str, entity_id: UUID, scenario_id: UUID,
                  payload: ScenarioCopyIn) -> Status[ScenarioOut]:  # fmt: skip
    """A new draft with the same overrides, optionally on another approved base."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = services.copy(ctx, entity_id, scenario_id, name=payload.name,
                         base_set_id=payload.base_set_id)  # fmt: skip
    return Status(201, _out(made))
