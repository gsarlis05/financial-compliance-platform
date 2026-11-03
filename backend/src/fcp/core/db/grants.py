"""Privileges for the runtime role, re-applied after every migration.

The runtime role gets data access only: no DDL, no ownership, no BYPASSRLS. Append-only tables
(e.g. the audit log) additionally lose UPDATE and DELETE.
"""

from django.conf import settings
from django.db import connections

from .registry import APPEND_ONLY_TABLES


def apply_runtime_grants(using: str = "default") -> None:
    role = settings.DB_APP_ROLE_NAME
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
        if cursor.fetchone() is None:
            return  # role not provisioned (e.g. a bare developer database)
        quoted = connections[using].ops.quote_name(role)
        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {quoted}")
        cursor.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted}"
        )
        cursor.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {quoted}")
        cursor.execute(f"REVOKE TRUNCATE, REFERENCES, TRIGGER ON ALL TABLES IN SCHEMA public FROM {quoted}")
        for table in sorted(APPEND_ONLY_TABLES):
            cursor.execute(
                f"REVOKE UPDATE, DELETE ON {connections[using].ops.quote_name(table)} FROM {quoted}"
            )
