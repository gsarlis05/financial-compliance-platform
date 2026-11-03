"""Authorization: route declarations, role matrix, entity scoping, grant limits (AC-B1/B2/B6/B7)."""

import time
from collections.abc import Callable
from typing import Any

import pytest
from django.http import HttpRequest
from ninja import NinjaAPI, Router

from fcp.api import api
from fcp.core.api.permissions import AUTHENTICATED, requires
from fcp.core.api.route_check import iter_operations, permission_problems
from fcp.modules.identity import oidc
from fcp.modules.tenancy.entitlements import Role
from fcp.modules.tenancy.permissions import PERMISSIONS, ROLE_PERMISSIONS, is_known

Make = Callable[..., Any]

# --- AC-B1: every route declares a permission ------------------------------------------------


def test_every_api_operation_declares_a_valid_permission() -> None:
    assert list(iter_operations(api)), "no operations found"
    assert permission_problems(api, is_known) == []


def test_route_check_detects_undeclared_and_invalid_routes() -> None:
    probe = NinjaAPI(urls_namespace="probe")
    router = Router()

    @router.get("/undeclared")
    def undeclared(request: HttpRequest) -> dict[str, str]:  # pragma: no cover
        return {}

    @router.get("/w/{slug}/thing")
    @requires(AUTHENTICATED)
    def too_weak(request: HttpRequest, slug: str) -> dict[str, str]:  # pragma: no cover
        return {}

    @router.get("/w/{slug}/other")
    @requires("ledger.does_not_exist")
    def unknown(request: HttpRequest, slug: str) -> dict[str, str]:  # pragma: no cover
        return {}

    probe.add_router("/", router)
    problems = permission_problems(probe, is_known)
    assert len(problems) == 3
    assert any("no @requires" in p for p in problems)
    assert any("workspace permission" in p for p in problems)
    assert any("unknown permission" in p for p in problems)


# --- AC-B2: role matrix (allow and deny cases) -------------------------------------------------

SOD_CRITICAL = ["ledger.entry.create", "ledger.entry.approve", "ledger.entry.post"]

# (create, approve, post) per role.
_MATRIX: dict[str, tuple[bool, bool, bool]] = {
    Role.OWNER: (True, True, True),
    Role.TENANT_ADMIN: (False, False, False),
    Role.PARTNER: (True, True, True),
    Role.FINANCE_MANAGER: (True, True, True),
    Role.ACCOUNTANT: (True, False, False),
    Role.REVIEWER: (False, True, True),
    Role.CLIENT_USER: (False, False, False),
    Role.HOUSEHOLD_MEMBER: (True, False, True),
    Role.READ_ONLY: (False, False, False),
}
EXPECTED = {role: dict(zip(SOD_CRITICAL, flags, strict=True)) for role, flags in _MATRIX.items()}


@pytest.mark.parametrize("role", list(EXPECTED))
@pytest.mark.parametrize("permission", SOD_CRITICAL)
def test_role_matrix_for_segregation_of_duties(role: str, permission: str) -> None:
    assert (permission in ROLE_PERMISSIONS[role]) is EXPECTED[role][permission]


@pytest.mark.parametrize("role", [Role.TENANT_ADMIN, Role.CLIENT_USER, Role.READ_ONLY])
def test_non_ledger_roles_hold_no_ledger_write_permission(role: str) -> None:
    writes = {p for p in PERMISSIONS if p.startswith("ledger.") and not p.endswith(".read")}
    assert ROLE_PERMISSIONS[role] & writes == set()


def test_every_role_permission_is_catalogued() -> None:
    for role, permissions in ROLE_PERMISSIONS.items():
        assert permissions <= set(PERMISSIONS), role


def test_only_owner_and_partner_hold_every_permission() -> None:
    # A firm partner signs off and manages staff; only an owner can remove another owner.
    full = {role for role, perms in ROLE_PERMISSIONS.items() if perms == set(PERMISSIONS)}
    assert full == {Role.OWNER, Role.PARTNER}


# --- API-level authorization -------------------------------------------------------------------


def _join(owner_client: Any, slug: str, user: Any, client_factory: Make, role: str,
          entity_id: str | None = None) -> Any:  # fmt: skip
    body: dict[str, Any] = {"email": user.email, "role_key": role}
    if entity_id:
        body["legal_entity_id"] = entity_id
    issued = owner_client.post_json(f"/api/w/{slug}/invitations", body)
    assert issued.status_code == 201, issued.content
    client = client_factory(user)
    assert (
        client.post_json("/api/invitations/accept", {"token": issued.json()["token"]}).status_code
        == 200
    )
    return client


@pytest.fixture
def firm(make_user: Make, api_client: Make, make_workspace: Make) -> dict[str, Any]:
    owner = make_user("partner@example.test")
    ws = make_workspace(owner, kind="FIRM", name="Firm")
    oc = api_client(owner)
    a = oc.post_json(
        f"/api/w/{ws['slug']}/entities", {"legal_name": "Client A", "entity_type": "COMPANY"}
    ).json()
    b = oc.post_json(
        f"/api/w/{ws['slug']}/entities", {"legal_name": "Client B", "entity_type": "COMPANY"}
    ).json()
    return {"owner": owner, "ws": ws, "oc": oc, "a": a, "b": b}


