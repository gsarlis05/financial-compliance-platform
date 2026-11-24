"""Isolation and lifecycle rules for budgets (M4-1, AC-BU1), enforced by the database.

- FORCE row-level security and composite tenant keys on every table.
- Same-entity composite foreign keys: a budget's fiscal year and dimension value, a version's
  budget and the version it revises, a line's version, account and dimension value, an amount's
  line and an event's version all belong to the same legal entity.
- A budget's scope (fiscal year, type, dimension value) never changes; only its name can.
- Versions start as drafts and are never deleted. Only these changes are allowed, each touching only its own columns:
  editing a draft's reason; DRAFT → SUBMITTED; SUBMITTED → DRAFT (returned); SUBMITTED → APPROVED;
  APPROVED → LOCKED; APPROVED or LOCKED → SUPERSEDED. Anything else is refused.
- Lines and amounts can be inserted, changed or deleted only while their version is a draft (the
  version row is share-locked, so a submission waits for an edit in progress and vice versa).
- Amounts are dated on the first day of a month.
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

TABLES = (
    "budgeting_settings",
    "budgeting_budget",
    "budgeting_version",
    "budgeting_line",
    "budgeting_amount",
    "budgeting_event",
)


def _sql(sql: str, reverse: str) -> migrations.RunSQL:
    return migrations.RunSQL(sql, reverse_sql=reverse)


def _key(table: str) -> migrations.RunSQL:
    name = f"{table}_entity_id_key"
    return _sql(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE (legal_entity_id, id)",
        f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


def _same_entity(table: str, column: str, ref: str) -> migrations.RunSQL:
    name = f"{table}_{column}_same_entity"
    return _sql(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (legal_entity_id, {column}) "
        f"REFERENCES {ref} (legal_entity_id, id)",
        f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


BUDGET_GUARD = r"""
CREATE OR REPLACE FUNCTION budgeting_budget_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'budgets are kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF (to_jsonb(NEW) - 'name') IS DISTINCT FROM (to_jsonb(OLD) - 'name') THEN
        RAISE EXCEPTION 'a budget''s fiscal year, type and scope never change'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER budgeting_budget_guard BEFORE UPDATE OR DELETE ON budgeting_budget
    FOR EACH ROW EXECUTE FUNCTION budgeting_budget_guard();
