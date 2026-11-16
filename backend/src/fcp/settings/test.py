"""Settings for the automated test suite."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret")

from .base import *  # noqa: F403

ALLOWED_HOSTS = ["testserver"]

OIDC_ISSUER = "https://idp.test/realms/fcp"
OIDC_CLIENT_ID = "fcp-test"
OIDC_CLIENT_SECRET = "test-client-secret"  # noqa: S105 - test-only fake
OIDC_REDIRECT_URI = "http://testserver/auth/callback"
LOGIN_REDIRECT_URL = "/app"
