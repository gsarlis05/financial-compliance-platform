"""Privileges for the runtime role, re-applied after every migration.

The runtime role gets data access only: no DDL, no ownership, no BYPASSRLS. Append-only tables
(e.g. the audit log) additionally lose UPDATE and DELETE; reference-data tables are SELECT-only.
Identifiers are composed with psycopg's ``sql.Identifier`` (they cannot be query parameters),
never with string formatting.
"""

from typing import Any

from django.conf import settings
from django.db import connections
from psycopg import sql

from .registry import APPEND_ONLY_TABLES, READ_ONLY_TABLES, RUNTIME_FUNCTIONS

_STATEMENTS = (
    "GRANT USAGE ON SCHEMA public TO {role}",
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {role}",
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {role}",
    "REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM {role}",
)


def _existing(cursor: Any, tables: set[str]) -> list[str]:
    """Tables that exist now (a module's migrations may be unapplied, e.g. while reversing)."""
    found = []
    for table in tables:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [table])
        row = cursor.fetchone()
        if row and row[0]:
            found.append(table)
    return found


def apply_runtime_grants(using: str = "default") -> None:
    role_name = settings.DB_APP_ROLE_NAME
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role_name])
        if cursor.fetchone() is None:
            return  # role not provisioned (e.g. a bare developer database)
        role = sql.Identifier(role_name)
        for statement in _STATEMENTS:
            cursor.execute(sql.SQL(statement).format(role=role))
        for table in sorted(_existing(cursor, APPEND_ONLY_TABLES)):
            cursor.execute(
                sql.SQL("REVOKE UPDATE, DELETE ON {table} FROM {role}").format(
                    table=sql.Identifier(table), role=role
                )
            )
        for signature in sorted(RUNTIME_FUNCTIONS):
            cursor.execute("SELECT to_regprocedure(%s) IS NOT NULL", [signature])
            row = cursor.fetchone()
            if row and row[0]:  # created by a migration already applied
                name = signature.removesuffix("()")
                cursor.execute(
                    sql.SQL("GRANT EXECUTE ON FUNCTION {fn}() TO {role}").format(
                        fn=sql.Identifier(name), role=role
                    )
                )
        for table in sorted(_existing(cursor, READ_ONLY_TABLES)):
            cursor.execute(
                sql.SQL("REVOKE INSERT, UPDATE, DELETE ON {table} FROM {role}").format(
                    table=sql.Identifier(table), role=role
                )
            )
