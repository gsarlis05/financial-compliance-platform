"""Public interface of the ``tenancy`` module: services for other modules and the HTTP router.

Workspace-scoped routes take the workspace from the URL path (``/api/w/{slug}/...``), never
from the request body (doc 04 §4 L1).
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Router, Schema

from fcp.core.api.permissions import AUTHENTICATED, requires
from fcp.modules.identity.api import User

from . import services
from .entitlements import Feature, Role, has_feature
from .models import LegalEntity, Tenant
from .services import WorkspaceContext, enter_workspace

__all__ = ["Feature", "Role", "WorkspaceContext", "enter_workspace", "router"]

router = Router(tags=["workspaces"])


def _user(request: HttpRequest) -> User:
    return cast(User, request.user)


class WorkspaceIn(Schema):
    name: str = Field(min_length=1, max_length=200)
    kind: Tenant.Kind
    entity_name: str | None = Field(default=None, max_length=200)
    entity_type: LegalEntity.EntityType | None = None


class WorkspaceOut(Schema):
    id: UUID
    slug: str
    name: str
    kind: str
    roles: list[str] = []


class EntityIn(Schema):
    legal_name: str = Field(min_length=1, max_length=200)
    entity_type: LegalEntity.EntityType
    registration_no: str = Field(default="", max_length=64)


class EntityOut(Schema):
    id: UUID
    legal_name: str
    entity_type: str
    registration_no: str
    jurisdiction: str
    functional_currency: str
    status: str


class InvitationIn(Schema):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role_key: Role
    legal_entity_id: UUID | None = None


class InvitationOut(Schema):
    id: UUID
    email: str
    role_key: str
    expires_at: datetime
    token: str = Field(description="Shown once. Send it to the invitee; only a hash is stored.")


class AcceptIn(Schema):
    token: str = Field(min_length=10, max_length=200)


def _workspace_out(ctx: WorkspaceContext) -> WorkspaceOut:
    t = ctx.tenant
    return WorkspaceOut(id=t.id, slug=t.slug, name=t.name, kind=t.kind, roles=sorted(ctx.roles))


@router.post("/workspaces", response={201: WorkspaceOut})
@requires(AUTHENTICATED)
def create_workspace(request: HttpRequest, payload: WorkspaceIn) -> tuple[int, WorkspaceOut]:
    ctx = services.create_workspace(
        _user(request),
        name=payload.name,
        kind=payload.kind,
        entity_name=payload.entity_name,
        entity_type=payload.entity_type,
    )
    return 201, _workspace_out(ctx)


@router.get("/workspaces", response=list[WorkspaceOut])
@requires(AUTHENTICATED)
def list_workspaces(request: HttpRequest) -> list[WorkspaceOut]:
    return [
        WorkspaceOut(id=t.id, slug=t.slug, name=t.name, kind=t.kind)
        for t in services.list_workspaces(_user(request))
    ]


@router.get("/w/{slug}", response=WorkspaceOut)
@requires("tenancy.workspace.read")
def get_workspace(request: HttpRequest, slug: str) -> WorkspaceOut:
    return _workspace_out(enter_workspace(_user(request), slug))


@router.get("/w/{slug}/entities", response=list[EntityOut])
@requires("tenancy.workspace.read")
def list_entities(request: HttpRequest, slug: str) -> list[LegalEntity]:
    return services.list_entities(enter_workspace(_user(request), slug))


@router.post("/w/{slug}/entities", response={201: EntityOut})
@requires("tenancy.entity.manage")
def create_entity(request: HttpRequest, slug: str, payload: EntityIn) -> tuple[int, LegalEntity]:
    ctx = enter_workspace(_user(request), slug)
    entity = services.create_entity(
        ctx,
        legal_name=payload.legal_name,
        entity_type=payload.entity_type,
        registration_no=payload.registration_no,
    )
    return 201, entity


@router.get("/w/{slug}/entities/{entity_id}", response=EntityOut)
@requires("tenancy.workspace.read")
def get_entity(request: HttpRequest, slug: str, entity_id: UUID) -> LegalEntity:
    return services.get_entity(enter_workspace(_user(request), slug), entity_id)


@router.post("/w/{slug}/invitations", response={201: InvitationOut})
@requires("tenancy.members.manage")
def invite(request: HttpRequest, slug: str, payload: InvitationIn) -> tuple[int, InvitationOut]:
    ctx = enter_workspace(_user(request), slug)
    issued = services.invite_member(
        ctx, email=payload.email, role_key=payload.role_key, legal_entity_id=payload.legal_entity_id
    )
    inv = issued.invitation
    return 201, InvitationOut(
        id=inv.id, email=inv.email, role_key=inv.role_key, expires_at=inv.expires_at,
        token=issued.token,
    )  # fmt: skip


@router.post("/invitations/accept", response=WorkspaceOut)
@requires(AUTHENTICATED)
def accept(request: HttpRequest, payload: AcceptIn) -> WorkspaceOut:
    return _workspace_out(services.accept_invitation(_user(request), payload.token))


@router.get("/w/{slug}/features", response=dict[str, bool])
@requires("tenancy.workspace.read")
def features(request: HttpRequest, slug: str) -> dict[str, bool]:
    ctx = enter_workspace(_user(request), slug)
    return {f.value: has_feature(ctx.tenant.kind, f) for f in Feature}
