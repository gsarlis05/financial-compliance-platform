"""Isolation and history of commitments (M3-4).

- FORCE row-level security and composite tenant keys on obligations, loans and holidays.
- A counterparty or lender belongs to the same legal entity (composite foreign key).
- Obligation and loan versions are never deleted. The only change allowed is superseding the
  current version, once; everything else about a version is fixed (forecast runs pin versions).
"""

from django.db import migrations

from fcp.core.db.operations import composite_tenant_fk, tenant_isolation

VERSIONED = ("registers_recurring_obligation", "registers_debt_instrument")

GUARD = r"""
CREATE OR REPLACE FUNCTION registers_version_guard() RETURNS trigger
    LANGUAGE plpgsql AS
$$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'versions are kept; retire instead of deleting'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.superseded_at IS NOT NULL
       OR NEW.superseded_at IS NULL
       OR (to_jsonb(NEW) - 'superseded_at') IS DISTINCT FROM (to_jsonb(OLD) - 'superseded_at') THEN
        RAISE EXCEPTION 'versions are immutable; a change adds a new version'
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
""" + "".join(
    f"""
CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION registers_version_guard();
"""
    for table in VERSIONED
)

GUARD_REVERSE = "".join(f"DROP TRIGGER IF EXISTS {t}_guard ON {t};\n" for t in VERSIONED) + (
    "DROP FUNCTION IF EXISTS registers_version_guard();"
)


def _same_entity(table: str, column: str) -> migrations.RunSQL:
    name = f"{table}_{column}_same_entity"
    return migrations.RunSQL(
        f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY (legal_entity_id, {column}) "
        "REFERENCES registers_counterparty (legal_entity_id, id)",
        reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name}",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_db", "0001_rls_functions"),
        ("tenancy", "0003_tenant_ids_function"),
        ("registers", "0005_commitments"),
    ]

    operations = [
        *[op for t in (*VERSIONED, "registers_entity_holiday") for op in tenant_isolation(t)],
        *[composite_tenant_fk(t, "legal_entity_id", "tenancy_legal_entity")
          for t in (*VERSIONED, "registers_entity_holiday")],
        composite_tenant_fk("registers_recurring_obligation", "counterparty_id",
                            "registers_counterparty"),
        composite_tenant_fk("registers_debt_instrument", "lender_id", "registers_counterparty"),
        _same_entity("registers_recurring_obligation", "counterparty_id"),
        _same_entity("registers_debt_instrument", "lender_id"),
        migrations.RunSQL(GUARD, reverse_sql=GUARD_REVERSE),
    ]  # fmt: skip
