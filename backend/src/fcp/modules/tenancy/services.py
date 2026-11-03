"""Workspace operations. Every function sets the row-level security context itself, so callers
cannot forget it; queries outside that context return nothing.
"""

import hashlib
import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from fcp.core.ids import uuid7
from fcp.modules.audit_log.api import record as audit
from fcp.modules.identity.api import User

from .entitlements import Feature, Role, allowed_roles, require_feature
from .models import Invitation, LegalEntity, Membership, RoleAssignment, Tenant
from .permissions import is_known, permissions_for

INVITATION_LIFETIME = timedelta(days=7)

type Assignment = tuple[str, uuid.UUID | None]  # (role_key, legal_entity_id or None = all)


@dataclass(frozen=True)
class WorkspaceContext:
    """The authenticated user acting inside one workspace (doc 11 §2: exactly one per request).

    Authorization (doc 04 §3.3): a permission is granted by any current role assignment that is
    workspace-wide or scoped to the legal entity concerned. Deny by default.
    """

    tenant: Tenant
    user: User
    membership: Membership
    assignments: tuple[Assignment, ...]

    @property
    def roles(self) -> frozenset[str]:
        return frozenset(role for role, _ in self.assignments)

    def can(self, permission: str, entity_id: uuid.UUID | None = None) -> bool:
        for role, scope in self.assignments:
            if permission in permissions_for(role) and (scope is None or scope == entity_id):
                return True
        return False

    def permitted_entity_ids(self, permission: str) -> frozenset[uuid.UUID] | None:
        """``None`` means every entity; otherwise only these entities (entity-scoped roles)."""
        scopes = [scope for role, scope in self.assignments if permission in permissions_for(role)]
        if any(scope is None for scope in scopes):
            return None
        return frozenset(scope for scope in scopes if scope is not None)

    def permissions(self, entity_id: uuid.UUID | None = None) -> frozenset[str]:
        granted: set[str] = set()
        for role, scope in self.assignments:
            if scope is None or scope == entity_id:
                granted |= permissions_for(role)
        return frozenset(granted)

    def authorize(self, permission: str, entity_id: uuid.UUID | None = None) -> None:
        """Raise unless the permission is granted (for ``entity_id`` if given).

        Without an entity, an entity-scoped grant suffices; callers then restrict results with
        ``permitted_entity_ids``. A denial for an entity the user cannot see at all is a 404, so
        the entity's existence is not disclosed.
        """
        if not is_known(permission):
            raise PermissionDeniedError(f"Unknown permission {permission!r}.")
        if entity_id is None:
            if self.permitted_entity_ids(permission) != frozenset():
                return
        elif self.can(permission, entity_id):
            return
        else:
            visible = self.permitted_entity_ids("tenancy.workspace.read")
            if visible is not None and entity_id not in visible:
                raise NotFoundError("Legal entity not found.")
        raise PermissionDeniedError("You do not have permission to do this.")


# --- workspace lifecycle -----------------------------------------------------------------------


def _slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


@transaction.atomic
def create_workspace(
    user: User,
    *,
    name: str,
    kind: str,
    entity_name: str | None = None,
    entity_type: str | None = None,
) -> WorkspaceContext:
    """Create a workspace with the creator as owner. PERSONAL workspaces get their single
    household entity automatically; BUSINESS workspaces need their first legal entity."""
    if kind not in Tenant.Kind.values:
        raise ValidationFailedError("Unknown workspace kind.", field_errors={"kind": ["invalid"]})
    tenant_id = uuid7()
    set_context(tenant_id=tenant_id, user_id=user.id)
    tenant = Tenant.objects.create(
        id=tenant_id, slug=_slugify(name), name=name, kind=kind, created_by=user
    )
    membership = Membership.objects.create(tenant=tenant, user=user)
    owner_role = RoleAssignment.objects.create(
        tenant=tenant, membership=membership, role_key=Role.OWNER, granted_by=user
    )
    audit(
        tenant_id=tenant.id,
        actor_user_id=user.id,
        action="tenancy.workspace.created",
        subject_type="tenant",
        subject_id=tenant.id,
        changes={"name": name, "kind": kind},
    )
    _audit_role(tenant.id, user.id, owner_role, "tenancy.role.granted")
    entity: LegalEntity | None = None
    if kind == Tenant.Kind.PERSONAL:
        entity = LegalEntity.objects.create(
            tenant=tenant,
            legal_name=f"{name} (household)",
            entity_type=LegalEntity.EntityType.HOUSEHOLD,
            created_by=user,
        )
    elif kind == Tenant.Kind.BUSINESS:
        if not entity_name:
            raise ValidationFailedError(
                "A business workspace needs its company details.",
                field_errors={"entity_name": ["required for a business workspace"]},
            )
        entity = LegalEntity.objects.create(
            tenant=tenant,
            legal_name=entity_name,
            entity_type=entity_type or LegalEntity.EntityType.COMPANY,
            created_by=user,
        )
    if entity is not None:
        _audit_entity(tenant.id, user.id, entity)
    return WorkspaceContext(tenant, user, membership, ((Role.OWNER, None),))


