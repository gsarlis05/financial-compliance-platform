"""Isolation and history of tax payments (M3-5): FORCE row-level security, composite tenant
keys, and the same version guard as obligations and loans (supersede only, never delete)."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLE = "registers_tax_payment"


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("registers", "0007_tax_payments"),
    ]

    operations = [
        *tenant_isolation(TABLE),
        composite_tenant_fk(TABLE, "legal_entity_id", "tenancy_legal_entity"),
        migrations.RunSQL(
            f"CREATE TRIGGER {TABLE}_guard BEFORE UPDATE OR DELETE ON {TABLE} "
            "FOR EACH ROW EXECUTE FUNCTION registers_version_guard();",
            reverse_sql=f"DROP TRIGGER IF EXISTS {TABLE}_guard ON {TABLE};",
        ),
    ]
