"""Workspaces (tenants), legal entities, memberships, role assignments and invitations
(docs/planning/03 §1 and §6, 11 §2).

Every table except ``tenancy_tenant`` carries ``tenant_id`` and is protected by FORCE row-level
security plus composite (tenant_id, id) foreign keys (see migration 0001).
"""

from django.conf import settings
from django.db import models

from fcp.core.db.models import TenantOwned
from fcp.core.ids import uuid7


class Tenant(models.Model):
    class Kind(models.TextChoices):
        FIRM = "FIRM"
        BUSINESS = "BUSINESS"
        PERSONAL = "PERSONAL"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        SUSPENDED = "SUSPENDED"
        CLOSED = "CLOSED"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    slug = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    data_region = models.CharField(max_length=32, default="eu-central-1")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tenancy_tenant"

    def __str__(self) -> str:
        return self.slug


class LegalEntity(TenantOwned):
    class EntityType(models.TextChoices):
        COMPANY = "COMPANY"
        SOLE_TRADER = "SOLE_TRADER"
        PARTNERSHIP = "PARTNERSHIP"
        HOUSEHOLD = "HOUSEHOLD"

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        ARCHIVED = "ARCHIVED"

    legal_name = models.CharField(max_length=200)
    entity_type = models.CharField(max_length=16, choices=EntityType.choices)
    registration_no = models.CharField(max_length=64, blank=True)
    jurisdiction = models.CharField(max_length=2, default="CY")
    functional_currency = models.CharField(max_length=3, default="EUR")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "tenancy_legal_entity"

    def __str__(self) -> str:
        return str(self.id)


class Membership(TenantOwned):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE"
        SUSPENDED = "SUSPENDED"
        REMOVED = "REMOVED"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        db_table = "tenancy_membership"
        constraints = [
            models.UniqueConstraint(fields=["tenant", "user"], name="tenancy_membership_unique")
        ]


class RoleAssignment(TenantOwned):
    """A role for a member, either workspace-wide (legal_entity is NULL) or for one entity."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="roles")
    role_key = models.CharField(max_length=32)
    legal_entity = models.ForeignKey(
        LegalEntity, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    valid_until = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "tenancy_role_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "role_key", "legal_entity"],
                name="tenancy_role_assignment_unique",
                nulls_distinct=False,
            )
        ]


class Invitation(TenantOwned):
    email = models.EmailField(max_length=320)
    role_key = models.CharField(max_length=32)
    legal_entity = models.ForeignKey(
        LegalEntity, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "tenancy_invitation"


class Engagement(TenantOwned):
    """A client-owned workspace's grant to a firm (M5-4, doc 11 §3), stored in the **client's**
    workspace. The firm's staff act inside the client's workspace with the intersection of
    ``scope_roles`` and their firm role, until ``valid_until`` or revocation. A grant never
    changes; it can only be revoked (database trigger). The firm is referenced by ID only: no
    foreign key and no query crosses workspaces."""

    firm_tenant_id = models.UUIDField()
    firm_name = models.CharField(max_length=200)  # as it was when granted
    scope_roles = models.JSONField(default=list)  # e.g. ["accountant", "read_only"]
    legal_entity = models.ForeignKey(
        LegalEntity, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )  # NULL: every legal entity of the client
    valid_until = models.DateTimeField()
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        db_table = "tenancy_engagement"


class EngagementStaff(TenantOwned):
    """A firm member assigned to an engagement, stored in the **firm's** workspace. Assignments
    are removed, never edited or deleted (database trigger)."""

    engagement_id = models.UUIDField()  # tenancy_engagement in the client's workspace
    client_tenant_id = models.UUIDField()
    membership = models.ForeignKey(Membership, on_delete=models.PROTECT, related_name="+")
    added_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+"
    )
    removed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tenancy_engagement_staff"
        constraints = [
            models.UniqueConstraint(
                fields=["engagement_id", "membership"],
                condition=models.Q(removed_at__isnull=True),
                name="tenancy_engagement_staff_once",
            )
        ]


class WorkspaceDeletion(models.Model):
    """The deletion of a workspace (M5-6): requested, confirmed by an owner, then purged after a
    grace period; or cancelled before that. This row outlives the workspace it describes, so it
    is a global table and holds only IDs, dates and row counts (no names, no financial data)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField()
    tenant_kind = models.CharField(max_length=16)
    requested_by_id = models.UUIDField()
    requested_at = models.DateTimeField(auto_now_add=True)
    confirmed_by_id = models.UUIDField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    purge_after = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    purged_at = models.DateTimeField(null=True, blank=True)
    purged_rows = models.JSONField(default=dict)  # table -> rows deleted
    purged_files = models.JSONField(default=dict)  # {"deleted": n, "retained": n}

    class Meta:
        db_table = "tenancy_workspace_deletion"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant_id"],
                condition=models.Q(cancelled_at__isnull=True),
                name="tenancy_workspace_deletion_one_open",
            )
        ]
