"""Absolute session lifetime (doc 04 §2). The idle timeout is Django's SESSION_COOKIE_AGE with
SESSION_SAVE_EVERY_REQUEST, so every request extends it."""

import time
from collections.abc import Callable

import structlog
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpRequest, HttpResponse

from .oidc import SESSION_LOGIN_AT

log = structlog.get_logger(__name__)


class AbsoluteSessionTimeoutMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated:
            login_at = request.session.get(SESSION_LOGIN_AT)
            expired = not isinstance(login_at, int) or (
                time.time() - login_at > settings.SESSION_ABSOLUTE_TIMEOUT_SECONDS
            )
            if expired:
                user_id = str(request.user.pk)
                logout(request)
                log.info("auth.session_expired", user_id=user_id)
        return self.get_response(request)