@pytest.mark.django_db
def test_entity_scoped_member_sees_only_assigned_entity(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    staff = make_user("staff@example.test")
    slug = firm["ws"]["slug"]
    client = _join(firm["oc"], slug, staff, api_client, Role.ACCOUNTANT, firm["a"]["id"])
    names = [e["legal_name"] for e in client.get(f"/api/w/{slug}/entities").json()]
    assert names == ["Client A"]
    assert client.get(f"/api/w/{slug}/entities/{firm['a']['id']}").status_code == 200
    assert client.get(f"/api/w/{slug}/entities/{firm['b']['id']}").status_code == 404


@pytest.mark.django_db
def test_entity_scoped_member_cannot_add_entities_or_manage_members(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    staff = make_user("staff2@example.test")
    slug = firm["ws"]["slug"]
    client = _join(firm["oc"], slug, staff, api_client, Role.ACCOUNTANT, firm["a"]["id"])
    created = client.post_json(
        f"/api/w/{slug}/entities", {"legal_name": "X", "entity_type": "COMPANY"}
    )
    assert created.status_code == 403
    assert client.get(f"/api/w/{slug}/members").status_code == 403


@pytest.mark.django_db
def test_admin_cannot_grant_permissions_they_do_not_hold(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    admin, target = make_user("admin@example.test"), make_user("target@example.test")
    slug = firm["ws"]["slug"]
    admin_client = _join(firm["oc"], slug, admin, api_client, Role.TENANT_ADMIN)
    # tenant_admin lacks ledger permissions, so it cannot create an accountant or a reviewer.
    for role in (Role.ACCOUNTANT, Role.REVIEWER, Role.PARTNER):
        response = admin_client.post_json(
            f"/api/w/{slug}/invitations", {"email": target.email, "role_key": role}
        )
        assert response.status_code == 403, role
        assert "do not hold" in response.json()["detail"]
    # ...but it can grant read-only access, whose permissions it holds.
    ok = admin_client.post_json(
        f"/api/w/{slug}/invitations", {"email": target.email, "role_key": Role.READ_ONLY}
    )
    assert ok.status_code == 201


@pytest.mark.django_db
def test_entity_scoped_admin_cannot_grant_for_other_entities(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    scoped, target = make_user("scoped@example.test"), make_user("t2@example.test")
    slug = firm["ws"]["slug"]
    scoped_client = _join(firm["oc"], slug, scoped, api_client, Role.PARTNER, firm["a"]["id"])
    response = scoped_client.post_json(
        f"/api/w/{slug}/invitations",
        {"email": target.email, "role_key": Role.READ_ONLY, "legal_entity_id": firm["b"]["id"]},
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_grant_and_revoke_roles(firm: dict[str, Any], make_user: Make, api_client: Make) -> None:
    member = make_user("m@example.test")
    slug = firm["ws"]["slug"]
    _join(firm["oc"], slug, member, api_client, Role.READ_ONLY)
    members = firm["oc"].get(f"/api/w/{slug}/members").json()
    target = next(m for m in members if m["email"] == member.email)
    granted = firm["oc"].post_json(
        f"/api/w/{slug}/members/{target['membership_id']}/roles",
        {"role_key": Role.REVIEWER, "legal_entity_id": firm["b"]["id"]},
    )
    assert granted.status_code == 201
    duplicate = firm["oc"].post_json(
        f"/api/w/{slug}/members/{target['membership_id']}/roles",
        {"role_key": Role.REVIEWER, "legal_entity_id": firm["b"]["id"]},
    )
    assert duplicate.status_code == 409
    assert firm["oc"].delete_json(f"/api/w/{slug}/roles/{granted.json()['id']}").status_code == 204
    assert firm["oc"].delete_json(f"/api/w/{slug}/roles/{granted.json()['id']}").status_code == 404


@pytest.mark.django_db
def test_last_owner_cannot_be_removed(firm: dict[str, Any]) -> None:
    slug = firm["ws"]["slug"]
    owner_row = next(
        m
        for m in firm["oc"].get(f"/api/w/{slug}/members").json()
        if m["email"] == firm["owner"].email
    )
    owner_role = next(r for r in owner_row["roles"] if r["role_key"] == Role.OWNER)
    response = firm["oc"].delete_json(f"/api/w/{slug}/roles/{owner_role['id']}")
    assert response.status_code == 409


@pytest.mark.django_db
def test_role_changes_require_recent_sign_in(firm: dict[str, Any], make_user: Make) -> None:
    slug = firm["ws"]["slug"]
    session = firm["oc"].session
    session[oidc.SESSION_AUTH_TIME] = int(time.time()) - 600
    session.save()
    response = firm["oc"].post_json(
        f"/api/w/{slug}/invitations", {"email": make_user().email, "role_key": Role.READ_ONLY}
    )
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "auth.step_up_required"
    assert "step_up=1" in body["errors"]["login_url"][0]


@pytest.mark.django_db
def test_read_only_member_gets_403_not_404_for_admin_routes(
    firm: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = make_user("viewer@example.test")
    slug = firm["ws"]["slug"]
    client = _join(firm["oc"], slug, viewer, api_client, Role.READ_ONLY)
    assert client.get(f"/api/w/{slug}").status_code == 200
    assert client.get(f"/api/w/{slug}/members").status_code == 403
