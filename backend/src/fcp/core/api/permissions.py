"""Per-operation permission declarations (doc 04 §3.3).

Every API operation is decorated with ``@requires(<permission>)``. The decorator records the
permission on the request; ``tenancy`` enforces it when the operation enters its workspace, so
the declared and the checked permission are always the same. A CI test enumerates all routes and
fails if any operation lacks a declaration or a workspace route uses a non-workspace permission.
"""

import functools
from collections.abc import Callable
from typing import Any, TypeVar, cast

from django.http import HttpRequest

PERMISSION_ATTRIBUTE = "_fcp_permission"
REQUEST_ATTRIBUTE = "fcp_required_permission"

PUBLIC = "public"
"""No authentication (e.g. health checks)."""

AUTHENTICATED = "authenticated"
"""Any signed-in user; no workspace data is exposed."""

F = TypeVar("F", bound=Callable[..., Any])


def requires(permission: str) -> Callable[[F], F]:
    """Declare the permission an operation needs. Must be the innermost decorator."""

    def decorate(func: F) -> F:
        @functools.wraps(func)
        def wrapper(request: HttpRequest, *args: Any, **kwargs: Any) -> Any:
            setattr(request, REQUEST_ATTRIBUTE, permission)
            return func(request, *args, **kwargs)

        setattr(wrapper, PERMISSION_ATTRIBUTE, permission)
        return cast(F, wrapper)

    return decorate


def declared_permission(func: Callable[..., Any]) -> str | None:
    value = getattr(func, PERMISSION_ATTRIBUTE, None)
    return value if isinstance(value, str) else None


def required_permission(request: HttpRequest) -> str | None:
    value = getattr(request, REQUEST_ATTRIBUTE, None)
    return value if isinstance(value, str) else None
