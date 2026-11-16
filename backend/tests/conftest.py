"""Shared fixtures: users, signed-in API clients and workspaces."""

import time
from collections.abc import Callable
from typing import Any

import pytest
from django.test import Client

from fcp.modules.identity import oidc
from fcp.modules.identity.models import User


class ApiClient(Client):
    """A signed-in client that sends JSON and the CSRF header like the SPA does."""

    def __init__(self, user: User) -> None:
        super().__init__(enforce_csrf_checks=True)
        self.user = user
        self.force_login(user)
        session = self.session
        now = int(time.time())
        session[oidc.SESSION_AUTH_TIME] = now
        session[oidc.SESSION_LOGIN_AT] = now
        session.save()
        self.get("/api/me")  # receives the CSRF cookie

    def _csrf(self) -> dict[str, str]:
        return {"X-CSRFToken": self.cookies["__Host-fcp_csrftoken"].value}

    def post_json(self, path: str, data: Any) -> Any:
        return self.post(path, data, content_type="application/json", headers=self._csrf())

    def put_json(self, path: str, data: Any) -> Any:
        return self.put(path, data, content_type="application/json", headers=self._csrf())

    def delete_json(self, path: str) -> Any:
        return self.delete(path, headers=self._csrf())


@pytest.fixture
def make_user(db: None) -> Callable[..., User]:
    counter = iter(range(1, 10_000))

    def make(email: str | None = None, name: str = "Test User") -> User:
        n = next(counter)
        return User.objects.create(
            idp_subject=f"https://idp.test|user-{n}-{time.time_ns()}",
            email=email or f"user{n}@example.test",
            display_name=name,
        )

    return make


@pytest.fixture
def api_client() -> Callable[[User], ApiClient]:
    return ApiClient


@pytest.fixture
def make_workspace(api_client: Callable[[User], ApiClient]) -> Callable[..., dict[str, Any]]:
    def make(user: User, kind: str = "BUSINESS", name: str = "Demo") -> dict[str, Any]:
        payload: dict[str, Any] = {"name": name, "kind": kind}
        if kind == "BUSINESS":
            payload["entity_name"] = f"{name} Ltd (Demo)"
        response = api_client(user).post_json("/api/workspaces", payload)
        assert response.status_code == 201, response.content
        body: dict[str, Any] = response.json()
        return body

    return make


@pytest.fixture
def reference_data() -> None:
    """Transactional tests empty every table afterwards, including migration-seeded reference
    data; tests that need the VAT catalogue after such a flush request this fixture."""
    from django.core.management import call_command  # noqa: PLC0415

    call_command("seed_reference_data", verbosity=0)
