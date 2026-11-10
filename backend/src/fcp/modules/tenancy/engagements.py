"""Engagement grants: a client-owned workspace lets a firm work in it (M5-4, doc 11 §3).

- **The client grants** (owner or administrator, workspace-wide): a firm, a scope of roles, all
  legal entities or one, and an end date. A grant can be revoked at any time, with immediate
  effect, because access is worked out again on every request.
- **The firm staffs** the engagement with its own members, in its own workspace.
- **A staff member acts inside the client's workspace** (one workspace per request, the client's
  row-level security context) with the **intersection** of the engagement scope and their own
  workspace-wide firm role. Every action is audited in the client's workspace, attributed to the
  person and the firm; grants and revocations are audited there too, and staffing in the firm's.
- No query crosses workspaces. The firm and client learn about each other only through the narrow
  SECURITY DEFINER functions of migration 0005, which return only what the caller is entitled to.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context, set_engagement
from fcp.core.errors import NotFoundError, PermissionDeniedError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.identity.api import User

from .entitlements import Feature, Role, allowed_roles, require_feature
from .models import Engagement, EngagementStaff, LegalEntity, Membership, Tenant

__all__ = ["Engagement", "EngagementStaff"]

if TYPE_CHECKING:
    from .services import WorkspaceContext

MANAGE = "tenancy.members.manage"
MAX_LENGTH = timedelta(days=3 * 366)

# Roles a client can grant to a firm. Ownership and administration are never granted.
ENGAGEABLE: frozenset[str] = frozenset({Role.ACCOUNTANT, Role.REVIEWER, Role.READ_ONLY})

# Which engagement roles a workspace-wide firm role can fill. Partners and administrators can
# fill any; an accountant prepares, a reviewer reviews; everyone with a role can read.
FIRM_COVERS: dict[str, frozenset[str]] = {
    Role.OWNER: ENGAGEABLE,
    Role.TENANT_ADMIN: ENGAGEABLE,
    Role.PARTNER: ENGAGEABLE,
    Role.ACCOUNTANT: frozenset({Role.ACCOUNTANT, Role.READ_ONLY}),
    Role.REVIEWER: frozenset({Role.REVIEWER, Role.READ_ONLY}),
    Role.READ_ONLY: frozenset({Role.READ_ONLY}),
}


def _roles(raw: Any) -> list[str]:
    """A jsonb list from a raw cursor arrives as text."""
    return [str(r) for r in (json.loads(raw) if isinstance(raw, str) else raw)]


def _invalid(name: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={name: [message]})


def granted_roles(scope: list[str], firm_roles: set[str], client_kind: str) -> set[str]:
    """The intersection: what the engagement allows, the firm role covers and the client's kind
    of workspace has."""
    covered: set[str] = set()
    for role in firm_roles:
        covered |= FIRM_COVERS.get(role, frozenset())
    return set(scope) & covered & set(ENGAGEABLE) & set(allowed_roles(client_kind))


# --- access (used by enter_workspace on every request) -------------------------------------------


@dataclass(frozen=True)
class EngagedAccess:
    tenant: Tenant
    assignments: tuple[tuple[str, UUID | None], ...]
    firm_name: str


def access_through_engagement(user: User, slug: str) -> EngagedAccess:
    """The user's access to a client workspace through engagements they are staffed on, or a 404
    (the same answer as for an unknown workspace). Binds the RLS context to the client."""
    set_context(user_id=user.id)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT client_tenant_id, engagement_id, firm_name, scope_roles, legal_entity_id, "
            "firm_role FROM app_engagement_access(%s)",
            [slug],
        )
        rows = cursor.fetchall()
    if not rows:
        raise NotFoundError("Workspace not found.")
    client_id = rows[0][0]
    set_context(tenant_id=client_id, user_id=user.id)
    tenant = Tenant.objects.filter(id=client_id, status=Tenant.Status.ACTIVE).first()
    if tenant is None:
        raise NotFoundError("Workspace not found.")
    by_engagement: dict[UUID, tuple[str, list[str], UUID | None, set[str]]] = {}
    for _, engagement_id, firm_name, scope, entity_id, firm_role in rows:
        name, scope_roles, entity, roles = by_engagement.setdefault(
            engagement_id, (firm_name, _roles(scope), entity_id, set())
        )
        roles.add(firm_role)
    assignments: set[tuple[str, UUID | None]] = set()
    firms: set[str] = set()
    for engagement_id, (name, scope_roles, entity, roles) in by_engagement.items():
        granted = granted_roles(scope_roles, roles, tenant.kind)
        if granted:
            assignments |= {(role, entity) for role in granted}
            firms.add(f"{name} ({engagement_id})")
    if not assignments:
        raise NotFoundError("Workspace not found.")
    label = "; ".join(sorted(firms))
    set_engagement(label)
    ordered = tuple(sorted(assignments, key=lambda a: (a[0], str(a[1] or ""))))
    return EngagedAccess(tenant, ordered, label)


def engaged_workspaces(firm_tenant_id: UUID | None = None) -> list[Tenant]:
    """Client workspaces the current user (RLS context) can open through an engagement, through
    any firm or the given one. The tenant context is left as it is."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT DISTINCT id, slug, name, kind FROM app_engaged_workspaces() "
            "WHERE %s::uuid IS NULL OR firm_tenant_id = %s::uuid ORDER BY name",
            [firm_tenant_id, firm_tenant_id],
        )
        return [Tenant(id=i, slug=s, name=n, kind=k) for i, s, n, k in cursor.fetchall()]


