"""Isolation and history for the fixed-asset register (M6-1), enforced by the database.

- FORCE row-level security and composite tenant keys. An asset's three accounts belong to its
  legal entity.
- An asset is never deleted. Its terms can be corrected only until depreciation has been prepared
  for it (``locked_at``); after that only the disposal can be recorded, once.
- A depreciation run can only be cancelled (its entry was voided or rejected), once; its lines
  never change.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("assets_fixed_asset", "assets_depreciation_run", "assets_depreciation_run_line")

GUARDS = r"""
CREATE OR REPLACE FUNCTION assets_fixed_asset_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'fixed assets are kept; record a disposal instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.locked_at IS NOT NULL THEN
        IF NEW.locked_at IS DISTINCT FROM OLD.locked_at
           OR (to_jsonb(NEW) - 'disposed_on' - 'disposal_proceeds')
              IS DISTINCT FROM (to_jsonb(OLD) - 'disposed_on' - 'disposal_proceeds')
           OR (OLD.disposed_on IS NOT NULL
               AND (NEW.disposed_on IS DISTINCT FROM OLD.disposed_on
                    OR NEW.disposal_proceeds IS DISTINCT FROM OLD.disposal_proceeds)) THEN
            RAISE EXCEPTION 'depreciation was prepared for this asset: its terms are locked'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER assets_fixed_asset_guard BEFORE UPDATE OR DELETE ON assets_fixed_asset
    FOR EACH ROW EXECUTE FUNCTION assets_fixed_asset_guard();

CREATE OR REPLACE FUNCTION assets_depreciation_run_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'depreciation runs are kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.cancelled_at IS NOT NULL OR NEW.cancelled_at IS NULL
       OR (to_jsonb(NEW) - 'cancelled_at') IS DISTINCT FROM (to_jsonb(OLD) - 'cancelled_at') THEN
        RAISE EXCEPTION 'a depreciation run can only be cancelled'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER assets_depreciation_run_guard BEFORE UPDATE OR DELETE ON assets_depreciation_run
    FOR EACH ROW EXECUTE FUNCTION assets_depreciation_run_guard();

CREATE OR REPLACE FUNCTION assets_run_line_append_only() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'depreciation run lines are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER assets_run_line_append_only BEFORE UPDATE OR DELETE ON assets_depreciation_run_line
    FOR EACH ROW EXECUTE FUNCTION assets_run_line_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS assets_run_line_append_only ON assets_depreciation_run_line;
DROP FUNCTION IF EXISTS assets_run_line_append_only();
DROP TRIGGER IF EXISTS assets_depreciation_run_guard ON assets_depreciation_run;
DROP FUNCTION IF EXISTS assets_depreciation_run_guard();
DROP TRIGGER IF EXISTS assets_fixed_asset_guard ON assets_fixed_asset;
DROP FUNCTION IF EXISTS assets_fixed_asset_guard();
"""


def _same_entity(column: str) -> migrations.RunSQL:
    name = f"assets_{column.removesuffix('_account_id')}_account_same_entity"
    return migrations.RunSQL(
        f"ALTER TABLE assets_fixed_asset ADD CONSTRAINT {name} FOREIGN KEY (legal_entity_id, "
        f"{column}) REFERENCES ledger_account (legal_entity_id, id)",
        f"ALTER TABLE assets_fixed_asset DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("ledger", "0002_isolation"),
        ("assets", "0001_initial"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        composite_tenant_fk("assets_fixed_asset", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("assets_depreciation_run", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("assets_depreciation_run_line", "run_id", "assets_depreciation_run"),
        composite_tenant_fk("assets_depreciation_run_line", "asset_id", "assets_fixed_asset"),
        *[
            _same_entity(c)
            for c in ("asset_account_id", "accumulated_account_id", "expense_account_id")
        ],
        migrations.RunSQL(GUARDS, REVERSE),
    ]
