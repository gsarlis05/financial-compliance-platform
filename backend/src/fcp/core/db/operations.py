"""Migration operations for tenant isolation (ADR-0002, doc 03 conventions).

Use in module migrations::

    operations = [
        ...CreateModel...,
        *tenant_isolation("ledger_account"),
        composite_tenant_fk("ledger_account", "legal_entity_id", "tenancy_legal_entity"),
    ]
"""

from django.db import migrations

TENANT_PREDICATE = "tenant_id = app_current_tenant()"


def _ident(name: str) -> str:
    if not name.replace("_", "").isalnum():
        raise ValueError(f"Unsafe SQL identifier: {name!r}")
    return f'"{name}"'


def enable_rls(table: str, using: str, check: str | None = None) -> migrations.RunSQL:
    """ENABLE + FORCE row-level security with one policy (FORCE applies it to the owner too)."""
    t = _ident(table)
    return migrations.RunSQL(
        sql=[
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY",
            f"CREATE POLICY tenant_isolation ON {t} USING ({using}) WITH CHECK ({check or using})",
        ],
        reverse_sql=[
            f"DROP POLICY IF EXISTS tenant_isolation ON {t}",
            f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY",
            f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY",
        ],
    )


def tenant_isolation(table: str) -> list[migrations.RunSQL]:
    """Standard isolation for a tenant-owned table: (tenant_id, id) unique key + RLS policy."""
    t = _ident(table)
    return [
        migrations.RunSQL(
            sql=f"ALTER TABLE {t} ADD CONSTRAINT {_ident(table + '_tenant_id_key')} "
            f"UNIQUE (tenant_id, id)",
            reverse_sql=f"ALTER TABLE {t} DROP CONSTRAINT {_ident(table + '_tenant_id_key')}",
        ),
        enable_rls(table, TENANT_PREDICATE),
    ]


def composite_tenant_fk(
    table: str, column: str, ref_table: str, *, nullable_ok: bool = True
) -> migrations.RunSQL:
    """FOREIGN KEY (tenant_id, column) -> ref_table (tenant_id, id): a row can never reference a
    row of another tenant, even through a bug (doc 03 conventions)."""
    del nullable_ok  # MATCH SIMPLE: a NULL column skips the check, as for a nullable FK
    name = _ident(f"{table}_{column}_tenant_fk")
    return migrations.RunSQL(
        sql=f"ALTER TABLE {_ident(table)} ADD CONSTRAINT {name} FOREIGN KEY (tenant_id, "
        f"{_ident(column)}) REFERENCES {_ident(ref_table)} (tenant_id, id) DEFERRABLE INITIALLY "
        f"IMMEDIATE",
        reverse_sql=f"ALTER TABLE {_ident(table)} DROP CONSTRAINT {name}",
    )
