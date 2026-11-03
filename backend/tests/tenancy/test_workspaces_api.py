"""Workspace, entity and invitation API, including cross-tenant isolation (AC-B3, B8, B9)."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pytest
from django.db import transaction
from django.test import Client
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.modules.identity.models import User
from fcp.modules.tenancy.models import Invitation

pytestmark = pytest.mark.django_db

Make = Callable[..., Any]


def test_unauthenticated_requests_are_rejected() -> None:
    assert Client().get("/api/workspaces").status_code == 401


def test_personal_workspace_gets_one_household_entity(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    user = make_user()
    ws = make_workspace(user, kind="PERSONAL", name="My finances")
    assert ws["kind"] == "PERSONAL"
    assert ws["roles"] == ["owner"]
    entities = api_client(user).get(f"/api/w/{ws['slug']}/entities").json()
    assert [e["entity_type"] for e in entities] == ["HOUSEHOLD"]


def test_personal_workspace_cannot_add_a_second_entity(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    user = make_user()
    ws = make_workspace(user, kind="PERSONAL")
    response = api_client(user).post_json(
        f"/api/w/{ws['slug']}/entities", {"legal_name": "Side Co", "entity_type": "COMPANY"}
    )
    assert response.status_code == 403
    assert response["Content-Type"] == "application/problem+json"


def test_business_workspace_requires_company_details(make_user: Make, api_client: Make) -> None:
    response = api_client(make_user()).post_json(
        "/api/workspaces", {"name": "No Entity", "kind": "BUSINESS"}
    )
    assert response.status_code == 422
    assert "entity_name" in response.json()["errors"]


def test_firm_can_add_client_entities(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    user = make_user()
    ws = make_workspace(user, kind="FIRM", name="Sarlis & Co")
    client = api_client(user)
    for name in ("Client A Ltd", "Client B Ltd"):
        created = client.post_json(
            f"/api/w/{ws['slug']}/entities", {"legal_name": name, "entity_type": "COMPANY"}
        )
        assert created.status_code == 201
    assert len(client.get(f"/api/w/{ws['slug']}/entities").json()) == 2
    features = client.get(f"/api/w/{ws['slug']}/features").json()
    assert features["client_portfolio"] is True


def test_household_entity_type_is_only_for_personal_workspaces(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    user = make_user()
    ws = make_workspace(user, kind="FIRM")
    response = api_client(user).post_json(
        f"/api/w/{ws['slug']}/entities", {"legal_name": "Home", "entity_type": "HOUSEHOLD"}
    )
    assert response.status_code == 422


def test_invalid_payload_gives_field_errors(make_user: Make, api_client: Make) -> None:
    response = api_client(make_user()).post_json("/api/workspaces", {"name": "", "kind": "BANK"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert set(body["errors"]) >= {"name", "kind"}


# --- AC-B3 / B9: isolation through the API -------------------------------------------------------


@pytest.fixture
def two_tenants(make_user: Make, make_workspace: Make, api_client: Make) -> dict[str, Any]:
    alice, bob = make_user("alice@example.test"), make_user("bob@example.test")
    a, b = make_workspace(alice, name="Alice"), make_workspace(bob, name="Bob")
    b_entity = api_client(bob).get(f"/api/w/{b['slug']}/entities").json()[0]
    return {"alice": alice, "bob": bob, "a": a, "b": b, "b_entity": b_entity}


@pytest.mark.parametrize(
    "path",
    ["/api/w/{b}", "/api/w/{b}/entities", "/api/w/{b}/entities/{e}", "/api/w/{b}/features"],
)
def test_other_tenants_resources_are_not_found(
    two_tenants: dict[str, Any], api_client: Make, path: str
) -> None:
    client = api_client(two_tenants["alice"])
    url = path.format(b=two_tenants["b"]["slug"], e=two_tenants["b_entity"]["id"])
    response = client.get(url)
    assert response.status_code == 404
    assert two_tenants["b_entity"]["legal_name"] not in response.content.decode()


def test_other_tenants_entity_via_own_workspace_path_is_not_found(
    two_tenants: dict[str, Any], api_client: Make
) -> None:
    client = api_client(two_tenants["alice"])
    url = f"/api/w/{two_tenants['a']['slug']}/entities/{two_tenants['b_entity']['id']}"
    assert client.get(url).status_code == 404


def test_cannot_write_into_another_tenant(two_tenants: dict[str, Any], api_client: Make) -> None:
    client = api_client(two_tenants["alice"])
    response = client.post_json(
        f"/api/w/{two_tenants['b']['slug']}/entities",
        {"legal_name": "Intruder", "entity_type": "COMPANY"},
    )
    assert response.status_code == 404
    response = client.post_json(
        f"/api/w/{two_tenants['b']['slug']}/invitations",
        {"email": "spy@example.test", "role_key": "read_only"},
    )
    assert response.status_code == 404


def test_tenant_id_in_body_is_ignored(two_tenants: dict[str, Any], api_client: Make) -> None:
    client = api_client(two_tenants["alice"])
    created = client.post_json(
        f"/api/w/{two_tenants['a']['slug']}/entities",
        {
            "legal_name": "Second Ltd",
            "entity_type": "COMPANY",
            "tenant_id": two_tenants["b"]["id"],
        },
    )
    assert created.status_code == 201
    names = [
        e["legal_name"] for e in client.get(f"/api/w/{two_tenants['a']['slug']}/entities").json()
    ]
    assert "Second Ltd" in names
    bob_names = [
        e["legal_name"]
        for e in api_client(two_tenants["bob"])
        .get(f"/api/w/{two_tenants['b']['slug']}/entities")
        .json()
    ]
    assert "Second Ltd" not in bob_names


def test_list_shows_only_own_workspaces(two_tenants: dict[str, Any], api_client: Make) -> None:
    slugs = [w["slug"] for w in api_client(two_tenants["alice"]).get("/api/workspaces").json()]
    assert slugs == [two_tenants["a"]["slug"]]


def test_same_user_personal_and_business_are_separate(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    user = make_user()
    personal = make_workspace(user, kind="PERSONAL", name="Me")
    business = make_workspace(user, kind="BUSINESS", name="MyCo")
    client = api_client(user)
    assert {w["kind"] for w in client.get("/api/workspaces").json()} == {"PERSONAL", "BUSINESS"}
    personal_entities = client.get(f"/api/w/{personal['slug']}/entities").json()
    business_entities = client.get(f"/api/w/{business['slug']}/entities").json()
    assert {e["entity_type"] for e in personal_entities} == {"HOUSEHOLD"}
    assert {e["entity_type"] for e in business_entities} == {"COMPANY"}
    personal_household_id = personal_entities[0]["id"]
    url = f"/api/w/{business['slug']}/entities/{personal_household_id}"
    assert client.get(url).status_code == 404


# --- invitations --------------------------------------------------------------------------------


def _invite(client: Any, slug: str, email: str, role: str = "accountant") -> Any:
    return client.post_json(f"/api/w/{slug}/invitations", {"email": email, "role_key": role})


def test_invitation_flow(make_user: Make, api_client: Make, make_workspace: Make) -> None:
    owner, invitee = make_user("owner@example.test"), make_user("Accountant@Example.test")
    ws = make_workspace(owner)
    issued = _invite(api_client(owner), ws["slug"], "accountant@example.test")
    assert issued.status_code == 201
    token = issued.json()["token"]
    invitee_client = api_client(invitee)
    assert invitee_client.get(f"/api/w/{ws['slug']}").status_code == 404
    accepted = invitee_client.post_json("/api/invitations/accept", {"token": token})
    assert accepted.status_code == 200
    assert accepted.json()["roles"] == ["accountant"]
    assert invitee_client.get(f"/api/w/{ws['slug']}").status_code == 200
    # Single use.
    again = invitee_client.post_json("/api/invitations/accept", {"token": token})
    assert again.status_code == 404


def test_invitation_for_another_email_is_refused(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    owner, other = make_user(), make_user("other@example.test")
    ws = make_workspace(owner)
    token = _invite(api_client(owner), ws["slug"], "intended@example.test").json()["token"]
    response = api_client(other).post_json("/api/invitations/accept", {"token": token})
    assert response.status_code == 403


def test_expired_invitation_is_refused(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    owner, invitee = make_user(), make_user("late@example.test")
    ws = make_workspace(owner)
    token = _invite(api_client(owner), ws["slug"], "late@example.test").json()["token"]
    with transaction.atomic():
        set_context(tenant_id=ws["id"])
        Invitation.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    response = api_client(invitee).post_json("/api/invitations/accept", {"token": token})
    assert response.status_code == 404


@pytest.mark.parametrize(
    "token", ["garbage-token", "not-a-uuid.secret", "00000000-0000-7000-8000-000000000000."]
)
def test_malformed_tokens_are_refused(make_user: Make, api_client: Make, token: str) -> None:
    response = api_client(make_user()).post_json("/api/invitations/accept", {"token": token})
    assert response.status_code == 404


def test_only_admins_can_invite(make_user: Make, api_client: Make, make_workspace: Make) -> None:
    owner, member = make_user(), make_user("member@example.test")
    ws = make_workspace(owner)
    token = _invite(api_client(owner), ws["slug"], "member@example.test").json()["token"]
    member_client = api_client(member)
    member_client.post_json("/api/invitations/accept", {"token": token})
    assert _invite(member_client, ws["slug"], "x@example.test").status_code == 403


@pytest.mark.parametrize(("kind", "role"), [("BUSINESS", "owner"), ("PERSONAL", "partner")])
def test_roles_not_grantable_in_workspace_are_rejected(
    make_user: Make, api_client: Make, make_workspace: Make, kind: str, role: str
) -> None:
    owner = make_user()
    ws = make_workspace(owner, kind=kind)
    assert _invite(api_client(owner), ws["slug"], "x@example.test", role).status_code == 422


def test_invitation_token_is_stored_only_as_hash(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    owner = make_user()
    ws = make_workspace(owner)
    token = _invite(api_client(owner), ws["slug"], "h@example.test").json()["token"]
    with transaction.atomic():
        set_context(tenant_id=ws["id"])
        stored = Invitation.objects.get()
    assert token not in stored.token_hash
    assert len(stored.token_hash) == 64


def test_user_model_is_imported() -> None:
    assert User.__name__ == "User"
