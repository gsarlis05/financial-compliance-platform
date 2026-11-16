"""Workspaces (tenants), legal entities, memberships, role assignments and invitations
(docs/planning/03 §1 and §6, 11 §2).

Every table except ``tenancy_tenant`` carries ``tenant_id`` and is protected by FORCE row-level
security plus composite (tenant_id, id) foreign keys (see migration 0001).
"""

from django.conf import settings
from django.db import models

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


class TenantOwned(models.Model):
    """Base for tenant-owned rows. ``tenant`` is always set from the request context."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


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
