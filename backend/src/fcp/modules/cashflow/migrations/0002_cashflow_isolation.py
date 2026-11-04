"""FORCE row-level security and composite tenant keys for forecast settings and manual items."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("cashflow_settings", "cashflow_manual_item")


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("cashflow", "0001_forecast_settings"),
    ]

    operations = [
        *[op for table in TABLES for op in tenant_isolation(table)],
        *[
            composite_tenant_fk(table, "legal_entity_id", "tenancy_legal_entity")
            for table in TABLES
        ],
    ]