# --- the client's side -------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantInput:
    firm_slug: str
    scope_roles: list[str]
    valid_until: datetime
    legal_entity_id: UUID | None = None


def _client_admin(ctx: "WorkspaceContext") -> None:
    require_feature(ctx.tenant.kind, Feature.GRANT_ENGAGEMENTS)
    ctx.authorize(MANAGE)
    if ctx.permitted_entity_ids(MANAGE) is not None or ctx.engagement is not None:
        raise PermissionDeniedError("Only the client's own administrators can manage engagements.")


@transaction.atomic
def grant(ctx: "WorkspaceContext", data: GrantInput) -> Engagement:
    _client_admin(ctx)
    scope = sorted(set(data.scope_roles))
    possible = set(ENGAGEABLE) & set(allowed_roles(ctx.tenant.kind))
    if not scope or not set(scope) <= possible:
        raise _invalid("scope_roles", f"Choose from: {', '.join(sorted(possible))}.")
    now = timezone.now()
    if data.valid_until <= now or data.valid_until > now + MAX_LENGTH:
        raise _invalid("valid_until", "Choose an end date in the next 3 years.")
    if (
        data.legal_entity_id is not None
        and not LegalEntity.objects.filter(
            tenant=ctx.tenant, id=data.legal_entity_id, status=LegalEntity.Status.ACTIVE
        ).exists()
    ):
        raise _invalid("legal_entity_id", "Choose one of your legal entities.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT id, name FROM app_firm_lookup(%s)", [data.firm_slug.strip()])
        firm = cursor.fetchone()
    if firm is None:
        raise _invalid("firm_slug", "No accounting firm has this address.")
    made = Engagement.objects.create(
        tenant=ctx.tenant,
        firm_tenant_id=firm[0],
        firm_name=firm[1],
        scope_roles=scope,
        legal_entity_id=data.legal_entity_id,
        valid_until=data.valid_until,
        granted_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.engagement.granted",
        subject_type="engagement",
        subject_id=made.id,
        entity_id=data.legal_entity_id,
        changes={"firm": firm[1], "firm_tenant_id": str(firm[0]), "scope_roles": scope,
                 "valid_until": data.valid_until.isoformat()},
    )  # fmt: skip
    return made


def grants(ctx: "WorkspaceContext") -> list[Engagement]:
    """The client's grants, current first, then ended ones."""
    _client_admin(ctx)
    return list(Engagement.objects.filter(tenant=ctx.tenant).order_by("revoked_at", "-created_at"))


