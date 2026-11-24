"""Public interface of the ``identity`` module."""

from typing import cast

from django.http import HttpRequest
from django.views.decorators.csrf import ensure_csrf_cookie
from ninja import Router, Schema
from ninja.decorators import decorate_view

from fcp.core.api.permissions import AUTHENTICATED, requires

from .models import User
from .oidc import SESSION_AMR, SESSION_AUTH_TIME, StepUpRequiredError, require_recent_auth

__all__ = ["StepUpRequiredError", "User", "require_recent_auth", "router"]

router = Router(tags=["identity"])


class MeOut(Schema):
    id: str
    email: str
    display_name: str
    locale: str
    auth_time: int | None
    amr: list[str]


@router.get("/me", response=MeOut)
@decorate_view(ensure_csrf_cookie)  # the SPA calls /me at start-up and receives its CSRF cookie
@requires(AUTHENTICATED)
def me(request: HttpRequest) -> MeOut:
    user = cast(User, request.user)  # django_auth guarantees an authenticated User
    auth_time = request.session.get(SESSION_AUTH_TIME)
    return MeOut(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        locale=user.locale,
        auth_time=auth_time if isinstance(auth_time, int) else None,
        amr=list(request.session.get(SESSION_AMR, [])),
    )
