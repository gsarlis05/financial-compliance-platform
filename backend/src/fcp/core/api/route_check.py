"""Static check that every API operation declares a valid permission (doc 09 AC-B1)."""

from collections.abc import Callable, Iterator

from ninja import NinjaAPI, Router

from .permissions import AUTHENTICATED, PUBLIC, declared_permission


def _operations(
    router: Router, prefix: str = ""
) -> Iterator[tuple[str, str, Callable[..., object]]]:
    for path, path_view in router.path_operations.items():
        for operation in path_view.operations:
            for method in operation.methods:
                yield method, prefix + path, operation.view_func
    # Ninja exposes no public API for mounted routers: entries are (prefix, router, tags).
    for mounted in router._routers:
        yield from _operations(mounted[1], prefix + mounted[0])


def iter_operations(api: NinjaAPI) -> Iterator[tuple[str, str, Callable[..., object]]]:
    for prefix, router in api._routers:
        yield from _operations(router, prefix)


def permission_problems(api: NinjaAPI, is_known: Callable[[str], bool]) -> list[str]:
    """Return a description of every operation with a missing or invalid declaration."""
    problems = []
    for method, path, func in iter_operations(api):
        permission = declared_permission(func)
        where = f"{method} {path}"
        if permission is None:
            problems.append(f"{where}: no @requires(...) permission declared")
        elif "slug}" in path and permission in (PUBLIC, AUTHENTICATED):
            problems.append(f"{where}: workspace route must declare a workspace permission")
        elif permission not in (PUBLIC, AUTHENTICATED) and not is_known(permission):
            problems.append(f"{where}: unknown permission {permission!r}")
    return problems
