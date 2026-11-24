"""One-person workspaces (version 1, V1-1, #207).

``tenancy_one_person(tid)`` is true only while the workspace's setting is on **and** it has
exactly one active member and no active engagement grant. Other modules' triggers call
``tenancy_self_approval_guard()``: a row may be marked ``self_approved`` only when that holds.

Guards, so the setting can never be true for a workspace that more than one person can use:
- turning it on is refused while there is a second active member, a pending invitation or an
  active engagement grant;
- while it is on, a second active membership, a new invitation and a new engagement grant are
  refused.

The functions run with the caller's rights, under its row-level security context: in another
workspace's context they see no members and return false.
"""

from django.db import migrations, models

SQL = """
CREATE OR REPLACE FUNCTION tenancy_one_person(tid uuid) RETURNS boolean
    LANGUAGE sql STABLE SET search_path = public AS
$$ SELECT COALESCE((SELECT one_person FROM tenancy_tenant WHERE id = tid), false)
      AND (SELECT count(*) FROM tenancy_membership
           WHERE tenant_id = tid AND status = 'ACTIVE') = 1
      AND NOT EXISTS (SELECT 1 FROM tenancy_engagement
                      WHERE tenant_id = tid AND revoked_at IS NULL AND valid_until > now()) $$;

CREATE OR REPLACE FUNCTION tenancy_self_approval_guard() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public AS
$$
BEGIN
    IF NEW.self_approved AND NOT tenancy_one_person(NEW.tenant_id) THEN
        RAISE EXCEPTION 'a self-approval is allowed only in a one-person workspace'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION tenancy_one_person_switch() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public AS
$$
BEGIN
    IF NEW.one_person AND NOT OLD.one_person THEN
        IF (SELECT count(*) FROM tenancy_membership
            WHERE tenant_id = NEW.id AND status = 'ACTIVE') <> 1 THEN
            RAISE EXCEPTION 'a one-person workspace must have exactly one active member'
                USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (SELECT 1 FROM tenancy_invitation WHERE tenant_id = NEW.id
                   AND accepted_at IS NULL AND expires_at > now()) THEN
            RAISE EXCEPTION 'a one-person workspace cannot have a pending invitation'
                USING ERRCODE = 'check_violation';
        END IF;
        IF EXISTS (SELECT 1 FROM tenancy_engagement WHERE tenant_id = NEW.id
                   AND revoked_at IS NULL AND valid_until > now()) THEN
            RAISE EXCEPTION 'a one-person workspace cannot have an active engagement grant'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE OR REPLACE FUNCTION tenancy_one_person_closed() RETURNS trigger
    LANGUAGE plpgsql SET search_path = public AS
$$
BEGIN
    IF COALESCE((SELECT one_person FROM tenancy_tenant WHERE id = NEW.tenant_id), false) THEN
        IF TG_TABLE_NAME <> 'tenancy_membership' OR (NEW.status = 'ACTIVE' AND EXISTS (
                SELECT 1 FROM tenancy_membership WHERE tenant_id = NEW.tenant_id
                AND status = 'ACTIVE' AND id <> NEW.id)) THEN
            RAISE EXCEPTION 'this is a one-person workspace: turn that setting off to add people'
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    RETURN NEW;
END $$;

CREATE TRIGGER tenancy_tenant_one_person
    BEFORE UPDATE OF one_person ON tenancy_tenant
    FOR EACH ROW EXECUTE FUNCTION tenancy_one_person_switch();
CREATE TRIGGER tenancy_membership_one_person
    BEFORE INSERT OR UPDATE OF status ON tenancy_membership
    FOR EACH ROW EXECUTE FUNCTION tenancy_one_person_closed();
CREATE TRIGGER tenancy_invitation_one_person
    BEFORE INSERT ON tenancy_invitation
    FOR EACH ROW EXECUTE FUNCTION tenancy_one_person_closed();
CREATE TRIGGER tenancy_engagement_one_person
    BEFORE INSERT ON tenancy_engagement
    FOR EACH ROW EXECUTE FUNCTION tenancy_one_person_closed();
"""

REVERSE = """
DROP TRIGGER IF EXISTS tenancy_engagement_one_person ON tenancy_engagement;
DROP TRIGGER IF EXISTS tenancy_invitation_one_person ON tenancy_invitation;
DROP TRIGGER IF EXISTS tenancy_membership_one_person ON tenancy_membership;
DROP TRIGGER IF EXISTS tenancy_tenant_one_person ON tenancy_tenant;
DROP FUNCTION IF EXISTS tenancy_one_person_closed();
DROP FUNCTION IF EXISTS tenancy_one_person_switch();
DROP FUNCTION IF EXISTS tenancy_self_approval_guard();
DROP FUNCTION IF EXISTS tenancy_one_person(uuid);
"""


class Migration(migrations.Migration):
    dependencies = [("tenancy", "0008_currency_guards")]

    operations = [
        migrations.AddField(
            model_name="tenant", name="one_person", field=models.BooleanField(default=False)
        ),
        migrations.RunSQL(SQL, REVERSE),
    ]
