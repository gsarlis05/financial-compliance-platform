"""A fake OIDC provider for tests: real RS256-signed ID tokens, HTTP endpoints mocked by
``responses``. Nothing leaves the process."""

import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

import responses
from django.conf import settings
from django.test import Client
from joserfc import jwt
from joserfc.jwk import RSAKey

ISSUER = "https://idp.test/realms/fcp"
_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})
_OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "test-key"})


@dataclass
class FakeIdP:
    mock: responses.RequestsMock
    claims_override: dict[str, Any] = field(default_factory=dict)
    sign_with_other_key: bool = False

    def register_metadata(self) -> None:
        self.mock.get(
            f"{ISSUER}/.well-known/openid-configuration",
            json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
                "end_session_endpoint": f"{ISSUER}/protocol/openid-connect/logout",
                "id_token_signing_alg_values_supported": ["RS256"],
            },
        )
        self.mock.get(
            f"{ISSUER}/protocol/openid-connect/certs",
            json={"keys": [_KEY.as_dict(private=False)]},
        )

    def id_token(self, nonce: str) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "sub": "user-123",
            "aud": settings.OIDC_CLIENT_ID,
            "iat": now,
            "exp": now + 300,
            "auth_time": now,
            "nonce": nonce,
            "email": "owner@example.test",
            "email_verified": True,
            "name": "Demo Owner",
            "amr": ["pwd", "otp"],
        }
        claims.update(self.claims_override)
        claims = {k: v for k, v in claims.items() if v is not None}
        key = _OTHER_KEY if self.sign_with_other_key else _KEY
        return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)

    def login(self, client: Client, next_path: str = "/app") -> Any:
        """Run the full browser flow; returns the callback response."""
        start = client.get("/auth/login", {"next": next_path})
        query = parse_qs(urlparse(start["Location"]).query)
        state, nonce = query["state"][0], query["nonce"][0]
        self.mock.post(
            f"{ISSUER}/protocol/openid-connect/token",
            json={
                "access_token": "opaque-access",
                "token_type": "Bearer",
                "expires_in": 300,
                "id_token": self.id_token(nonce),
            },
        )
        return client.get("/auth/callback", {"code": "auth-code", "state": state})