@transaction.atomic
def revoke(ctx: "WorkspaceContext", engagement_id: UUID) -> Engagement:
    _client_admin(ctx)
    made = Engagement.objects.filter(
        tenant=ctx.tenant, id=engagement_id, revoked_at__isnull=True
    ).first()
    if made is None:
        raise NotFoundError("Engagement not found.")
    made.revoked_at, made.revoked_by = timezone.now(), ctx.user
    made.save(update_fields=["revoked_at", "revoked_by"])
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.engagement.revoked",
        subject_type="engagement",
        subject_id=made.id,
        entity_id=made.legal_entity_id,
        changes={"firm": made.firm_name},
    )
    return made


# --- the firm's side ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmEngagement:
    engagement_id: UUID
    client_tenant_id: UUID
    client_slug: str
    client_name: str
    client_kind: str
    scope_roles: list[str]
    legal_entity_id: UUID | None
    valid_until: datetime
    staff: list[EngagementStaff]


def _firm_admin(ctx: "WorkspaceContext") -> None:
    require_feature(ctx.tenant.kind, Feature.CLIENT_PORTFOLIO)
    ctx.authorize(MANAGE)
    if ctx.permitted_entity_ids(MANAGE) is not None:
        raise PermissionDeniedError("Only the firm's administrators can staff engagements.")


def _granted_to_firm(ctx: "WorkspaceContext") -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT engagement_id, client_tenant_id, client_slug, client_name, client_kind, "
            "scope_roles, legal_entity_id, valid_until FROM app_firm_engagements()"
        )
        return list(cursor.fetchall())


def firm_engagements(ctx: "WorkspaceContext") -> list[FirmEngagement]:
    """Active grants made to this firm, with the firm's staff on each."""
    _firm_admin(ctx)
    rows = _granted_to_firm(ctx)
    staff = list(
        EngagementStaff.objects.filter(tenant=ctx.tenant, removed_at__isnull=True)
        .select_related("membership__user")
        .order_by("created_at")
    )
    return [
        FirmEngagement(
            engagement_id=r[0], client_tenant_id=r[1], client_slug=r[2], client_name=r[3],
            client_kind=r[4], scope_roles=_roles(r[5]), legal_entity_id=r[6], valid_until=r[7],
            staff=[s for s in staff if s.engagement_id == r[0]],
        )
        for r in rows
    ]  # fmt: skip


@transaction.atomic
def add_staff(ctx: "WorkspaceContext", engagement_id: UUID, membership_id: UUID) -> EngagementStaff:
    _firm_admin(ctx)
    row = next((r for r in _granted_to_firm(ctx) if r[0] == engagement_id), None)
    if row is None:
        raise NotFoundError("Engagement not found.")
    member = Membership.objects.filter(
        tenant=ctx.tenant, id=membership_id, status=Membership.Status.ACTIVE
    ).first()
    if member is None:
        raise _invalid("membership_id", "Choose an active member of the firm.")
    if EngagementStaff.objects.filter(
        tenant=ctx.tenant, engagement_id=engagement_id, membership=member, removed_at__isnull=True
    ).exists():
        raise _invalid("membership_id", "This member is already on the engagement.")
    made = EngagementStaff.objects.create(
        tenant=ctx.tenant,
        engagement_id=engagement_id,
        client_tenant_id=row[1],
        membership=member,
        added_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.engagement.staff_added",
        subject_type="engagement_staff",
        subject_id=made.id,
        changes={"engagement": str(engagement_id), "client": row[3],
                 "member": member.user.email},
    )  # fmt: skip
    return made


@transaction.atomic
def remove_staff(ctx: "WorkspaceContext", staff_id: UUID) -> None:
    _firm_admin(ctx)
    made = EngagementStaff.objects.filter(
        tenant=ctx.tenant, id=staff_id, removed_at__isnull=True
    ).first()
    if made is None:
        raise NotFoundError("Assignment not found.")
    made.removed_at = timezone.now()
    made.save(update_fields=["removed_at"])
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.engagement.staff_removed",
        subject_type="engagement_staff",
        subject_id=made.id,
        changes={"engagement": str(made.engagement_id)},
    )
