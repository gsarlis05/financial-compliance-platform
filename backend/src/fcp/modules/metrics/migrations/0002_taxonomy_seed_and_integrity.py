"""Seed the taxonomy; isolate and protect account mappings (M2-6).

- FORCE row-level security and composite tenant keys on ``metrics_account_taxonomy_map``.
- The mapped account must exist in the same tenant AND the same legal entity (composite FK to
  ``ledger_account (legal_entity_id, id)``), although the code refers to it by key only (ADR-0007).
- Mapping history is append-only: rows are never deleted, and the only allowed update is marking
  the current row superseded (once).
"""

from typing import Any

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation
from fcp.modules.metrics.taxonomy import seed_taxonomies


def seed(apps: Any, schema_editor: Any) -> None:
    del schema_editor
    seed_taxonomies(apps.get_model("metrics", "TaxonomyVersion"),
                    apps.get_model("metrics", "TaxonomyLine"))  # fmt: skip


GUARD = r"""
CREATE OR REPLACE FUNCTION metrics_map_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'account mapping history is kept; supersede instead of deleting'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.superseded_at IS NOT NULL
       OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'account mappings are append-only; only superseding is allowed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER metrics_map_guard
    BEFORE UPDATE OR DELETE ON metrics_account_taxonomy_map
    FOR EACH ROW EXECUTE FUNCTION metrics_map_guard();
"""

GUARD_REVERSE = """
DROP TRIGGER IF EXISTS metrics_map_guard ON metrics_account_taxonomy_map;
DROP FUNCTION IF EXISTS metrics_map_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("metrics", "0001_taxonomy"),
        ("ledger", "0014_vat_seed_and_rules"),
        ("tenancy", "0003_tenant_ids_function"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        *tenant_isolation("metrics_account_taxonomy_map"),
        composite_tenant_fk(
            "metrics_account_taxonomy_map", "legal_entity_id", "tenancy_legal_entity"
        ),
        composite_tenant_fk("metrics_account_taxonomy_map", "account_id", "ledger_account"),
        migrations.RunSQL(
            "ALTER TABLE metrics_account_taxonomy_map ADD CONSTRAINT metrics_map_account_same_entity "
            "FOREIGN KEY (legal_entity_id, account_id) "
            "REFERENCES ledger_account (legal_entity_id, id)",
            reverse_sql="ALTER TABLE metrics_account_taxonomy_map "
            "DROP CONSTRAINT metrics_map_account_same_entity",
        ),
        migrations.RunSQL(GUARD, reverse_sql=GUARD_REVERSE),
    ]