"""

VERSION_GUARD = r"""
CREATE OR REPLACE FUNCTION budgeting_version_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    changed text[];
    allowed text[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'budget versions are kept'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.status <> 'DRAFT' OR NEW.content_hash <> '' OR NEW.submitted_at IS NOT NULL
           OR NEW.approved_at IS NOT NULL OR NEW.locked_at IS NOT NULL
           OR NEW.superseded_at IS NOT NULL THEN
            RAISE EXCEPTION 'a budget version starts as a draft'
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
        RETURN NEW;
    END IF;
    SELECT coalesce(array_agg(n.key), '{}') INTO changed
      FROM jsonb_each(to_jsonb(NEW)) n JOIN jsonb_each(to_jsonb(OLD)) o USING (key)
     WHERE n.value IS DISTINCT FROM o.value;
    allowed := CASE
        WHEN OLD.status = 'DRAFT' AND NEW.status = 'DRAFT'
            THEN ARRAY['reason']
        WHEN OLD.status = 'DRAFT' AND NEW.status = 'SUBMITTED'
            THEN ARRAY['status', 'content_hash', 'submitted_by_id', 'submitted_at']
        WHEN OLD.status = 'SUBMITTED' AND NEW.status = 'DRAFT'
            THEN ARRAY['status', 'content_hash', 'submitted_by_id', 'submitted_at']
        WHEN OLD.status = 'SUBMITTED' AND NEW.status = 'APPROVED'
            THEN ARRAY['status', 'approved_by_id', 'approved_at', 'sod_applied']
        WHEN OLD.status = 'APPROVED' AND NEW.status = 'LOCKED'
            THEN ARRAY['status', 'locked_by_id', 'locked_at']
        WHEN OLD.status IN ('APPROVED', 'LOCKED') AND NEW.status = 'SUPERSEDED'
            THEN ARRAY['status', 'superseded_at']
    END;
    IF allowed IS NULL OR NOT changed <@ allowed THEN
        RAISE EXCEPTION 'budget version % cannot change from % to % (changed: %)',
            OLD.number, OLD.status, NEW.status, changed
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER budgeting_version_guard BEFORE INSERT OR UPDATE OR DELETE ON budgeting_version
    FOR EACH ROW EXECUTE FUNCTION budgeting_version_guard();
"""

CONTENT_GUARD = r"""
CREATE OR REPLACE FUNCTION budgeting_require_draft(version uuid) RETURNS void
    LANGUAGE plpgsql AS
$$
DECLARE
    st text;
BEGIN
    SELECT status INTO st FROM budgeting_version WHERE id = version FOR SHARE;
    IF st IS DISTINCT FROM 'DRAFT' THEN
        RAISE EXCEPTION 'budget lines can only change while their version is a draft'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION budgeting_line_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM budgeting_require_draft(OLD.version_id);
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM budgeting_require_draft(NEW.version_id);
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER budgeting_line_guard BEFORE INSERT OR UPDATE OR DELETE ON budgeting_line
    FOR EACH ROW EXECUTE FUNCTION budgeting_line_guard();

CREATE OR REPLACE FUNCTION budgeting_amount_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        PERFORM budgeting_require_draft((SELECT version_id FROM budgeting_line WHERE id = OLD.line_id));
    END IF;
    IF TG_OP <> 'DELETE' THEN
        PERFORM budgeting_require_draft((SELECT version_id FROM budgeting_line WHERE id = NEW.line_id));
        RETURN NEW;
    END IF;
    RETURN OLD;
END;
$$;
CREATE TRIGGER budgeting_amount_guard BEFORE INSERT OR UPDATE OR DELETE ON budgeting_amount
    FOR EACH ROW EXECUTE FUNCTION budgeting_amount_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS budgeting_amount_guard ON budgeting_amount;
DROP TRIGGER IF EXISTS budgeting_line_guard ON budgeting_line;
DROP TRIGGER IF EXISTS budgeting_version_guard ON budgeting_version;
DROP FUNCTION IF EXISTS budgeting_amount_guard();
DROP FUNCTION IF EXISTS budgeting_line_guard();
DROP FUNCTION IF EXISTS budgeting_require_draft(uuid);
DROP FUNCTION IF EXISTS budgeting_version_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("ledger", "0016_dimension_value_entity_key"),
        ("budgeting", "0001_budgets"),
    ]

    operations = [
        *[op for table in TABLES for op in tenant_isolation(table)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity") for t in TABLES],
        _key("budgeting_budget"),
        _key("budgeting_version"),
        _key("budgeting_line"),
        _same_entity("budgeting_budget", "fiscal_year_id", "ledger_fiscal_year"),
        _same_entity("budgeting_budget", "dimension_value_id", "ledger_dimension_value"),
        _same_entity("budgeting_version", "budget_id", "budgeting_budget"),
        _same_entity("budgeting_version", "supersedes_id", "budgeting_version"),
        _same_entity("budgeting_line", "version_id", "budgeting_version"),
        _same_entity("budgeting_line", "account_id", "ledger_account"),
        _same_entity("budgeting_line", "dimension_value_id", "ledger_dimension_value"),
        _same_entity("budgeting_amount", "line_id", "budgeting_line"),
        _same_entity("budgeting_event", "version_id", "budgeting_version"),
        _sql(
            "ALTER TABLE budgeting_amount ADD CONSTRAINT budgeting_amount_first_of_month "
            "CHECK (extract(day FROM month) = 1)",
            "ALTER TABLE budgeting_amount DROP CONSTRAINT budgeting_amount_first_of_month",
        ),
        _sql(
            BUDGET_GUARD,
            "DROP TRIGGER IF EXISTS budgeting_budget_guard ON budgeting_budget; "
            "DROP FUNCTION IF EXISTS budgeting_budget_guard();",
        ),
        _sql(VERSION_GUARD + CONTENT_GUARD, REVERSE),
    ]