def _audit_entity(tenant_id: uuid.UUID, user_id: uuid.UUID, entity: LegalEntity) -> None:
    audit(
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action="tenancy.entity.created",
        subject_type="legal_entity",
        subject_id=entity.id,
        entity_id=entity.id,
        changes={
            "legal_name": entity.legal_name,
            "entity_type": entity.entity_type,
            "registration_no": entity.registration_no,
        },
    )


def _audit_role(
    tenant_id: uuid.UUID, user_id: uuid.UUID, assignment: RoleAssignment, action: str
) -> None:
    audit(
        tenant_id=tenant_id,
        actor_user_id=user_id,
        action=action,
        subject_type="role_assignment",
        subject_id=assignment.id,
        entity_id=assignment.legal_entity_id,
        changes={
            "membership_id": assignment.membership_id,
            "role_key": assignment.role_key,
            "legal_entity_id": assignment.legal_entity_id,
        },
    )


def list_workspaces(user: User) -> list[Tenant]:
    """Workspaces where the user has an active membership (visible through the RLS policy)."""
    set_context(user_id=user.id)
    member_of = Membership.objects.filter(user=user, status=Membership.Status.ACTIVE).values(
        "tenant_id"
    )
    return list(
        Tenant.objects.filter(id__in=member_of, status=Tenant.Status.ACTIVE).order_by("name")
    )


def enter_workspace(user: User, slug: str) -> WorkspaceContext:
    """Resolve the workspace from the URL and bind the RLS context to it.

    Unknown workspaces and workspaces the user is not a member of give the same 404, so their
    existence is never disclosed (doc 04 §5).
    """
    set_context(user_id=user.id)
    tenant = Tenant.objects.filter(slug=slug, status=Tenant.Status.ACTIVE).first()
    if tenant is None:
        raise NotFoundError("Workspace not found.")
    set_context(tenant_id=tenant.id, user_id=user.id)
    membership = Membership.objects.filter(
        tenant=tenant, user=user, status=Membership.Status.ACTIVE
    ).first()
    if membership is None:
        raise NotFoundError("Workspace not found.")
    assignments = tuple(
        RoleAssignment.objects.filter(membership=membership)
        .exclude(valid_until__lt=timezone.now())
        .order_by("role_key")
        .values_list("role_key", "legal_entity_id")
    )
    return WorkspaceContext(tenant, user, membership, assignments)


# --- legal entities ----------------------------------------------------------------------------


@transaction.atomic
def create_entity(
    ctx: WorkspaceContext, *, legal_name: str, entity_type: str, registration_no: str = ""
) -> LegalEntity:
    ctx.authorize("tenancy.entity.manage")
    if ctx.permitted_entity_ids("tenancy.entity.manage") is not None:
        raise PermissionDeniedError("Only workspace-wide administrators can add legal entities.")
    existing = LegalEntity.objects.filter(tenant=ctx.tenant).count()
    if existing >= 1:
        require_feature(ctx.tenant.kind, Feature.MULTIPLE_ENTITIES)
    if entity_type not in LegalEntity.EntityType.values or (
        entity_type == LegalEntity.EntityType.HOUSEHOLD and ctx.tenant.kind != Tenant.Kind.PERSONAL
    ):
        raise ValidationFailedError(
            "This entity type is not allowed here.", field_errors={"entity_type": ["invalid"]}
        )
    entity = LegalEntity.objects.create(
        tenant=ctx.tenant,
        legal_name=legal_name,
        entity_type=entity_type,
        registration_no=registration_no,
        created_by=ctx.user,
    )
    _audit_entity(ctx.tenant.id, ctx.user.id, entity)
    return entity


