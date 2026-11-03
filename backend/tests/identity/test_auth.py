"""Authentication acceptance tests (doc 09 §A: AC-A1 to AC-A5)."""

import time
import uuid
from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
import responses
from django.test import Client, override_settings

from fcp.core.ids import uuid7
from fcp.modules.identity import oidc
from fcp.modules.identity.models import User
from fcp.modules.identity.oidc import StepUpRequiredError, require_recent_auth

from .fake_idp import ISSUER, FakeIdP

pytestmark = pytest.mark.django_db


@pytest.fixture
def idp() -> Iterator[FakeIdP]:
    oidc._oauth.cache_clear()  # fresh client: no cached metadata or keys between tests
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        fake = FakeIdP(mock)
        fake.register_metadata()
        yield fake
    oidc._oauth.cache_clear()


def me(client: Client) -> tuple[int, dict[str, object]]:
    response = client.get("/api/me")
    return response.status_code, response.json()


# --- AC-A1: OIDC only, MFA required ---------------------------------------------------------


def test_login_redirect_uses_pkce_state_and_nonce(idp: FakeIdP) -> None:
    response = Client().get("/auth/login")
    assert response.status_code == 302
    location = urlparse(response["Location"])
    query = parse_qs(location.query)
    assert f"{location.scheme}://{location.netloc}{location.path}".startswith(ISSUER)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43
    assert query["state"][0]
    assert query["nonce"][0]
    assert "openid" in query["scope"][0].split()


def test_successful_mfa_login_creates_session_and_user(idp: FakeIdP) -> None:
    client = Client()
    response = idp.login(client, next_path="/app/ledger")
    assert response.status_code == 302
    assert response["Location"] == "/app/ledger"
    status, body = me(client)
    assert status == 200
    assert body["email"] == "owner@example.test"
    assert body["amr"] == ["pwd", "otp"]
    user = User.objects.get()
    assert user.idp_subject == f"{ISSUER}|user-123"
    assert not user.has_usable_password()


def test_login_without_mfa_retries_once_with_fresh_sign_in(idp: FakeIdP) -> None:
    idp.claims_override = {"amr": ["pwd"]}
    client = Client()
    response = idp.login(client, next_path="/app/x")
    assert response.status_code == 302
    assert response["Location"].startswith("/auth/login?")
    assert "step_up=1" in response["Location"]
    assert me(client)[0] == 401


def test_login_without_mfa_is_refused_with_actionable_message(idp: FakeIdP) -> None:
    idp.claims_override = {"amr": ["pwd"]}
    client = Client()
    idp.login(client)  # first attempt triggers the single automatic retry
    response = idp.login(client)
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "auth.mfa_required"
    assert "authenticator app" in body["detail"]
    assert me(client)[0] == 401
    assert not User.objects.exists()


@override_settings(OIDC_MFA_ACR_VALUES=frozenset({"gold"}))
def test_mfa_can_be_proven_by_configured_acr(idp: FakeIdP) -> None:
    idp.claims_override = {"amr": None, "acr": "gold"}
    assert idp.login(Client()).status_code == 302


def test_token_signed_by_unknown_key_is_rejected(idp: FakeIdP) -> None:
    idp.sign_with_other_key = True
    client = Client()
    response = idp.login(client)
    assert response.status_code >= 400
    assert me(client)[0] == 401


def test_token_with_wrong_audience_is_rejected(idp: FakeIdP) -> None:
    idp.claims_override = {"aud": "someone-else"}
    client = Client()
    assert idp.login(client).status_code >= 400
    assert me(client)[0] == 401


