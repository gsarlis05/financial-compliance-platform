"""Browser-facing OIDC endpoints: /auth/login, /auth/callback, /auth/logout."""

import time
from urllib.parse import urlencode

import structlog
from authlib.integrations.base_client.errors import OAuthError
from django.conf import settings
from django.contrib.auth import login, logout
from django.db import transaction
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from fcp.core.http.problem import response_for_exception

from . import oidc
from .models import User

log = structlog.get_logger(__name__)
SESSION_NEXT = "fcp_login_next"
SESSION_MFA_RETRY = "fcp_mfa_retry"
SESSION_ID_TOKEN = "fcp_id_token"  # noqa: S105 - a session key name, not a secret


def _safe_next(request: HttpRequest, candidate: str | None) -> str:
    """Only same-origin relative paths are allowed (prevents open redirects)."""
    if (
        candidate
        and candidate.startswith("/")
        and url_has_allowed_host_and_scheme(candidate, allowed_hosts=None, require_https=False)
    ):
        return candidate
    return settings.LOGIN_REDIRECT_URL


@require_GET
def login_view(request: HttpRequest) -> HttpResponse:
    request.session[SESSION_NEXT] = _safe_next(request, request.GET.get("next"))
    extra: dict[str, str | int] = {}
    if request.GET.get("step_up") == "1":
        # Force a fresh interactive authentication for step-up (doc 04 §2).
        extra = {"prompt": "login", "max_age": 0}
    response: HttpResponse = oidc.client().authorize_redirect(
        request, settings.OIDC_REDIRECT_URI, **extra
    )
    return response


def _verified_identity(request: HttpRequest) -> oidc.VerifiedIdentity | HttpResponse:
    """Complete the code exchange and verify the ID token, or return the response to send."""
    try:
        token = oidc.client().authorize_access_token(request)
    except OAuthError as exc:
        log.warning("auth.callback_rejected", error_code="auth.login_failed", error_type=exc.error)
        return response_for_exception(
            request, oidc.LoginFailedError("Sign-in could not be completed. Please try again.")
        )
    claims = token.get("userinfo")
    if not claims:
        return response_for_exception(
            request, oidc.LoginFailedError("The identity provider did not return an ID token.")
        )
    try:
        identity = oidc.verify_claims(dict(claims))
    except oidc.MfaRequiredError as exc:
        # Typical right after first-time authenticator enrolment: the IdP did not count the
        # enrolment as an authentication factor. Retry once with a forced fresh sign-in, which
        # now asks for the second factor; a second failure is shown to the user.
        if not request.session.get(SESSION_MFA_RETRY):
            request.session[SESSION_MFA_RETRY] = True
            log.info("auth.mfa_retry", error_code=exc.code)
            next_path = request.session.get(SESSION_NEXT, settings.LOGIN_REDIRECT_URL)
            return HttpResponseRedirect(oidc.step_up_login_url(_safe_next(request, next_path)))
        request.session.pop(SESSION_MFA_RETRY, None)
        log.warning("auth.login_refused", error_code=exc.code)
        return response_for_exception(request, exc)
    except oidc.LoginFailedError as exc:
        log.warning("auth.login_refused", error_code=exc.code)
        return response_for_exception(request, exc)
    request.session[SESSION_ID_TOKEN] = token.get("id_token", "")
    return identity


@require_GET
@transaction.non_atomic_requests
def callback_view(request: HttpRequest) -> HttpResponse:
    identity = _verified_identity(request)
    if isinstance(identity, HttpResponse):
        return identity

    with transaction.atomic():
        user, created = User.objects.get_or_create_from_oidc(
            subject=identity.subject, email=identity.email, display_name=identity.display_name
        )
    if not user.is_active:
        log.warning("auth.login_refused", error_code="auth.account_disabled", user_id=str(user.id))
        return response_for_exception(
            request, oidc.LoginFailedError("This account is disabled. Contact your administrator.")
        )

    next_path = request.session.get(SESSION_NEXT, settings.LOGIN_REDIRECT_URL)
    id_token = request.session.get(SESSION_ID_TOKEN, "")
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")  # rotates session id
    request.session[oidc.SESSION_AUTH_TIME] = identity.auth_time
    request.session[oidc.SESSION_LOGIN_AT] = int(time.time())
    request.session[oidc.SESSION_AMR] = list(identity.amr)
    request.session[SESSION_ID_TOKEN] = id_token
    request.session.pop(SESSION_MFA_RETRY, None)
    log.info("auth.login_succeeded", user_id=str(user.id), count=int(created))
    return HttpResponseRedirect(_safe_next(request, next_path))


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    id_token = request.session.get(SESSION_ID_TOKEN, "")
    user_id = str(request.user.pk) if request.user.is_authenticated else None
    logout(request)  # flushes the server-side session
    log.info("auth.logout", user_id=user_id)
    metadata = oidc.client().load_server_metadata()
    end_session = metadata.get("end_session_endpoint")
    if not end_session:
        return HttpResponseRedirect(settings.LOGOUT_REDIRECT_URL)
    params = {
        "client_id": settings.OIDC_CLIENT_ID,
        "post_logout_redirect_uri": settings.OIDC_POST_LOGOUT_REDIRECT_URI,
    }
    if id_token:
        params["id_token_hint"] = id_token
    return HttpResponseRedirect(f"{end_session}?{urlencode(params)}")
