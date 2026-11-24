"""One-person workspaces (version 1, V1-1, #207; ADR-0055).

A workspace used by one person cannot have a second person approve anything. When its owner
turns this setting on, the person who prepared something may also approve it, and every such
approval is recorded as **self-approved**. The setting holds only while the workspace has exactly
one active member, no pending invitation and no active engagement grant; the database refuses
anything else (migration 0009), so a self-approval can never happen where a second person could
have approved.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from fcp.core.errors import ConflictError
from fcp.modules.audit_log.api import record as audit

from .models import Engagement, Invitation, Membership, Tenant

if TYPE_CHECKING:
    from .services import WorkspaceContext

CLOSED = "This is a one-person workspace. Turn that setting off before adding people."


@dataclass(frozen=True)
class OnePerson:
    enabled: bool  # the setting
    active: bool  # the setting holds now: self-approval is allowed
    blockers: list[str]  # why it cannot be turned on (empty when it can)


def self_approval_allowed(tenant_id: UUID) -> bool:
    """True when the person who prepared something may also approve it (the database's view)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT tenancy_one_person(%s)", [tenant_id])
        return bool(cursor.fetchone()[0])


def _blockers(tenant: Tenant) -> list[str]:
    found = []
    members = Membership.objects.filter(tenant=tenant, status=Membership.Status.ACTIVE).count()
    if members != 1:
        found.append(f"The workspace has {members} active members; it must have exactly one.")
    if Invitation.objects.filter(
        tenant=tenant, accepted_at__isnull=True, expires_at__gt=timezone.now()
    ).exists():
        found.append("An invitation is still pending.")
    if Engagement.objects.filter(
        tenant=tenant, revoked_at__isnull=True, valid_until__gt=timezone.now()
    ).exists():
        found.append("An accounting firm has an active engagement grant.")
    return found


def status(ctx: "WorkspaceContext") -> OnePerson:
    tenant = ctx.tenant
    tenant.refresh_from_db(fields=["one_person"])
    return OnePerson(tenant.one_person, self_approval_allowed(tenant.id), _blockers(tenant))


@transaction.atomic
def set_enabled(ctx: "WorkspaceContext", enabled: bool) -> OnePerson:
    ctx.authorize("tenancy.members.manage")
    tenant = Tenant.objects.select_for_update().get(id=ctx.tenant.id)
    if tenant.one_person == enabled:
        return status(ctx)
    if enabled:
        problems = _blockers(tenant)
        if problems:
            raise ConflictError("This workspace cannot be one-person yet. " + " ".join(problems))
    tenant.one_person = enabled
    tenant.save(update_fields=["one_person"])
    audit(
        tenant_id=tenant.id,
        actor_user_id=ctx.user.id,
        action="tenancy.one_person.enabled" if enabled else "tenancy.one_person.disabled",
        subject_type="workspace",
        subject_id=tenant.id,
        changes={"one_person": enabled},
    )
    ctx.tenant.one_person = enabled
    return status(ctx)


def refuse_people(tenant: Tenant) -> None:
    """Called before inviting someone or granting an engagement."""
    tenant.refresh_from_db(fields=["one_person"])
    if tenant.one_person:
        raise ConflictError(CLOSED)
