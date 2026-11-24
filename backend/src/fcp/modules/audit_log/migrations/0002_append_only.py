"""Row-level security and append-only enforcement for the audit tables."""

from django.db import migrations

from fcp.core.db.operations import enable_rls, tenant_isolation

APPEND_ONLY = """
CREATE OR REPLACE FUNCTION audit_log_reject_change() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    RAISE EXCEPTION 'audit events are append-only (% rejected)', TG_OP
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_log_event_append_only
    BEFORE UPDATE OR DELETE ON audit_log_event
    FOR EACH ROW EXECUTE FUNCTION audit_log_reject_change();

-- TRUNCATE is already revoked from the runtime role. The test suite's database (and only it)
-- sets fcp.allow_audit_truncate=on so Django can reset tables between transactional tests.
CREATE OR REPLACE FUNCTION audit_log_reject_truncate() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF current_setting('fcp.allow_audit_truncate', true) = 'on' THEN
        RETURN NULL;
    END IF;
    RAISE EXCEPTION 'audit events are append-only (TRUNCATE rejected)'
        USING ERRCODE = 'insufficient_privilege';
END;
$$;

CREATE TRIGGER audit_log_event_no_truncate
    BEFORE TRUNCATE ON audit_log_event
    FOR EACH STATEMENT EXECUTE FUNCTION audit_log_reject_truncate();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_log_event_no_truncate ON audit_log_event;
DROP TRIGGER IF EXISTS audit_log_event_append_only ON audit_log_event;
DROP FUNCTION IF EXISTS audit_log_reject_change();
DROP FUNCTION IF EXISTS audit_log_reject_truncate();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("audit_log", "0001_initial"),
    ]

    operations = [
        *tenant_isolation("audit_log_event"),
        enable_rls("audit_log_chain_head", "tenant_id = app_current_tenant()"),
        migrations.RunSQL(APPEND_ONLY, reverse_sql=REVERSE),
    ]
