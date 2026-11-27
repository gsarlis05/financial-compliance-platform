"""Corrections of the rules, per entity (brief 27, T-2, #255).

This module keeps the corrections and answers "which version applies on this day". The checks of
what a correction may say belong to the module that owns the rule: the ledger checks a VAT code's
correction, the tax module a box rule's, and this module a corporate tax rule set's. Each calls
``add`` once its own checks pass.

A correction is a version from ``effective_from``. It is never changed or deleted. A later
correction for the same rule replaces it from its own start, and one starting on the same day
supersedes it. A correction may not start before the latest one for the same rule, so the history
only moves forward.
"""

from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID

from fcp.core.errors import ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import RuleCorrection

PERMISSION = "tax.rules.correct"
Kind = RuleCorrection.Kind


@dataclass(frozen=True)
class Correction:
    id: UUID
    kind: str
    target: str
    effective_from: date
    values: dict[str, Any]
    source: str
    note: str
    created_at: str
    created_by: str

    def as_ref(self) -> dict[str, Any]:
        """What a VAT return or a run pins to say which correction it used."""
        return {"id": str(self.id), "kind": self.kind, "target": self.target,
                "effective_from": self.effective_from.isoformat(), "values": self.values,
                "source": self.source}  # fmt: skip


def _view(c: RuleCorrection) -> Correction:
    return Correction(c.id, c.kind, c.target, c.effective_from, dict(c.values), c.source, c.note,
                      c.created_at.isoformat(), getattr(c.created_by, "email", ""))  # fmt: skip


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def add(  # noqa: PLR0913 - keyword-only parts of a correction
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    kind: str,
    target: str,
    effective_from: date,
    values: dict[str, Any],
    source: str,
    note: str = "",
) -> Correction:
    """Record a correction checked by its owner module. Audited."""
    entity = get_entity(ctx, entity_id, PERMISSION)
    if not source.strip():
        raise _invalid("source", "Give the source of the correction (the law, the Tax "
                                 "Department's notice or your adviser's note).")  # fmt: skip
    if not values:
        raise _invalid("values", "The correction changes nothing.")
    latest = (RuleCorrection.objects.filter(legal_entity=entity, kind=kind, target=target)
              .order_by("-effective_from").first())  # fmt: skip
    if latest is not None and effective_from < latest.effective_from:
        raise _invalid("effective_from", f"A correction of {target} already applies from "
                                         f"{latest.effective_from:%d/%m/%Y}; a new one can start "
                                         "on that day or later.")  # fmt: skip
    found = RuleCorrection.objects.create(
        tenant=ctx.tenant, legal_entity=entity, kind=kind, target=target,
        effective_from=effective_from, values=values, source=source.strip()[:500],
        note=note.strip()[:1000], created_by=ctx.user,
    )  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="taxrules.corrected",
          subject_type="rule_correction", subject_id=found.id, entity_id=entity.id,
          changes={"kind": kind, "target": target,
                   "effective_from": effective_from.isoformat(), "values": values,
                   "source": found.source, "note": found.note,
                   "replaces": str(latest.id) if latest else None})  # fmt: skip
    return _view(found)


def history(ctx: WorkspaceContext, entity_id: UUID, kind: str | None = None) -> list[Correction]:
    """Every correction of the entity, the most recent first."""
    entity = get_entity(ctx, entity_id, "tenancy.workspace.read")
    rows = RuleCorrection.objects.filter(legal_entity=entity).select_related("created_by")
    if kind:
        rows = rows.filter(kind=kind)
    return [_view(c) for c in rows.order_by("-effective_from", "-created_at")]


def all_for(entity_id: UUID, kind: str) -> list[Correction]:
    """The entity's corrections of one kind, oldest first (engines; the caller is authorised)."""
    rows = RuleCorrection.objects.filter(legal_entity_id=entity_id, kind=kind)
    return [_view(c) for c in rows.order_by("effective_from", "created_at")]


def in_force(entity_id: UUID, kind: str, target: str, day: date) -> Correction | None:
    """The correction of ``target`` that applies on ``day``: the one with the latest start on
    or before that day (the last entered, for the same start)."""
    found = (RuleCorrection.objects.filter(legal_entity_id=entity_id, kind=kind, target=target,
                                           effective_from__lte=day)
             .order_by("-effective_from", "-created_at").first())  # fmt: skip
    return _view(found) if found else None


def latest_by_target(corrections: list[Correction], day: date) -> dict[str, Correction]:
    """From corrections oldest first: the one in force on ``day`` for each target."""
    found: dict[str, Correction] = {}
    for c in corrections:
        if c.effective_from <= day:
            found[c.target] = c
    return found
