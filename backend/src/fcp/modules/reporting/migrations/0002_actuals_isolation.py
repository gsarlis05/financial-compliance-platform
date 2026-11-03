"""Isolation for the actuals read model: FORCE RLS, composite tenant keys, and accounts kept
inside the same legal entity (composite FK to ledger_account (legal_entity_id, id))."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation


def _same_entity(table: str) -> migrations.RunSQL:
    return migrations.RunSQL(
        f"ALTER TABLE {table} ADD CONSTRAINT {table}_account_same_entity "
        "FOREIGN KEY (legal_entity_id, account_id) REFERENCES ledger_account (legal_entity_id, id)",
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {table}_account_same_entity",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("reporting", "0001_actuals"),
        ("ledger", "0014_vat_seed_and_rules"),
        ("tenancy", "0003_tenant_ids_function"),
    ]

    operations = [
        *tenant_isolation("reporting_fact_monthly"),
        *tenant_isolation("reporting_fact_daily"),
        *tenant_isolation("reporting_actuals_state"),
        composite_tenant_fk("reporting_fact_monthly", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("reporting_fact_daily", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("reporting_fact_monthly", "account_id", "ledger_account"),
        composite_tenant_fk("reporting_fact_daily", "account_id", "ledger_account"),
        _same_entity("reporting_fact_monthly"),
        _same_entity("reporting_fact_daily"),
    ]
