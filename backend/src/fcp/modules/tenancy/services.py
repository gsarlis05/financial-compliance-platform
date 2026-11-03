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

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import ConflictError, NotFoundError, PermissionDeniedError, ValidationFailedError
from fcp.core.ids import uuid7
from fcp.modules.identity.api import User

from .entitlements import Feature, Role, allowed_roles, require_feature
from .models import Invitation, LegalEntity, Membership, RoleAssignment, Tenant

INVITATION_LIFETIME = timedelta(days=7)
ADMIN_ROLES = frozenset({Role.OWNER, Role.TENANT_ADMIN})


@dataclass(frozen=True)
class WorkspaceContext:
    """The authenticated user acting inside one workspace (doc 11 §2: exactly one per request)."""

    tenant: Tenant
    user: User
    membership: Membership
    roles: frozenset[str]


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
    RoleAssignment.objects.create(
        tenant=tenant, membership=membership, role_key=Role.OWNER, granted_by=user
    )
    if kind == Tenant.Kind.PERSONAL:
        LegalEntity.objects.create(
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
        LegalEntity.objects.create(
            tenant=tenant,
            legal_name=entity_name,
            entity_type=entity_type or LegalEntity.EntityType.COMPANY,
            created_by=user,
        )
    return WorkspaceContext(tenant, user, membership, frozenset({Role.OWNER}))


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
    now = timezone.now()
    roles = frozenset(
        RoleAssignment.objects.filter(membership=membership)
        .exclude(valid_until__lt=now)
        .values_list("role_key", flat=True)
    )
    return WorkspaceContext(tenant, user, membership, roles)


def _require_admin(ctx: WorkspaceContext) -> None:
    if not ctx.roles & ADMIN_ROLES:
        raise PermissionDeniedError("Only workspace owners and administrators can do this.")


# --- legal entities ----------------------------------------------------------------------------


@transaction.atomic
def create_entity(
    ctx: WorkspaceContext, *, legal_name: str, entity_type: str, registration_no: str = ""
) -> LegalEntity:
    _require_admin(ctx)
    existing = LegalEntity.objects.filter(tenant=ctx.tenant).count()
    if existing >= 1:
        require_feature(ctx.tenant.kind, Feature.MULTIPLE_ENTITIES)
    if entity_type not in LegalEntity.EntityType.values or (
        entity_type == LegalEntity.EntityType.HOUSEHOLD and ctx.tenant.kind != Tenant.Kind.PERSONAL
    ):
        raise ValidationFailedError(
            "This entity type is not allowed here.", field_errors={"entity_type": ["invalid"]}
        )
    return LegalEntity.objects.create(
        tenant=ctx.tenant,
        legal_name=legal_name,
        entity_type=entity_type,
        registration_no=registration_no,
        created_by=ctx.user,
    )


def list_entities(ctx: WorkspaceContext) -> list[LegalEntity]:
    return list(LegalEntity.objects.filter(tenant=ctx.tenant).order_by("legal_name"))


def get_entity(ctx: WorkspaceContext, entity_id: uuid.UUID) -> LegalEntity:
    entity = LegalEntity.objects.filter(tenant=ctx.tenant, id=entity_id).first()
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
    _require_admin(ctx)
    require_feature(ctx.tenant.kind, Feature.INVITE_MEMBERS)
    if role_key not in allowed_roles(ctx.tenant.kind) or role_key == Role.OWNER:
        raise ValidationFailedError(
            "This role cannot be granted in this workspace.", field_errors={"role_key": ["invalid"]}
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
        RoleAssignment.objects.get_or_create(
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
    tenant = Tenant.objects.get(id=tenant_id)
    return enter_workspace(user, tenant.slug)
