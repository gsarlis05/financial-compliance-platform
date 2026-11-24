"""Dashboard layouts: per user, with a workspace default per entity (M4-8)."""

import re
from typing import Any
from uuid import UUID

from django.db import transaction

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import DashboardLayout, SavedView
from .overview import BUILT_IN_WIDGETS, DEFAULT_KPIS, WIDGETS

READ, MANAGE_DEFAULT = "planning.read", "dashboard.manage_default"
KPI_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,39}$")
UUID_TEXT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MAX_KPIS = 8
BUILT_IN = [{"type": w, **({"kpis": list(DEFAULT_KPIS)} if w == "kpis" else {})}
            for w in WIDGETS if w in BUILT_IN_WIDGETS]  # fmt: skip


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
        if kind == "scenario":
            scenario = str(w.get("scenario_id") or "")
            if not UUID_TEXT.match(scenario):
                raise _invalid("Choose the shared scenario this widget compares with its base.")
            item["scenario_id"] = scenario
        width = w.get("width", "full")
        if width not in ("full", "half"):
            raise _invalid("A widget is full or half width.")
        if width == "half":
            item["width"] = "half"  # full width is the default and is not stored
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


# --- saved views (M8-4) ---------------------------------------------------------------------------

MAX_VIEWS = 20


def views(ctx: WorkspaceContext, entity_id: UUID) -> list[SavedView]:
    entity = get_entity(ctx, entity_id, READ)
    return list(SavedView.objects.filter(legal_entity=entity, user=ctx.user).order_by("name"))


@transaction.atomic
def save_view(ctx: WorkspaceContext, entity_id: UUID, *, name: str, preset: str,
              comparison: str) -> SavedView:  # fmt: skip
    """Save (or replace, by name) one of your views: a period preset and a comparison."""
    entity = get_entity(ctx, entity_id, READ)
    name = name.strip()
    mine = SavedView.objects.filter(legal_entity=entity, user=ctx.user)
    if not mine.filter(name=name).exists() and mine.count() >= MAX_VIEWS:
        raise ValidationFailedError(f"Keep at most {MAX_VIEWS} views; delete one first.",
                                    field_errors={"name": ["Too many views."]})  # fmt: skip
    view, _ = SavedView.objects.update_or_create(
        legal_entity=entity, user=ctx.user, name=name,
        defaults={"tenant": ctx.tenant, "preset": preset, "comparison": comparison},
    )  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="dashboards.view.saved",
          subject_type="dashboard_view", subject_id=view.id, entity_id=entity.id,
          changes={"name": name, "preset": preset, "comparison": comparison})  # fmt: skip
    return view


@transaction.atomic
def delete_view(ctx: WorkspaceContext, entity_id: UUID, view_id: UUID) -> None:
    entity = get_entity(ctx, entity_id, READ)
    view = SavedView.objects.filter(legal_entity=entity, user=ctx.user, id=view_id).first()
    if view is None:
        raise NotFoundError("View not found.")
    view.delete()
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="dashboards.view.deleted",
          subject_type="dashboard_view", subject_id=view_id, entity_id=entity.id,
          changes={"name": view.name})  # fmt: skip
