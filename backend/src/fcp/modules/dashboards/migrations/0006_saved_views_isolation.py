"""FORCE row-level security and composite tenant keys on saved dashboard views (M8-4)."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation


class Migration(migrations.Migration):
    dependencies = [
        ("dashboards", "0005_saved_views"),
    ]

    operations = [
        *tenant_isolation("dashboards_saved_view"),
        composite_tenant_fk("dashboards_saved_view", "legal_entity_id", "tenancy_legal_entity"),
    ]
