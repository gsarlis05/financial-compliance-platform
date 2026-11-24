"""Isolation, history and narrow lookups for engagement grants (M5-4, doc 11 §3).

- FORCE row-level security and composite tenant keys on both tables. An engagement lives in the
  client's workspace; a staff assignment lives in the firm's workspace.
- An engagement can only be revoked, once; a staff assignment can only be removed, once.
  Nothing is deleted (triggers).
- No query of the application crosses workspaces. Four SECURITY DEFINER functions, owned by the
  NOLOGIN ``fcp_maintenance`` role, answer narrow questions and return only what the caller is
  entitled to:
  - ``app_firm_lookup(slug)``: the ID and name of an active firm workspace, so a client can grant
    it (the firm shares its address);
  - ``app_firm_engagements()``: the active grants made **to the current firm workspace**;
  - ``app_engagement_access(slug)``: the current user's own access to a client workspace through
    engagements they are assigned to (the engagement scope and their own firm roles);
  - ``app_engaged_workspaces()``: the client workspaces the current user can reach that way, and
    through which firm.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("tenancy_engagement", "tenancy_engagement_staff")

GUARDS = r"""
CREATE OR REPLACE FUNCTION tenancy_engagement_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'engagements are kept; revoke an engagement instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.revoked_at IS NOT NULL OR NEW.revoked_at IS NULL
       OR (to_jsonb(NEW) - 'revoked_at' - 'revoked_by_id')
          IS DISTINCT FROM (to_jsonb(OLD) - 'revoked_at' - 'revoked_by_id') THEN
        RAISE EXCEPTION 'an engagement can only be revoked; a different scope is a new grant'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tenancy_engagement_guard BEFORE UPDATE OR DELETE ON tenancy_engagement
    FOR EACH ROW EXECUTE FUNCTION tenancy_engagement_guard();

CREATE OR REPLACE FUNCTION tenancy_engagement_staff_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'staff assignments are kept; remove the assignment instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.removed_at IS NOT NULL OR NEW.removed_at IS NULL
       OR (to_jsonb(NEW) - 'removed_at') IS DISTINCT FROM (to_jsonb(OLD) - 'removed_at') THEN
        RAISE EXCEPTION 'a staff assignment can only be removed'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER tenancy_engagement_staff_guard BEFORE UPDATE OR DELETE ON tenancy_engagement_staff
    FOR EACH ROW EXECUTE FUNCTION tenancy_engagement_staff_guard();
