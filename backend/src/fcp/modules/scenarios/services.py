"""Scenarios and their overrides (M7-1, brief 21 §3).

- **Visibility:** a draft is visible only to its author; shared and archived scenarios to everyone
  who can read plans of the entity (``planning.read``). An invisible scenario is "not found".
- **Changes** need ``planning.run`` and are made by the author while the scenario is a draft:
  rename, add, change, reorder or remove overrides, then share or archive it. A shared scenario
  never changes; it is archived by its author or by someone with ``planning.publish``.
- **Copy** makes a new draft of any visible scenario for the person copying it, optionally on
  another approved base (a "rebase"): every override is checked again against the new base.
- The base is an approved assumption set of the same entity; a scenario never changes it.
Every change is audited.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from fcp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from fcp.modules.audit_log.api import record as audit
from fcp.modules.projections.api import OPEX_LINES, REVENUE_LINES, SetInfo, set_info
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Scenario, ScenarioOverride
from .overrides import MAX_OVERRIDES, Base, clean

READ, RUN, PUBLISH = "planning.read", "planning.run", "planning.publish"
Status = Scenario.Status


def audit_scenario(ctx: WorkspaceContext, action: str, s: Scenario, **changes: object) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=f"scenarios.{action}",
        subject_type="scenario",
        subject_id=s.id,
        entity_id=s.legal_entity_id,
        changes={"name": s.name, **changes},
    )


def base_of(info: SetInfo) -> Base:
    return Base(months=info.months, loan_codes=info.loan_codes,
                revenue_lines=REVENUE_LINES, opex_lines=OPEX_LINES)  # fmt: skip


def _approved_base(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> SetInfo:
    try:
        info = set_info(ctx, entity_id, set_id)
    except NotFoundError:
        raise ValidationFailedError(
            "base_set_id: no such assumption set for this entity.",
            field_errors={"base_set_id": ["No such assumption set for this entity."]},
        ) from None
    if info.status != "APPROVED":
        message = ("Base a scenario on an approved assumption set "
                   f"(this one is {info.status.lower()}).")  # fmt: skip
        raise ValidationFailedError(message, field_errors={"base_set_id": [message]})
    return info


def _visible(ctx: WorkspaceContext, entity: UUID) -> Q:
    return Q(legal_entity_id=entity) & (~Q(status=Status.DRAFT) | Q(created_by_id=ctx.user.id))


def scenarios(ctx: WorkspaceContext, entity_id: UUID) -> list[Scenario]:
    entity = get_entity(ctx, entity_id, READ).id
    return list(Scenario.objects.filter(_visible(ctx, entity)).order_by("-created_at"))


def get(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID,
        permission: str = READ) -> Scenario:  # fmt: skip
    entity = get_entity(ctx, entity_id, permission).id
    found = Scenario.objects.filter(_visible(ctx, entity), id=scenario_id).first()
    if found is None:
        raise NotFoundError("Scenario not found.")
    return found


def overrides(s: Scenario) -> list[ScenarioOverride]:
    return list(ScenarioOverride.objects.filter(scenario=s).order_by("seq"))


@dataclass(frozen=True)
class Detail:
    scenario: Scenario
    base: SetInfo
    overrides: list[ScenarioOverride]


def detail(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> Detail:
    s = get(ctx, entity_id, scenario_id)
    return Detail(s, set_info(ctx, entity_id, s.base_set_id), overrides(s))


def _draft(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> Scenario:
    """A draft of the current user, locked for a change."""
    s = get(ctx, entity_id, scenario_id, RUN)
    locked = Scenario.objects.select_for_update().get(id=s.id)
    if locked.status != Status.DRAFT:
        raise ConflictError("This scenario is shared or archived and never changes. "
                            "Copy it to change it.")  # fmt: skip
    return locked


def create(ctx: WorkspaceContext, entity_id: UUID, *, name: str, base_set_id: UUID,
           description: str = "") -> Scenario:  # fmt: skip
    entity = get_entity(ctx, entity_id, RUN).id
    _approved_base(ctx, entity_id, base_set_id)
    made = Scenario.objects.create(tenant=ctx.tenant, legal_entity_id=entity, name=name.strip(),
                                   base_set_id=base_set_id, description=description.strip(),
                                   created_by=ctx.user)  # fmt: skip
    audit_scenario(ctx, "created", made, base_set_id=str(base_set_id))
    return made


@transaction.atomic
def rename(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID, *, name: str,
           description: str) -> Scenario:  # fmt: skip
    s = _draft(ctx, entity_id, scenario_id)
    s.name, s.description = name.strip(), description.strip()
    s.save(update_fields=["name", "description"])
    audit_scenario(ctx, "renamed", s, description=s.description)
    return s


def _cleaned(ctx: WorkspaceContext, entity_id: UUID, s: Scenario, kind: str,
             params: object) -> dict[str, Any]:  # fmt: skip
    return clean(kind, params, base_of(set_info(ctx, entity_id, s.base_set_id)))


@transaction.atomic
def add_override(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID, *, kind: str,
                 params: object, rationale: str = "") -> ScenarioOverride:  # fmt: skip
    s = _draft(ctx, entity_id, scenario_id)
    count = ScenarioOverride.objects.filter(scenario=s).count()
    if count >= MAX_OVERRIDES:
        raise ConflictError(f"A scenario has at most {MAX_OVERRIDES} overrides.")
    cleaned = _cleaned(ctx, entity_id, s, kind, params)
    last = ScenarioOverride.objects.filter(scenario=s).aggregate(m=Max("seq"))["m"] or 0
    made = ScenarioOverride.objects.create(tenant=ctx.tenant, scenario=s, seq=last + 1,
                                           type=kind, params=cleaned,
                                           rationale=rationale.strip())  # fmt: skip
    audit_scenario(ctx, "override_added", s, override_id=str(made.id), type=kind, params=cleaned)
    return made


def _override(s: Scenario, override_id: UUID) -> ScenarioOverride:
    found = ScenarioOverride.objects.filter(scenario=s, id=override_id).first()
    if found is None:
        raise NotFoundError("Override not found.")
    return found


@transaction.atomic
def change_override(  # noqa: PLR0913 (keyword-only details of the override)
    ctx: WorkspaceContext,
    entity_id: UUID,
    scenario_id: UUID,
    override_id: UUID,
    *,
    kind: str,
    params: object,
    rationale: str = "",
) -> ScenarioOverride:
    s = _draft(ctx, entity_id, scenario_id)
    o = _override(s, override_id)
    o.type, o.params, o.rationale = (
        kind,
        _cleaned(ctx, entity_id, s, kind, params),
        rationale.strip(),
    )
    o.save(update_fields=["type", "params", "rationale"])
    audit_scenario(ctx, "override_changed", s, override_id=str(o.id), type=kind, params=o.params)
    return o


@transaction.atomic
def remove_override(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID,
                    override_id: UUID) -> None:  # fmt: skip
    s = _draft(ctx, entity_id, scenario_id)
    o = _override(s, override_id)
    removed = {"override_id": str(o.id), "type": o.type, "params": o.params}
    o.delete()
    _resequence(s, [x.id for x in overrides(s)])
    audit_scenario(ctx, "override_removed", s, **removed)


def _resequence(s: Scenario, order: list[UUID]) -> None:
    by_id = {o.id: o for o in overrides(s)}
    for seq, override_id in enumerate(order, start=1):
        o = by_id[override_id]
        if o.seq != seq:  # the (scenario, seq) key is checked at commit
            o.seq = seq
            o.save(update_fields=["seq"])


@transaction.atomic
def reorder(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID,
            order: list[UUID]) -> list[ScenarioOverride]:  # fmt: skip
    s = _draft(ctx, entity_id, scenario_id)
    current = {o.id for o in overrides(s)}
    if len(order) != len(set(order)) or set(order) != current:
        message = "List every override of the scenario once, in the new order."
        raise ValidationFailedError(message, field_errors={"order": [message]})
    _resequence(s, order)
    audit_scenario(ctx, "reordered", s, order=[str(x) for x in order])
    return overrides(s)


@transaction.atomic
def share(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> Scenario:
    s = _draft(ctx, entity_id, scenario_id)
    s.status, s.shared_at = Status.SHARED, timezone.now()
    s.save(update_fields=["status", "shared_at"])
    audit_scenario(ctx, "shared", s, overrides=ScenarioOverride.objects.filter(scenario=s).count())
    return s


@transaction.atomic
def archive(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> Scenario:
    s = get(ctx, entity_id, scenario_id, RUN)
    locked = Scenario.objects.select_for_update().get(id=s.id)
    if locked.status == Status.ARCHIVED:
        raise ConflictError("This scenario is already archived.")
    if locked.created_by_id != ctx.user.id and not ctx.can(PUBLISH, locked.legal_entity_id):
        raise PermissionDeniedError("Only the scenario's author, or someone who can publish "
                                    "plans, can archive it.")  # fmt: skip
    locked.status, locked.archived_at = Status.ARCHIVED, timezone.now()
    locked.save(update_fields=["status", "archived_at"])
    audit_scenario(ctx, "archived", locked)
    return locked


@transaction.atomic
def copy(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID, *, name: str | None = None,
         base_set_id: UUID | None = None) -> Scenario:  # fmt: skip
    """A new draft for the current user with the same overrides, optionally on another approved
    base; every override is checked again against the new base."""
    source = get(ctx, entity_id, scenario_id, RUN)
    base_id = base_set_id or source.base_set_id
    base = base_of(_approved_base(ctx, entity_id, base_id)) if base_set_id else base_of(
        set_info(ctx, entity_id, base_id))  # fmt: skip
    made = Scenario.objects.create(
        tenant=ctx.tenant, legal_entity_id=source.legal_entity_id, base_set_id=base_id,
        name=(name or f"Copy of {source.name}")[:120].strip(), description=source.description,
        copied_from=source, created_by=ctx.user,
    )  # fmt: skip
    for o in overrides(source):
        try:
            params = clean(o.type, o.params, base)
        except ValidationFailedError as problem:
            message = f"Override {o.seq} ({o.type}) does not fit the new base: {problem}"
            raise ValidationFailedError(message, field_errors={"base_set_id": [message]}) from None
        ScenarioOverride.objects.create(tenant=ctx.tenant, scenario=made, seq=o.seq, type=o.type,
                                        params=params, rationale=o.rationale)  # fmt: skip
    audit_scenario(ctx, "copied", made, copied_from=str(source.id), base_set_id=str(base_id))
    return made
