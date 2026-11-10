"""Isolation and history for counterpart hints (M5-3), enforced by the database.

- FORCE row-level security and composite tenant keys. The link's personal account and category
  belong to the same legal entity; a decision belongs to a link of the same workspace.
- A link never changes; it can only be revoked, once. Nothing is deleted.
- Decisions are append-only (trigger, and runtime role grants: INSERT and SELECT only).
- The business references are plain IDs: there is no foreign key, and no query, across
  workspaces.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("personal_counterpart_link", "personal_counterpart_decision")

GUARDS = r"""
CREATE OR REPLACE FUNCTION personal_counterpart_link_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'links are kept; revoke a link instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
       OR (to_jsonb(NEW) - 'revoked_at') IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at') THEN
        RAISE EXCEPTION 'a link can only be revoked; a different link is a new one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER personal_counterpart_link_guard
    BEFORE UPDATE OR DELETE ON personal_counterpart_link
    FOR EACH ROW EXECUTE FUNCTION personal_counterpart_link_guard();

CREATE OR REPLACE FUNCTION personal_counterpart_decision_append_only() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'counterpart decisions are append-only'
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER personal_counterpart_decision_append_only
    BEFORE UPDATE OR DELETE ON personal_counterpart_decision
    FOR EACH ROW EXECUTE FUNCTION personal_counterpart_decision_append_only();
"""

REVERSE = """
DROP TRIGGER IF EXISTS personal_counterpart_decision_append_only ON personal_counterpart_decision;
DROP FUNCTION IF EXISTS personal_counterpart_decision_append_only();
DROP TRIGGER IF EXISTS personal_counterpart_link_guard ON personal_counterpart_link;
DROP FUNCTION IF EXISTS personal_counterpart_link_guard();
"""


def _same_entity(column: str, name: str) -> migrations.RunSQL:
    return migrations.RunSQL(
        f"ALTER TABLE personal_counterpart_link ADD CONSTRAINT {name} "
        f"FOREIGN KEY (legal_entity_id, {column}) REFERENCES ledger_account (legal_entity_id, id)",
        f"ALTER TABLE personal_counterpart_link DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("personal", "0005_counterpart"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        composite_tenant_fk("personal_counterpart_link", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk(
            "personal_counterpart_decision", "link_id", "personal_counterpart_link"
        ),
        _same_entity("account_id", "personal_counterpart_account_same_entity"),
        _same_entity("category_id", "personal_counterpart_category_same_entity"),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