def test_state_mismatch_is_rejected(idp: FakeIdP) -> None:
    client = Client()
    client.get("/auth/login")
    response = client.get("/auth/callback", {"code": "x", "state": "forged"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.login_failed"


def test_idp_error_is_reported_without_details(idp: FakeIdP) -> None:
    response = Client().get("/auth/callback", {"error": "access_denied", "state": "x"})
    assert response.status_code == 401
    assert response.json()["code"] == "auth.login_failed"


def test_unverified_email_is_refused(idp: FakeIdP) -> None:
    idp.claims_override = {"email_verified": False}
    assert idp.login(Client()).status_code == 401


def test_disabled_user_cannot_sign_in(idp: FakeIdP) -> None:
    User.objects.create(
        idp_subject=f"{ISSUER}|user-123", email="owner@example.test", status=User.Status.DISABLED
    )
    client = Client()
    assert idp.login(client).status_code == 401
    assert me(client)[0] == 401


def test_profile_changes_at_the_idp_are_synchronised(idp: FakeIdP) -> None:
    User.objects.create(idp_subject=f"{ISSUER}|user-123", email="old@example.test")
    idp.login(Client())
    assert User.objects.get().email == "owner@example.test"


@pytest.mark.parametrize("target", ["https://evil.example/", "//evil.example/x", "javascript:x"])
def test_next_parameter_cannot_redirect_off_site(idp: FakeIdP, target: str) -> None:
    response = idp.login(Client(), next_path=target)
    assert response["Location"] == "/app"


# --- AC-A2: cookie flags and timeouts ---------------------------------------------------------


def test_session_cookie_flags(idp: FakeIdP) -> None:
    client = Client()
    idp.login(client)
    cookie = client.cookies["__Host-fcp_session"]
    assert cookie["httponly"]
    assert cookie["secure"]
    assert cookie["samesite"] == "Lax"
    assert cookie["path"] == "/"
    assert int(cookie["max-age"]) == 30 * 60  # idle timeout, renewed per request


def test_absolute_session_timeout_logs_out(idp: FakeIdP) -> None:
    client = Client()
    idp.login(client)
    session = client.session
    session[oidc.SESSION_LOGIN_AT] = int(time.time()) - 12 * 60 * 60 - 1
    session.save()
    assert me(client)[0] == 401


def test_session_id_rotates_on_login(idp: FakeIdP) -> None:
    client = Client()
    client.get("/auth/login")
    before = client.cookies["__Host-fcp_session"].value
    idp.login(client)
    assert client.cookies["__Host-fcp_session"].value != before


def test_unauthenticated_api_call_returns_problem_401() -> None:
    response = Client().get("/api/me")
    assert response.status_code == 401
    assert response["Content-Type"] == "application/problem+json"
    assert response.json()["code"] == "auth.unauthenticated"


# --- AC-A3: CSRF ------------------------------------------------------------------------------


def test_state_changing_request_without_csrf_token_is_rejected(idp: FakeIdP) -> None:
    client = Client(enforce_csrf_checks=True)
    idp.login(client)
    assert client.post("/auth/logout").status_code == 403
    assert me(client)[0] == 200


# --- AC-A4: step-up -----------------------------------------------------------------------------


def test_step_up_required_when_authentication_is_old() -> None:
    session = {oidc.SESSION_AUTH_TIME: int(time.time()) - 301}
    with pytest.raises(StepUpRequiredError) as exc:
        require_recent_auth(session, "/app/periods/unlock")
    assert exc.value.code == "auth.step_up_required"
    assert "step_up=1" in exc.value.login_url


def test_recent_authentication_passes_step_up() -> None:
    require_recent_auth({oidc.SESSION_AUTH_TIME: int(time.time()) - 10}, "/x")


def test_missing_auth_time_requires_step_up() -> None:
    with pytest.raises(StepUpRequiredError):
        require_recent_auth({}, "/x")


def test_step_up_login_forces_fresh_authentication(idp: FakeIdP) -> None:
    response = Client().get("/auth/login", {"step_up": "1", "next": "/app"})
    query = parse_qs(urlparse(response["Location"]).query)
    assert query["prompt"] == ["login"]
    assert query["max_age"] == ["0"]


# --- AC-A5: logout ----------------------------------------------------------------------------


def test_logout_ends_server_session_and_idp_session(idp: FakeIdP) -> None:
    client = Client(enforce_csrf_checks=True)
    idp.login(client)
    client.get("/api/me")  # obtains the CSRF cookie
    token = client.cookies["__Host-fcp_csrftoken"].value
    response = client.post("/auth/logout", headers={"X-CSRFToken": token})
    assert response.status_code == 302
    location = urlparse(response["Location"])
    assert location.path.endswith("/protocol/openid-connect/logout")
    assert "id_token_hint" in parse_qs(location.query)
    assert me(client)[0] == 401


# --- identifiers --------------------------------------------------------------------------------


def test_uuid7_format_and_ordering() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7
    assert first.variant == uuid.RFC_4122
    assert first < second
    assert len({uuid7() for _ in range(1000)}) == 1000