def visible_entities(ctx: WorkspaceContext, permission: str = "tenancy.workspace.read") -> Any:
    """Entities the user may see for ``permission`` (entity-scoped roles see only theirs)."""
    queryset = LegalEntity.objects.filter(tenant=ctx.tenant)
    scope = ctx.permitted_entity_ids(permission)
    return queryset if scope is None else queryset.filter(id__in=scope)


def list_entities(ctx: WorkspaceContext) -> list[LegalEntity]:
    return list(visible_entities(ctx).order_by("legal_name"))


def get_entity(
    ctx: WorkspaceContext, entity_id: uuid.UUID, permission: str = "tenancy.workspace.read"
) -> LegalEntity:
    entity: LegalEntity | None = visible_entities(ctx, permission).filter(id=entity_id).first()
    if entity is None:
        raise NotFoundError("Legal entity not found.")
    return entity


# --- invitations ---------------------------------------------------------------------------------


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class IssuedInvitation:
    invitation: Invitation
    token: str  # shown once; only its hash is stored


@transaction.atomic
def invite_member(
    ctx: WorkspaceContext, *, email: str, role_key: str, legal_entity_id: uuid.UUID | None = None
) -> IssuedInvitation:
    ctx.authorize("tenancy.members.manage", legal_entity_id)
    require_feature(ctx.tenant.kind, Feature.INVITE_MEMBERS)
    if role_key not in allowed_roles(ctx.tenant.kind) or role_key == Role.OWNER:
        raise ValidationFailedError(
            "This role cannot be granted in this workspace.", field_errors={"role_key": ["invalid"]}
        )
    # Nobody can grant more than they hold (AC-B7).
    missing = permissions_for(role_key) - ctx.permissions(legal_entity_id)
    if missing:
        raise PermissionDeniedError(
            "You cannot grant a role with permissions you do not hold yourself: "
            + ", ".join(sorted(missing))
        )
    entity = get_entity(ctx, legal_entity_id) if legal_entity_id else None
    # The tenant id prefix lets acceptance bind the RLS context before looking the invite up.
    token = f"{ctx.tenant.id}.{secrets.token_urlsafe(32)}"
    invitation = Invitation.objects.create(
        tenant=ctx.tenant,
        email=email.strip().lower(),
        role_key=role_key,
        legal_entity=entity,
        token_hash=_hash_token(token),
        expires_at=timezone.now() + INVITATION_LIFETIME,
        invited_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.invitation.created",
        subject_type="invitation",
        subject_id=invitation.id,
        entity_id=legal_entity_id,
        changes={
            "email": invitation.email,
            "role_key": role_key,
            "legal_entity_id": legal_entity_id,
            "expires_at": invitation.expires_at,
        },
        sensitive=["email"],
    )
    return IssuedInvitation(invitation, token)


