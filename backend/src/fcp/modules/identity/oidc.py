"""OIDC login (Authorization Code + PKCE) in the backend-for-frontend pattern (docs/planning/04 §2).

- Tokens never reach the browser; only the Django session cookie does.
- Login is refused unless the ID token proves multi-factor authentication (``amr``/``acr``).
- ``auth_time`` is stored so sensitive operations can require a recent login (step-up).
"""

import time
from dataclasses import dataclass
from functools import cache
from typing import Any
from urllib.parse import urlencode

from authlib.integrations.django_client import DjangoOAuth2App, OAuth
from django.conf import settings

from fcp.core.errors import DomainError

SESSION_AUTH_TIME = "fcp_auth_time"
SESSION_LOGIN_AT = "fcp_login_at"
SESSION_AMR = "fcp_amr"


class MfaRequiredError(DomainError):
    code = "auth.mfa_required"
    status = 403
    title = "Multi-factor authentication required"


class LoginFailedError(DomainError):
    code = "auth.login_failed"
    status = 401
    title = "Login failed"


class StepUpRequiredError(DomainError):
    code = "auth.step_up_required"
    status = 401
    title = "Recent authentication required"

    def __init__(self, detail: str, *, login_url: str) -> None:
        super().__init__(detail, field_errors={"login_url": [login_url]})
        self.login_url = login_url


@cache
def _oauth() -> OAuth:
    oauth = OAuth()
    oauth.register(
        name="fcp",
        client_id=settings.OIDC_CLIENT_ID,
        client_secret=settings.OIDC_CLIENT_SECRET,
        server_metadata_url=f"{settings.OIDC_ISSUER}/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256"},
    )
    return oauth


def client() -> DjangoOAuth2App:
    app: DjangoOAuth2App = _oauth().create_client("fcp")
    return app


@dataclass(frozen=True)
class VerifiedIdentity:
    subject: str
    email: str
    display_name: str
    auth_time: int
    amr: tuple[str, ...]


def verify_claims(claims: dict[str, Any]) -> VerifiedIdentity:
    """Check the validated ID token claims for MFA and required attributes."""
    amr = tuple(str(v) for v in claims.get("amr") or ())
    acr = str(claims.get("acr") or "")
    mfa_by_amr = bool(set(amr) & set(settings.OIDC_MFA_AMR_VALUES))
    mfa_by_acr = bool(acr) and acr in settings.OIDC_MFA_ACR_VALUES
    if not (mfa_by_amr or mfa_by_acr):
        raise MfaRequiredError(
            "Your sign-in did not use multi-factor authentication. Set up an authenticator app "
            "or security key in your account, then sign in again."
        )
    email = str(claims.get("email") or "")
    if not email or claims.get("email_verified") is False:
        raise LoginFailedError(
            "Your account needs a verified e-mail address before you can sign in."
        )
    issuer = str(claims["iss"])
    auth_time = int(claims.get("auth_time") or claims["iat"])
    name = str(claims.get("name") or claims.get("preferred_username") or "")
    return VerifiedIdentity(f"{issuer}|{claims['sub']}", email, name, auth_time, amr)


def step_up_login_url(next_path: str) -> str:
    return "/auth/login?" + urlencode({"next": next_path, "step_up": "1"})


def require_recent_auth(session: Any, next_path: str, max_age_seconds: int | None = None) -> None:
    """Raise StepUpRequiredError unless the user authenticated within ``max_age_seconds``."""
    max_age = max_age_seconds or settings.STEP_UP_MAX_AGE_SECONDS
    auth_time = session.get(SESSION_AUTH_TIME)
    if not isinstance(auth_time, int) or time.time() - auth_time > max_age:
        raise StepUpRequiredError(
            "This action needs a recent sign-in. Sign in again to continue.",
            login_url=step_up_login_url(next_path),
        )
