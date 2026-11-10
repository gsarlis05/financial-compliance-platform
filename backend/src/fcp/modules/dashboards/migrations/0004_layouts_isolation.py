"""FORCE row-level security and composite tenant keys on dashboard layouts (M4-8)."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("dashboards", "0003_layouts"),
    ]

    operations = [
        *tenant_isolation("dashboards_layout"),
        composite_tenant_fk("dashboards_layout", "legal_entity_id", "tenancy_legal_entity"),
    ]