@transaction.atomic
def accept_invitation(user: User, token: str) -> WorkspaceContext:
    tenant_part, _, secret = token.partition(".")
    try:
        tenant_id = uuid.UUID(tenant_part)
    except ValueError:
        raise NotFoundError("This invitation is invalid or has expired.") from None
    if not secret:
        raise NotFoundError("This invitation is invalid or has expired.")
    set_context(tenant_id=tenant_id, user_id=user.id)
    invitation = (
        Invitation.objects.select_for_update()
        .filter(token_hash=_hash_token(token), accepted_at__isnull=True)
        .first()
    )
    if invitation is None or invitation.expires_at < timezone.now():
        raise NotFoundError("This invitation is invalid or has expired.")
    if invitation.email != user.email.strip().lower():
        raise PermissionDeniedError(
            "This invitation was sent to a different e-mail address. Sign in with that address."
        )
    membership, _ = Membership.objects.get_or_create(tenant_id=tenant_id, user=user)
    if membership.status != Membership.Status.ACTIVE:
        raise ConflictError("Your membership of this workspace is not active.")
    try:
        assignment, created = RoleAssignment.objects.get_or_create(
            tenant_id=tenant_id,
            membership=membership,
            role_key=invitation.role_key,
            legal_entity=invitation.legal_entity,
            defaults={"granted_by": invitation.invited_by},
        )
    except IntegrityError:  # pragma: no cover - guarded by get_or_create
        raise ConflictError("This role is already assigned.") from None
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    audit(
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="tenancy.invitation.accepted",
        subject_type="invitation",
        subject_id=invitation.id,
        changes={"membership_id": membership.id},
    )
    if created:
        _audit_role(tenant_id, user.id, assignment, "tenancy.role.granted")
    tenant = Tenant.objects.get(id=tenant_id)
    return enter_workspace(user, tenant.slug)


# --- members and roles -----------------------------------------------------------------------


@dataclass(frozen=True)
class MemberView:
    membership: Membership
    user: User
    assignments: list[RoleAssignment]


def list_members(ctx: WorkspaceContext) -> list[MemberView]:
    ctx.authorize("tenancy.members.manage")
    members = (
        Membership.objects.filter(tenant=ctx.tenant).select_related("user").order_by("created_at")
    )
    assignments: dict[uuid.UUID, list[RoleAssignment]] = {}
    for a in RoleAssignment.objects.filter(tenant=ctx.tenant).order_by("role_key"):
        assignments.setdefault(a.membership_id, []).append(a)
    return [MemberView(m, m.user, assignments.get(m.id, [])) for m in members]


def _membership(ctx: WorkspaceContext, membership_id: uuid.UUID) -> Membership:
    membership = Membership.objects.filter(tenant=ctx.tenant, id=membership_id).first()
    if membership is None:
        raise NotFoundError("Member not found.")
    return membership


@transaction.atomic
def grant_role(
    ctx: WorkspaceContext,
    membership_id: uuid.UUID,
    *,
    role_key: str,
    legal_entity_id: uuid.UUID | None = None,
) -> RoleAssignment:
    ctx.authorize("tenancy.members.manage", legal_entity_id)
    if role_key not in allowed_roles(ctx.tenant.kind) or role_key == Role.OWNER:
        raise ValidationFailedError(
            "This role cannot be granted in this workspace.", field_errors={"role_key": ["invalid"]}
        )
    missing = permissions_for(role_key) - ctx.permissions(legal_entity_id)
    if missing:
        raise PermissionDeniedError(
            "You cannot grant a role with permissions you do not hold yourself: "
            + ", ".join(sorted(missing))
        )
    membership = _membership(ctx, membership_id)
    entity = get_entity(ctx, legal_entity_id) if legal_entity_id else None
    assignment, created = RoleAssignment.objects.get_or_create(
        tenant=ctx.tenant,
        membership=membership,
        role_key=role_key,
        legal_entity=entity,
        defaults={"granted_by": ctx.user},
    )
    if not created:
        raise ConflictError("The member already has this role.")
    _audit_role(ctx.tenant.id, ctx.user.id, assignment, "tenancy.role.granted")
    return assignment


@transaction.atomic
def revoke_role(ctx: WorkspaceContext, assignment_id: uuid.UUID) -> None:
    assignment = (
        RoleAssignment.objects.select_for_update()
        .filter(tenant=ctx.tenant, id=assignment_id)
        .first()
    )
    if assignment is None:
        raise NotFoundError("Role assignment not found.")
    ctx.authorize("tenancy.members.manage", assignment.legal_entity_id)
    if assignment.role_key == Role.OWNER:
        owners = RoleAssignment.objects.filter(tenant=ctx.tenant, role_key=Role.OWNER).count()
        if owners <= 1:
            raise ConflictError("A workspace must keep at least one owner.")
        if Role.OWNER not in ctx.roles:
            raise PermissionDeniedError("Only an owner can remove another owner.")
    _audit_role(ctx.tenant.id, ctx.user.id, assignment, "tenancy.role.revoked")
    assignment.delete()
