"""Isolation for capital allowance classes; an asset's allowance class may change after lock
(M6F-3, #148).

- Allowance classes: FORCE row-level security, composite tenant key to the legal entity, never
  changed or deleted (a new rate is a new version).
- The fixed-asset guard keeps every accounting term locked once depreciation is prepared, but the
  allowance class (tax data, kept apart from accounting) can still be set or corrected; the change
  is audited by the service.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

SQL = r"""
CREATE OR REPLACE FUNCTION assets_allowance_class_kept() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'allowance classes are never changed or deleted; add a new version'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER assets_allowance_class_kept BEFORE UPDATE OR DELETE ON assets_allowance_class
    FOR EACH ROW EXECUTE FUNCTION assets_allowance_class_kept();

CREATE OR REPLACE FUNCTION assets_fixed_asset_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    free CONSTANT text[] := ARRAY['disposed_on', 'disposal_proceeds', 'allowance_class_code'];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'fixed assets are kept; record a disposal instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.locked_at IS NOT NULL THEN
        IF NEW.locked_at IS DISTINCT FROM OLD.locked_at
           OR (to_jsonb(NEW) - free) IS DISTINCT FROM (to_jsonb(OLD) - free)
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
"""
REVERSE = """
DROP TRIGGER IF EXISTS assets_allowance_class_kept ON assets_allowance_class;
DROP FUNCTION IF EXISTS assets_allowance_class_kept();
"""


class Migration(migrations.Migration):
    dependencies = [("assets", "0003_commencement_allowances")]
    operations = [
        *tenant_isolation("assets_allowance_class"),
        composite_tenant_fk("assets_allowance_class", "legal_entity_id", "tenancy_legal_entity"),
        migrations.RunSQL(SQL, REVERSE),
    ]
