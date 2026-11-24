"""Isolation for counterparties: FORCE row-level security and composite tenant foreign keys."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("registers", "0001_counterparty"),
    ]

    operations = [
        *tenant_isolation("registers_counterparty"),
        composite_tenant_fk("registers_counterparty", "legal_entity_id", "tenancy_legal_entity"),
        migrations.RunSQL(
            "ALTER TABLE registers_counterparty ADD CONSTRAINT registers_counterparty_entity_id_key "
            "UNIQUE (legal_entity_id, id)",
            reverse_sql="ALTER TABLE registers_counterparty "
            "DROP CONSTRAINT registers_counterparty_entity_id_key",
        ),
    ]
