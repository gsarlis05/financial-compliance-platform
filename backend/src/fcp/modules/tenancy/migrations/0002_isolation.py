"""Row-level security and composite tenant foreign keys for the tenancy tables (ADR-0002)."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, enable_rls, tenant_isolation

# A workspace row is visible when it is the current tenant, or the current user is an active
# member of it (needed to list "my workspaces" before a workspace is selected).
TENANT_VISIBLE = """
    id = app_current_tenant()
    OR EXISTS (
        SELECT 1 FROM tenancy_membership m
        WHERE m.tenant_id = tenancy_tenant.id
          AND m.user_id = app_current_user()
          AND m.status = 'ACTIVE'
    )
"""

# Memberships are visible inside their workspace, and to the member themself (for the list of
# their workspaces). They can only be written inside the current workspace.
MEMBERSHIP_VISIBLE = "tenant_id = app_current_tenant() OR user_id = app_current_user()"


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0001_initial"),
    ]

    operations = [
        enable_rls("tenancy_tenant", TENANT_VISIBLE, check="id = app_current_tenant()"),
        *tenant_isolation("tenancy_legal_entity"),
        migrations.RunSQL(
            "ALTER TABLE tenancy_membership ADD CONSTRAINT tenancy_membership_tenant_id_key "
            "UNIQUE (tenant_id, id)",
            reverse_sql="ALTER TABLE tenancy_membership DROP CONSTRAINT "
            "tenancy_membership_tenant_id_key",
        ),
        enable_rls(
            "tenancy_membership", MEMBERSHIP_VISIBLE, check="tenant_id = app_current_tenant()"
        ),
        *tenant_isolation("tenancy_role_assignment"),
        *tenant_isolation("tenancy_invitation"),
        composite_tenant_fk("tenancy_role_assignment", "membership_id", "tenancy_membership"),
        composite_tenant_fk("tenancy_role_assignment", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("tenancy_invitation", "legal_entity_id", "tenancy_legal_entity"),
    ]
