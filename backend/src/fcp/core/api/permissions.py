"""Per-operation permission declarations (doc 04 §3.3).

Every API operation must be decorated with ``@requires(<permission>)``. A CI test enumerates all
routes and fails if any operation lacks a declaration. Enforcement of workspace permissions is done
by ``fcp.modules.tenancy`` (Milestone 1-3); the special values below need no workspace.
"""

from collections.abc import Callable
from typing import Any, TypeVar

PERMISSION_ATTRIBUTE = "_fcp_permission"

PUBLIC = "public"
"""No authentication (e.g. health checks)."""

AUTHENTICATED = "authenticated"
"""Any signed-in user; no workspace data is exposed."""

F = TypeVar("F", bound=Callable[..., Any])


def requires(permission: str) -> Callable[[F], F]:
    """Declare the permission an operation needs. Must be the innermost decorator."""

    def decorate(func: F) -> F:
        setattr(func, PERMISSION_ATTRIBUTE, permission)
        return func

    return decorate


def declared_permission(func: Callable[..., Any]) -> str | None:
    value = getattr(func, PERMISSION_ATTRIBUTE, None)
    return value if isinstance(value, str) else None