"""

GUARDS_REVERSE = """
DROP TRIGGER IF EXISTS tenancy_engagement_staff_guard ON tenancy_engagement_staff;
DROP FUNCTION IF EXISTS tenancy_engagement_staff_guard();
DROP TRIGGER IF EXISTS tenancy_engagement_guard ON tenancy_engagement;
DROP FUNCTION IF EXISTS tenancy_engagement_guard();
"""

FUNCTIONS = r"""
CREATE OR REPLACE FUNCTION app_firm_lookup(p_slug text)
    RETURNS TABLE (id uuid, name text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT t.id, t.name::text FROM tenancy_tenant t
   WHERE t.slug = p_slug AND t.kind = 'FIRM' AND t.status = 'ACTIVE' $$;

CREATE OR REPLACE FUNCTION app_firm_engagements()
    RETURNS TABLE (engagement_id uuid, client_tenant_id uuid, client_slug text, client_name text,
                   client_kind text, scope_roles jsonb, legal_entity_id uuid,
                   valid_until timestamptz)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT e.id, c.id, c.slug::text, c.name::text, c.kind::text, e.scope_roles, e.legal_entity_id,
          e.valid_until
   FROM tenancy_engagement e JOIN tenancy_tenant c ON c.id = e.tenant_id
   WHERE e.firm_tenant_id = app_current_tenant() AND app_current_tenant() IS NOT NULL
     AND e.revoked_at IS NULL AND e.valid_until > now() AND c.status = 'ACTIVE'
   ORDER BY c.name, e.id $$;

CREATE OR REPLACE FUNCTION app_engagement_access(p_slug text)
    RETURNS TABLE (client_tenant_id uuid, engagement_id uuid, firm_tenant_id uuid,
                   firm_name text, scope_roles jsonb, legal_entity_id uuid, firm_role text)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT c.id, e.id, e.firm_tenant_id, e.firm_name::text, e.scope_roles, e.legal_entity_id,
          r.role_key::text
   FROM tenancy_tenant c
   JOIN tenancy_engagement e ON e.tenant_id = c.id
   JOIN tenancy_tenant f ON f.id = e.firm_tenant_id
   JOIN tenancy_engagement_staff s
        ON s.tenant_id = e.firm_tenant_id AND s.engagement_id = e.id AND s.client_tenant_id = c.id
   JOIN tenancy_membership m ON m.id = s.membership_id AND m.tenant_id = s.tenant_id
   JOIN tenancy_role_assignment r ON r.membership_id = m.id AND r.tenant_id = m.tenant_id
   WHERE c.slug = p_slug AND c.status = 'ACTIVE' AND f.status = 'ACTIVE'
     AND e.revoked_at IS NULL AND e.valid_until > now()
     AND s.removed_at IS NULL
     AND m.user_id = app_current_user() AND app_current_user() IS NOT NULL
     AND m.status = 'ACTIVE'
     AND r.legal_entity_id IS NULL AND (r.valid_until IS NULL OR r.valid_until > now())
   ORDER BY e.id, r.role_key $$;

CREATE OR REPLACE FUNCTION app_engaged_workspaces()
    RETURNS TABLE (id uuid, slug text, name text, kind text, firm_tenant_id uuid)
    LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
$$ SELECT DISTINCT c.id, c.slug::text, c.name::text, c.kind::text, e.firm_tenant_id
   FROM tenancy_tenant c
   JOIN tenancy_engagement e ON e.tenant_id = c.id
   JOIN tenancy_tenant f ON f.id = e.firm_tenant_id
   JOIN tenancy_engagement_staff s
        ON s.tenant_id = e.firm_tenant_id AND s.engagement_id = e.id AND s.client_tenant_id = c.id
   JOIN tenancy_membership m ON m.id = s.membership_id AND m.tenant_id = s.tenant_id
   WHERE c.status = 'ACTIVE' AND f.status = 'ACTIVE'
     AND e.revoked_at IS NULL AND e.valid_until > now() AND s.removed_at IS NULL
     AND m.user_id = app_current_user() AND app_current_user() IS NOT NULL
     AND m.status = 'ACTIVE' $$;

REVOKE ALL ON FUNCTION app_firm_lookup(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_firm_engagements() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_engagement_access(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_engaged_workspaces() FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fcp_maintenance') THEN
        GRANT SELECT (id, slug, name, kind, status) ON tenancy_tenant TO fcp_maintenance;
        GRANT SELECT (id, tenant_id, firm_tenant_id, firm_name, scope_roles, legal_entity_id,
                      valid_until, revoked_at) ON tenancy_engagement TO fcp_maintenance;
        GRANT SELECT (tenant_id, engagement_id, client_tenant_id, membership_id, removed_at)
            ON tenancy_engagement_staff TO fcp_maintenance;
        GRANT SELECT (id, tenant_id, user_id, status) ON tenancy_membership TO fcp_maintenance;
        GRANT SELECT (tenant_id, membership_id, role_key, legal_entity_id, valid_until)
            ON tenancy_role_assignment TO fcp_maintenance;
        -- A new owner needs CREATE on the schema while ownership changes; revoked right after.
        GRANT CREATE ON SCHEMA public TO fcp_maintenance;
        ALTER FUNCTION app_firm_lookup(text) OWNER TO fcp_maintenance;
        ALTER FUNCTION app_firm_engagements() OWNER TO fcp_maintenance;
        ALTER FUNCTION app_engagement_access(text) OWNER TO fcp_maintenance;
        ALTER FUNCTION app_engaged_workspaces() OWNER TO fcp_maintenance;
        REVOKE CREATE ON SCHEMA public FROM fcp_maintenance;
    END IF;
END $$;
"""

FUNCTIONS_REVERSE = """
DROP FUNCTION IF EXISTS app_engaged_workspaces();
DROP FUNCTION IF EXISTS app_engagement_access(text);
DROP FUNCTION IF EXISTS app_firm_engagements();
DROP FUNCTION IF EXISTS app_firm_lookup(text);
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0004_engagements"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        composite_tenant_fk("tenancy_engagement", "legal_entity_id", "tenancy_legal_entity"),
        composite_tenant_fk("tenancy_engagement_staff", "membership_id", "tenancy_membership"),
        migrations.RunSQL(GUARDS, GUARDS_REVERSE),
        migrations.RunSQL(FUNCTIONS, FUNCTIONS_REVERSE),
    ]
