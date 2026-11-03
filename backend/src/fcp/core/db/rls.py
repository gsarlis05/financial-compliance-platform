"""Row-level security context for the current transaction.

Policies compare ``tenant_id`` with ``app_current_tenant()``, which reads the transaction-local
setting ``app.tenant_id``. When no context is set, policies match nothing, so forgetting to set
the context returns no data rather than all data.
"""

from uuid import UUID

from django.db import connection


class RlsContextError(RuntimeError):
    """Raised when the context is set outside a transaction (it would not persist)."""


def set_context(*, tenant_id: UUID | None = None, user_id: UUID | None = None) -> None:
    """Set the tenant and user for the rest of the current transaction."""
    if not connection.in_atomic_block:
        raise RlsContextError(
            "Row-level security context must be set inside a transaction (transaction.atomic)."
        )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('app.tenant_id', %s, true), set_config('app.user_id', %s, true)",
            [str(tenant_id) if tenant_id else "", str(user_id) if user_id else ""],
        )


def clear_context() -> None:
    set_context(tenant_id=None, user_id=None)


def current_tenant_id() -> UUID | None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT app_current_tenant()")
        row = cursor.fetchone()
    return row[0] if row and row[0] else None
