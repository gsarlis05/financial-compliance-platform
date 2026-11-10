"""Dashboard layouts: per user, with a workspace default per entity (M4-8)."""

import re
from typing import Any
from uuid import UUID

from django.db import transaction

from fcp.core.errors import ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import DashboardLayout
from .overview import DEFAULT_KPIS, WIDGETS

READ, MANAGE_DEFAULT = "planning.read", "dashboard.manage_default"
KPI_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")
MAX_KPIS = 8
BUILT_IN = [{"type": w, **({"kpis": list(DEFAULT_KPIS)} if w == "kpis" else {})} for w in WIDGETS]


def _invalid(message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={"widgets": [message]})


def clean(widgets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not widgets or len(widgets) > len(WIDGETS):
        raise _invalid(f"Choose 1 to {len(WIDGETS)} widgets.")
    seen, out = set(), []
    for w in widgets:
        kind = w.get("type")
        if kind not in WIDGETS or kind in seen:
            raise _invalid(f"Unknown or repeated widget {kind!r}.")
        seen.add(kind)
        item: dict[str, Any] = {"type": kind}
        if kind == "kpis":
            keys = w.get("kpis") or list(DEFAULT_KPIS)
            if (not isinstance(keys, list) or len(keys) > MAX_KPIS or len(set(keys)) != len(keys)
                    or not all(isinstance(k, str) and KPI_KEY.match(k) for k in keys)):  # fmt: skip
                raise _invalid(f"Choose up to {MAX_KPIS} different KPI keys.")
            item["kpis"] = keys
        out.append(item)
    return out


def layout(ctx: WorkspaceContext, entity_id: UUID) -> tuple[list[dict[str, Any]], str]:
    """The user's layout, else the entity default, else the built-in one; and which it is."""
    entity = get_entity(ctx, entity_id, READ)
    mine = DashboardLayout.objects.filter(legal_entity=entity, user=ctx.user).first()
    if mine is not None:
        return mine.widgets, "USER"
    default = DashboardLayout.objects.filter(legal_entity=entity, user__isnull=True).first()
    if default is not None:
        return default.widgets, "WORKSPACE"
    return BUILT_IN, "BUILT_IN"


@transaction.atomic
def save(ctx: WorkspaceContext, entity_id: UUID, widgets: list[dict[str, Any]], *,
         default: bool = False) -> list[dict[str, Any]]:  # fmt: skip
    entity = get_entity(ctx, entity_id, MANAGE_DEFAULT if default else READ)
    cleaned = clean(widgets)
    DashboardLayout.objects.update_or_create(
        legal_entity=entity, user=None if default else ctx.user,
        defaults={"tenant": ctx.tenant, "widgets": cleaned, "updated_by": ctx.user},
    )  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
          action="dashboards.layout.saved", subject_type="dashboard_layout",
          subject_id="default" if default else str(ctx.user.id), entity_id=entity.id,
          changes={"widgets": [w["type"] for w in cleaned]})  # fmt: skip
    return cleaned


@transaction.atomic
def reset(ctx: WorkspaceContext, entity_id: UUID) -> None:
    """Forget the user's own layout (back to the workspace default)."""
    entity = get_entity(ctx, entity_id, READ)
    DashboardLayout.objects.filter(legal_entity=entity, user=ctx.user).delete()
