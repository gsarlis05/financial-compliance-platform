"""Settings shared by every environment.

Secrets and environment-specific values come from environment variables only.
Nothing secret is committed to the repository.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from fcp.core.logging import build_logging_config, configure_structlog

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    """Return an environment variable, failing loudly if it is required and missing."""
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(f"Required environment variable {name} is not set.")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS: list[str] = [h for h in env("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "fcp.core.db",
    "fcp.modules.identity",
    "fcp.modules.tenancy",
    "fcp.modules.audit_log",
    "fcp.modules.ledger",
    "fcp.modules.registers",
    "fcp.modules.banking",
    "fcp.modules.documents",
    "fcp.modules.reporting",
    "fcp.modules.metrics",
    "fcp.modules.cashflow",
    "fcp.modules.budgeting",
    "fcp.modules.kpi",
    "fcp.modules.goals",
    "fcp.modules.dashboards",
    "fcp.modules.personal",
]

AUTH_USER_MODEL = "identity.User"

MIDDLEWARE = [
    "fcp.core.http.middleware.CorrelationIdMiddleware",
    "fcp.core.http.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "fcp.modules.identity.middleware.AbsoluteSessionTimeoutMiddleware",
    "fcp.core.http.middleware.ProblemDetailsMiddleware",
]

ROOT_URLCONF = "fcp.urls"
WSGI_APPLICATION = "fcp.wsgi.application"
ASGI_APPLICATION = "fcp.asgi.application"

# The application never connects as a superuser (superusers bypass row-level security).
# DB_ROLE=app (default) is the runtime role; DB_ROLE=owner runs migrations and tests.
DB_ROLE = env("DB_ROLE", "app")
if DB_ROLE not in ("app", "owner"):
    raise ImproperlyConfigured("DB_ROLE must be 'app' or 'owner'.")
DB_APP_ROLE_NAME = env("POSTGRES_APP_USER", "fcp_app")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "fcp"),
        "USER": env(f"POSTGRES_{DB_ROLE.upper()}_USER", f"fcp_{DB_ROLE}"),
        "PASSWORD": env(f"POSTGRES_{DB_ROLE.upper()}_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "ATOMIC_REQUESTS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en"
LANGUAGES = [("en", "English"), ("el", "Greek")]
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Security headers (TLS terminates at the load balancer in deployed environments).
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

# Logging: JSON lines, redacted by an allow-list (fcp.core.logging.redaction).
LOGGING = build_logging_config(env("LOG_LEVEL", "INFO"))
configure_structlog()

# --- Sessions and cookies (docs/planning/04 §2) -------------------------------------------------
# Server-side sessions; the browser only holds an opaque, HttpOnly, Secure, SameSite cookie.
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_NAME = "__Host-fcp_session"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 30 * 60  # idle timeout; extended by every request
SESSION_SAVE_EVERY_REQUEST = True
SESSION_ABSOLUTE_TIMEOUT_SECONDS = 12 * 60 * 60
STEP_UP_MAX_AGE_SECONDS = 5 * 60

# CSRF token cookie is readable by the SPA, which echoes it in the X-CSRFToken header.
CSRF_COOKIE_NAME = "__Host-fcp_csrftoken"
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = "Strict"
CSRF_TRUSTED_ORIGINS: list[str] = [o for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# --- OIDC (identity provider) -----------------------------------------------------------------
OIDC_ISSUER = env("OIDC_ISSUER", "http://localhost:8080/realms/fcp-dev")
OIDC_CLIENT_ID = env("OIDC_CLIENT_ID", "fcp-backend")
OIDC_CLIENT_SECRET = env("OIDC_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = env("OIDC_REDIRECT_URI", "http://localhost:8000/auth/callback")
OIDC_POST_LOGOUT_REDIRECT_URI = env("OIDC_POST_LOGOUT_REDIRECT_URI", "http://localhost:5173/")
# Claim values accepted as proof of multi-factor authentication.
OIDC_MFA_AMR_VALUES = frozenset(env("OIDC_MFA_AMR_VALUES", "otp,mfa,hwk,swk,webauthn").split(","))
OIDC_MFA_ACR_VALUES = frozenset(v for v in env("OIDC_MFA_ACR_VALUES", "").split(",") if v)
LOGIN_REDIRECT_URL = env("LOGIN_REDIRECT_URL", "/")
LOGOUT_REDIRECT_URL = env("LOGOUT_REDIRECT_URL", "/")

# Bank statement imports (M2-5, ADR-0015): parsed by the worker (banking_process_imports), never in
# the request. Development and tests may process inline for convenience; deployed settings never.
BANKING_PROCESS_INLINE = env("BANKING_PROCESS_INLINE", "false").lower() == "true"
DATA_UPLOAD_MAX_MEMORY_SIZE = 11 * 1024 * 1024  # a 10 MB document plus form overhead
FILE_UPLOAD_MAX_MEMORY_SIZE = 11 * 1024 * 1024  # uploads stay in memory (read-only root filesystem)

# Document vault (M2-4, ADR-0016): S3 API storage under per-tenant prefixes, ClamAV as a service.
# S3_ENDPOINT empty means AWS S3; empty keys mean the default credential chain (ECS task role).
S3_ENDPOINT = env("S3_ENDPOINT", "")
S3_REGION = env("S3_REGION", "eu-central-1")
S3_ACCESS_KEY = env("S3_ACCESS_KEY", "")
S3_SECRET_KEY = env("S3_SECRET_KEY", "")
DOCUMENTS_BUCKET = env("DOCUMENTS_BUCKET", "fcp-documents")
DOCUMENTS_KMS_KEY_ID = env("DOCUMENTS_KMS_KEY_ID", "")  # set: SSE-KMS with a tenant context
DOCUMENTS_MAX_BYTES = 10 * 1024 * 1024

# Days between an owner confirming a workspace deletion and its purge (M5-6); it can be cancelled
# until then.
WORKSPACE_DELETION_GRACE_DAYS = int(env("WORKSPACE_DELETION_GRACE_DAYS", "30"))
CLAMD_HOST = env("CLAMD_HOST", "127.0.0.1")
CLAMD_PORT = int(env("CLAMD_PORT", "3310"))
CLAMD_TIMEOUT_SECONDS = int(env("CLAMD_TIMEOUT_SECONDS", "30"))
