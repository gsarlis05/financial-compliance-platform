"""Deployed-environment settings (M2-0): secure by default, fail fast on unsafe configuration.

Each case starts a fresh interpreter, because Django settings are loaded once per process.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest
from django.db import DatabaseError
from django.test import Client

BACKEND = Path(__file__).resolve().parents[1]

DEPLOYED_ENV = {
    "DJANGO_SETTINGS_MODULE": "fcp.settings.prod",
    "DJANGO_SECRET_KEY": "test-only-" + "".join(chr(97 + (i * 7) % 26) for i in range(60)),
    "DJANGO_ALLOWED_HOSTS": "app.example.test",
    "CSRF_TRUSTED_ORIGINS": "https://app.example.test",
    "POSTGRES_HOST": "db.internal.example.test",
    "OIDC_ISSUER": "https://id.example.test/realms/fcp",
    "OIDC_CLIENT_ID": "fcp-backend",
    "OIDC_CLIENT_SECRET": "from-secrets-manager",
    "OIDC_REDIRECT_URI": "https://app.example.test/auth/callback",
    "OIDC_POST_LOGOUT_REDIRECT_URI": "https://app.example.test/",
    "DOCUMENTS_BUCKET": "fcp-documents-test",
    "DOCUMENTS_KMS_KEY_ID": "arn:aws:kms:eu-central-1:000000000000:key/test",
    "CLAMD_HOST": "clamav.internal.example.test",
}

PROBE = (
    "import django; django.setup(); from django.conf import settings as s; "
    "print(s.SECURE_SSL_REDIRECT, s.SECURE_HSTS_SECONDS, s.SESSION_COOKIE_SECURE, "
    "s.DATABASES['default']['OPTIONS']['sslmode'], s.DATABASES['default']['CONN_MAX_AGE'], s.DEBUG)"
)


def _run(args: list[str], **overrides: str | None) -> subprocess.CompletedProcess[str]:
    prefixes = ("POSTGRES_", "OIDC_", "DJANGO_", "DOCUMENTS_", "CLAMD_", "S3_")
    env = {k: v for k, v in os.environ.items() if not k.startswith(prefixes)}
    env.update(DEPLOYED_ENV)
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(  # noqa: S603 - fixed arguments, test-only
        [sys.executable, *args], cwd=BACKEND, env=env, capture_output=True, text=True, check=False
    )


def test_deploy_checks_pass() -> None:
    result = _run(["manage.py", "check", "--deploy", "--fail-level", "WARNING"])
    assert result.returncode == 0, result.stderr + result.stdout


def test_secure_defaults() -> None:
    result = _run(["-c", PROBE])
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["True", "31536000", "True", "verify-full", "60", "False"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"DJANGO_ALLOWED_HOSTS": ""}, "DJANGO_ALLOWED_HOSTS must list"),
        ({"POSTGRES_HOST": None}, "POSTGRES_HOST is not set"),
        ({"OIDC_ISSUER": "http://id.example.test/realms/fcp"}, "OIDC_ISSUER must be an https://"),
        ({"OIDC_CLIENT_SECRET": ""}, "OIDC_CLIENT_SECRET must be set"),
        ({"CSRF_TRUSTED_ORIGINS": "http://app.example.test"}, "must use https"),
        ({"POSTGRES_SSLMODE": "disable"}, "POSTGRES_SSLMODE must enforce TLS"),
        ({"DJANGO_SECRET_KEY": None}, "DJANGO_SECRET_KEY is not set"),
        ({"DOCUMENTS_KMS_KEY_ID": ""}, "DOCUMENTS_KMS_KEY_ID must be set"),
        ({"CLAMD_HOST": None}, "CLAMD_HOST is not set"),
        ({"S3_ENDPOINT": "http://s3.example.test"}, "S3_ENDPOINT must be empty"),
    ],
)
def test_unsafe_or_missing_configuration_stops_start_up(
    override: dict[str, str | None], message: str
) -> None:
    result = _run(["-c", PROBE], **override)
    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.django_db
def test_readyz_reports_database_ok() -> None:
    response = Client().get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_responses_forbid_framing() -> None:
    assert Client().get("/healthz")["X-Frame-Options"] == "DENY"


def test_readyz_reports_unavailable_database() -> None:
    with mock.patch("fcp.urls.connection.cursor", side_effect=DatabaseError("down")):
        response = Client().get("/readyz")
    assert response.status_code == 503
    assert response.json()["database"] == "unreachable"
