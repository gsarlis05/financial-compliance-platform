"""Shared model base classes (no concrete models).

This module also makes Django send this app the post_migrate signal (Django skips apps without a
models module), which applies the runtime-role grants after every migration.
"""

from django.db import models

from fcp.core.ids import uuid7


class TenantOwned(models.Model):
    """Base for tenant-owned rows. ``tenant`` is always set from the request context, and the
    table must get ``tenant_isolation(...)`` (RLS) in its migration."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # Referenced by label so the shared kernel never imports a module.
    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
