"""Isolation for variance explanations and period reviews (M4-3): FORCE row-level security,
composite tenant keys, and every row stays inside its legal entity (same-entity foreign keys).
Both tables are append-only for the runtime role (registry)."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("budgeting_explanation", "budgeting_review")


def _same_entity(table: str, column: str, ref: str) -> migrations.RunSQL:
    name = f"{table}_{column}_same_entity"
    return migrations.RunSQL(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (legal_entity_id, {column}) "
        f"REFERENCES {ref} (legal_entity_id, id)",
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("budgeting", "0005_variance"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity") for t in TABLES],
        _same_entity("budgeting_explanation", "version_id", "budgeting_version"),
        _same_entity("budgeting_explanation", "line_id", "budgeting_line"),
        _same_entity("budgeting_review", "version_id", "budgeting_version"),
    ]
