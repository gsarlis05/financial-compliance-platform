"""Settings for the automated test suite."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-not-a-secret")
# Tests create the test database and run migrations, so they use the schema-owner role.
# It is not a superuser and has no BYPASSRLS, so row-level security is fully enforced.
os.environ["DB_ROLE"] = "owner"

from .base import *  # noqa: F403

ALLOWED_HOSTS = ["testserver"]

OIDC_ISSUER = "https://idp.test/realms/fcp"
OIDC_CLIENT_ID = "fcp-test"
OIDC_CLIENT_SECRET = "test-client-secret"  # noqa: S105 - test-only fake
OIDC_REDIRECT_URI = "http://testserver/auth/callback"
LOGIN_REDIRECT_URL = "/app"

# Lets Django reset tables between transactional tests (see audit_log migration 0002).
# Never set in any deployed environment; the runtime role has no TRUNCATE privilege anyway.
DATABASES["default"]["OPTIONS"] = {"options": "-c fcp.allow_audit_truncate=on"}  # noqa: F405

BANKING_PROCESS_INLINE = True
