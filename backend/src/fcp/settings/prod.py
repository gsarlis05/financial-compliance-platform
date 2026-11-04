"""Settings for every deployed environment (staging, pilot, production).

Differences from ``base``:
- every deployment-specific value is required (no ``localhost`` fallbacks), so a missing
  variable stops the container at start-up instead of misbehaving at runtime;
- HTTPS is assumed: TLS terminates at the load balancer, which sets ``X-Forwarded-Proto``;
- the database connection uses TLS and persistent connections. Persistent connections are
  safe because the row-level security context is transaction-local (``set_config(..., true)``).

Verified in CI by ``manage.py check --deploy`` and by ``tests/test_prod_settings.py``.
"""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import DATABASES, env


def _required_list(name: str) -> list[str]:
    values = [v.strip() for v in env(name).split(",") if v.strip()]
    if not values:
        raise ImproperlyConfigured(f"{name} must list at least one value.")
    return values


def _https(name: str) -> str:
    value = env(name)
    if not value.startswith("https://"):
        raise ImproperlyConfigured(f"{name} must be an https:// URL in deployed environments.")
    return value


DEBUG = False
BANKING_PROCESS_INLINE = False  # imports are parsed by the worker only (ADR-0015)
ALLOWED_HOSTS = _required_list("DJANGO_ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = _required_list("CSRF_TRUSTED_ORIGINS")
if any(not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured("CSRF_TRUSTED_ORIGINS must use https://.")

# --- HTTPS behind the load balancer -------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
# Load balancer health checks call these over plain HTTP inside the VPC.
SECURE_REDIRECT_EXEMPT = [r"^healthz$", r"^readyz$"]
SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", str(365 * 24 * 60 * 60)))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False  # opt in deliberately once the domain is final
# W021 (preload not set) is a deliberate, reviewed choice: preloading is hard to undo.
SILENCED_SYSTEM_CHECKS = ["security.W021"]
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# --- Database ------------------------------------------------------------------------------------
DATABASES["default"]["HOST"] = env("POSTGRES_HOST")
DATABASES["default"]["CONN_MAX_AGE"] = int(env("DB_CONN_MAX_AGE", "60"))
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
_SSLMODE = env("POSTGRES_SSLMODE", "verify-full")
if _SSLMODE not in ("require", "verify-ca", "verify-full"):
    raise ImproperlyConfigured(
        "POSTGRES_SSLMODE must enforce TLS (require, verify-ca, verify-full)."
    )
DATABASES["default"]["OPTIONS"] = {
    "sslmode": _SSLMODE,
    "sslrootcert": env("POSTGRES_SSLROOTCERT", "/etc/ssl/certs/rds-global-bundle.pem"),
}

# --- Identity provider ---------------------------------------------------------------------------
OIDC_ISSUER = _https("OIDC_ISSUER")
OIDC_CLIENT_ID = env("OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET = env("OIDC_CLIENT_SECRET")
OIDC_REDIRECT_URI = _https("OIDC_REDIRECT_URI")
OIDC_POST_LOGOUT_REDIRECT_URI = _https("OIDC_POST_LOGOUT_REDIRECT_URI")
if not OIDC_CLIENT_SECRET:
    raise ImproperlyConfigured("OIDC_CLIENT_SECRET must be set.")
