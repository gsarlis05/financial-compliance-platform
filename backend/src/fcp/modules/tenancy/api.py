"""Public interface of the ``tenancy`` module: services for other modules and the HTTP router.

Workspace-scoped routes take the workspace from the URL path (``/api/w/{slug}/...``), never
from the request body (doc 04 §4 L1).
"""

from datetime import datetime
from typing import cast
from uuid import UUID

from django.db import connection
from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from fcp.core.api.permissions import AUTHENTICATED, required_permission, requires
from fcp.core.errors import PermissionDeniedError
from fcp.modules.identity.api import User, require_recent_auth

from . import services
from .entitlements import Feature, Role, has_feature
from .models import LegalEntity, Tenant
from .services import WorkspaceContext, enter_workspace, get_entity

__all__ = [
    "Feature",
    "Role",
    "Tenant",
    "WorkspaceContext",
    "all_tenant_ids",
    "enter_workspace",
    "get_entity",
    "router",
    "workspace_ctx",
]


def all_tenant_ids() -> list[UUID]:
    """IDs of all active workspaces, for platform jobs only (see migration 0003)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT app_tenant_ids()")
        return [row[0] for row in cursor.fetchall()]


router = Router(tags=["workspaces"])


def _user(request: HttpRequest) -> User:
    return cast(User, request.user)


def workspace_ctx(
    request: HttpRequest, slug: str, entity_id: UUID | None = None
) -> WorkspaceContext:
    """Enter the workspace in the URL and enforce the operation's declared permission.

    Every workspace-scoped operation in every module calls this first; the permission is the one
    declared with ``@requires``, so declaration and enforcement cannot diverge.
    """
    permission = required_permission(request)
    if permission is None:
        raise PermissionDeniedError("This operation declares no permission.")
    ctx = enter_workspace(_user(request), slug)
    ctx.authorize(permission, entity_id)
    return ctx


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
    roles: list[str] = Field(default_factory=list)


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
def create_workspace(request: HttpRequest, payload: WorkspaceIn) -> Status[WorkspaceOut]:
    ctx = services.create_workspace(
        _user(request),
        name=payload.name,
        kind=payload.kind,
        entity_name=payload.entity_name,
        entity_type=payload.entity_type,
    )
    return Status(201, _workspace_out(ctx))


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
    return _workspace_out(workspace_ctx(request, slug))


@router.get("/w/{slug}/entities", response=list[EntityOut])
@requires("tenancy.workspace.read")
def list_entities_route(request: HttpRequest, slug: str) -> list[LegalEntity]:
    return services.list_entities(workspace_ctx(request, slug))


@router.post("/w/{slug}/entities", response={201: EntityOut})
@requires("tenancy.entity.manage")
def create_entity_route(request: HttpRequest, slug: str, payload: EntityIn) -> Status[LegalEntity]:
    ctx = workspace_ctx(request, slug)
    entity = services.create_entity(
        ctx,
        legal_name=payload.legal_name,
        entity_type=payload.entity_type,
        registration_no=payload.registration_no,
    )
    return Status(201, entity)


@router.get("/w/{slug}/entities/{entity_id}", response=EntityOut)
@requires("tenancy.workspace.read")
def get_entity_route(request: HttpRequest, slug: str, entity_id: UUID) -> LegalEntity:
    return services.get_entity(workspace_ctx(request, slug, entity_id), entity_id)


@router.post("/w/{slug}/invitations", response={201: InvitationOut})
@requires("tenancy.members.manage")
def invite(request: HttpRequest, slug: str, payload: InvitationIn) -> Status[InvitationOut]:
    ctx = workspace_ctx(request, slug, payload.legal_entity_id)
    # Granting roles needs a recent sign-in (doc 04 §2 step-up).
    require_recent_auth(request.session, request.path)
    issued = services.invite_member(
        ctx, email=payload.email, role_key=payload.role_key, legal_entity_id=payload.legal_entity_id
    )
    inv = issued.invitation
    return Status(
        201,
        InvitationOut(
            id=inv.id,
            email=inv.email,
            role_key=inv.role_key,
            expires_at=inv.expires_at,
            token=issued.token,
        ),
    )


@router.post("/invitations/accept", response=WorkspaceOut)
@requires(AUTHENTICATED)
def accept(request: HttpRequest, payload: AcceptIn) -> WorkspaceOut:
    return _workspace_out(services.accept_invitation(_user(request), payload.token))


class RoleOut(Schema):
    id: UUID
    role_key: str
    legal_entity_id: UUID | None


class MemberOut(Schema):
    membership_id: UUID
    user_id: UUID
    email: str
    display_name: str
    status: str
    roles: list[RoleOut]


class RoleGrantIn(Schema):
    role_key: Role
    legal_entity_id: UUID | None = None


@router.get("/w/{slug}/members", response=list[MemberOut])
@requires("tenancy.members.manage")
def list_members(request: HttpRequest, slug: str) -> list[MemberOut]:
    return [
        MemberOut(
            membership_id=m.membership.id,
            user_id=m.user.id,
            email=m.user.email,
            display_name=m.user.display_name,
            status=m.membership.status,
            roles=[
                RoleOut(id=a.id, role_key=a.role_key, legal_entity_id=a.legal_entity_id)
                for a in m.assignments
            ],
        )
        for m in services.list_members(workspace_ctx(request, slug))
    ]


@router.post("/w/{slug}/members/{membership_id}/roles", response={201: RoleOut})
@requires("tenancy.members.manage")
def grant_role(
    request: HttpRequest, slug: str, membership_id: UUID, payload: RoleGrantIn
) -> Status[RoleOut]:
    ctx = workspace_ctx(request, slug, payload.legal_entity_id)
    require_recent_auth(request.session, request.path)
    a = services.grant_role(
        ctx, membership_id, role_key=payload.role_key, legal_entity_id=payload.legal_entity_id
    )
    return Status(201, RoleOut(id=a.id, role_key=a.role_key, legal_entity_id=a.legal_entity_id))


@router.delete("/w/{slug}/roles/{assignment_id}", response={204: None})
@requires("tenancy.members.manage")
def revoke_role(request: HttpRequest, slug: str, assignment_id: UUID) -> Status[None]:
    ctx = workspace_ctx(request, slug)
    require_recent_auth(request.session, request.path)
    services.revoke_role(ctx, assignment_id)
    return Status(204, None)


@router.get("/w/{slug}/features", response=dict[str, bool])
@requires("tenancy.workspace.read")
def features(request: HttpRequest, slug: str) -> dict[str, bool]:
    ctx = workspace_ctx(request, slug)
    return {f.value: has_feature(ctx.tenant.kind, f) for f in Feature}
