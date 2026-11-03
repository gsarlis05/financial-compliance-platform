"""Isolation and integrity constraints for the chart of accounts and fiscal calendar."""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

SQL = [
    # Keep hierarchy and periods inside one legal entity, structurally.
    "ALTER TABLE ledger_account ADD CONSTRAINT ledger_account_entity_id_key "
    "UNIQUE (legal_entity_id, id)",
    "ALTER TABLE ledger_account ADD CONSTRAINT ledger_account_parent_same_entity "
    "FOREIGN KEY (legal_entity_id, parent_id) REFERENCES ledger_account (legal_entity_id, id)",
    "ALTER TABLE ledger_fiscal_year ADD CONSTRAINT ledger_fiscal_year_entity_id_key "
    "UNIQUE (legal_entity_id, id)",
    "ALTER TABLE ledger_period ADD CONSTRAINT ledger_period_year_same_entity "
    "FOREIGN KEY (legal_entity_id, fiscal_year_id) "
    "REFERENCES ledger_fiscal_year (legal_entity_id, id)",
    # Fiscal years of one entity never overlap.
    "CREATE EXTENSION IF NOT EXISTS btree_gist",
    "ALTER TABLE ledger_fiscal_year ADD CONSTRAINT ledger_fiscal_year_no_overlap "
    "EXCLUDE USING gist (legal_entity_id WITH =, daterange(start_date, end_date, '[]') WITH &&)",
]

REVERSE = [
    "ALTER TABLE ledger_fiscal_year DROP CONSTRAINT ledger_fiscal_year_no_overlap",
    "ALTER TABLE ledger_period DROP CONSTRAINT ledger_period_year_same_entity",
    "ALTER TABLE ledger_fiscal_year DROP CONSTRAINT ledger_fiscal_year_entity_id_key",
    "ALTER TABLE ledger_account DROP CONSTRAINT ledger_account_parent_same_entity",
    "ALTER TABLE ledger_account DROP CONSTRAINT ledger_account_entity_id_key",
]


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("ledger", "0001_initial"),
    ]

    operations = [
        *tenant_isolation("ledger_account"),
        *tenant_isolation("ledger_fiscal_year"),
        *tenant_isolation("ledger_period"),
        composite_tenant_fk("ledger_account", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_fiscal_year", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_period", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("ledger_period", "fiscal_year_id", "ledger_fiscal_year"),
        migrations.RunSQL(SQL, reverse_sql=REVERSE),
    ]
