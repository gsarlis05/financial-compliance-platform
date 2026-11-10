"""Isolation and history for personal budgets and goals (M5-2), enforced by the database.

- FORCE row-level security and composite tenant keys; a budget amount is of a category of the
  same legal entity.
- A budget amount never changes; a new amount supersedes it, once. Nothing is deleted.
- A personal goal never changes; it can only be retired, once. Nothing is deleted.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = ("personal_budget_amount", "personal_goal")

GUARDS = r"""
CREATE OR REPLACE FUNCTION personal_budget_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'budget amounts are kept; set a new amount instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.superseded_at IS NOT NULL OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'budget amounts are immutable; a change adds a new amount'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER personal_budget_guard BEFORE UPDATE OR DELETE ON personal_budget_amount
    FOR EACH ROW EXECUTE FUNCTION personal_budget_guard();

CREATE OR REPLACE FUNCTION personal_goal_guard() RETURNS trigger LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'goals are kept; retire a goal instead'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
       OR (to_jsonb(NEW) - 'retired_at') IS DISTINCT FROM (to_jsonb(OLD) - 'retired_at') THEN
        RAISE EXCEPTION 'a goal can only be retired; a different goal is a new one'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER personal_goal_guard BEFORE UPDATE OR DELETE ON personal_goal
    FOR EACH ROW EXECUTE FUNCTION personal_goal_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS personal_goal_guard ON personal_goal;
DROP FUNCTION IF EXISTS personal_goal_guard();
DROP TRIGGER IF EXISTS personal_budget_guard ON personal_budget_amount;
DROP FUNCTION IF EXISTS personal_budget_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("personal", "0003_plans"),
    ]

    operations = [
        *[op for t in TABLES for op in tenant_isolation(t)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity") for t in TABLES],
        migrations.RunSQL(
            "ALTER TABLE personal_budget_amount ADD CONSTRAINT personal_budget_same_entity "
            "FOREIGN KEY (legal_entity_id, account_id) REFERENCES ledger_account "
            "(legal_entity_id, id)",
            "ALTER TABLE personal_budget_amount DROP CONSTRAINT personal_budget_same_entity",
        ),
        migrations.RunSQL(GUARDS, REVERSE),
    ]
