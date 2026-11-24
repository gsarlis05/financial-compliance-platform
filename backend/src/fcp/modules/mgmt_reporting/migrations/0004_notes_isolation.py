"""Isolation and history for commentary and risks (M8-2), enforced by the database.

- FORCE row-level security and composite tenant keys (each row's pack).
- Append-only: a change adds a row; nothing is updated or deleted.
- Rows are added only while their pack is a draft, so a pack in review, final or superseded keeps
  exactly the commentary and risks it was reviewed with.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

GUARDS = r"""
CREATE OR REPLACE FUNCTION mgmt_reporting_note_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE
    pack_status text;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'commentary and risks are append-only; add a new row instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    SELECT status INTO pack_status FROM mgmt_reporting_pack WHERE id = NEW.pack_id;
    IF pack_status IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'commentary and risks change only while the pack is a draft'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER mgmt_reporting_comment_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mgmt_reporting_comment
    FOR EACH ROW EXECUTE FUNCTION mgmt_reporting_note_guard();
CREATE TRIGGER mgmt_reporting_risk_guard
    BEFORE INSERT OR UPDATE OR DELETE ON mgmt_reporting_risk
    FOR EACH ROW EXECUTE FUNCTION mgmt_reporting_note_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS mgmt_reporting_risk_guard ON mgmt_reporting_risk;
DROP TRIGGER IF EXISTS mgmt_reporting_comment_guard ON mgmt_reporting_comment;
DROP FUNCTION IF EXISTS mgmt_reporting_note_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("mgmt_reporting", "0003_notes"),
    ]

    operations = [
        *tenant_isolation("mgmt_reporting_comment"),
        *tenant_isolation("mgmt_reporting_risk"),
        composite_tenant_fk("mgmt_reporting_comment", "pack_id", "mgmt_reporting_pack"),
        composite_tenant_fk("mgmt_reporting_risk", "pack_id", "mgmt_reporting_pack"),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
