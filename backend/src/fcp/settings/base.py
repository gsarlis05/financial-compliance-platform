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
]

MIDDLEWARE = [
    "fcp.core.http.middleware.CorrelationIdMiddleware",
    "fcp.core.http.middleware.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.common.CommonMiddleware",
    "fcp.core.http.middleware.ProblemDetailsMiddleware",
]

ROOT_URLCONF = "fcp.urls"
WSGI_APPLICATION = "fcp.wsgi.application"
ASGI_APPLICATION = "fcp.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "fcp"),
        "USER": env("POSTGRES_USER", "fcp"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
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
