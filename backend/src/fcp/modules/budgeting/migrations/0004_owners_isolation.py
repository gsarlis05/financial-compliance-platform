"""Isolation for department budget owners (M4-2): FORCE row-level security, composite tenant
keys, and the budget and dimension value belong to the owner row's legal entity."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLE = "budgeting_owner"


def _same_entity(column: str, ref: str) -> migrations.RunSQL:
    name = f"{TABLE}_{column}_same_entity"
    return migrations.RunSQL(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {name} FOREIGN KEY (legal_entity_id, {column}) "
        f"REFERENCES {ref} (legal_entity_id, id)",
        reverse_sql=f"ALTER TABLE {TABLE} DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("budgeting", "0003_owners"),
    ]

    operations = [
        *tenant_isolation(TABLE),
        composite_tenant_fk(TABLE, "legal_entity_id", "tenancy_legal_entity"),
        _same_entity("budget_id", "budgeting_budget"),
        _same_entity("dimension_value_id", "ledger_dimension_value"),
    ]
