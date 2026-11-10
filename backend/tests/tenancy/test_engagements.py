"""Engagement grants (M5-4, doc 11 §3): a client-owned workspace lets a firm in. Scope ∩ firm
role, time-bound, revocable with immediate effect, audited in both workspaces, portfolio
included, and no query across workspaces."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.tenancy.models import Engagement, EngagementStaff

from ..ledger.conftest import join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]


def later(days: int = 30) -> str:
    return (timezone.now() + timedelta(days=days)).isoformat()


@pytest.fixture
def setup(make_user: Make, api_client: Make, make_workspace: Make) -> dict[str, Any]:
    """A firm (owner, an accountant, a read-only member) and a client business with its owner."""
    firm_owner = make_user("partner@firm.test")
    firm = make_workspace(firm_owner, kind="FIRM", name="Sarlis & Co")
    fc = api_client(firm_owner)
    staff = {}
    for email, role in (("acc@firm.test", "accountant"), ("view@firm.test", "read_only")):
        user = make_user(email)
        staff[role] = {"user": user, "client": join(fc, firm["slug"], user, api_client, role)}
    members = {m["email"]: m["membership_id"] for m in
               fc.get(f"/api/w/{firm['slug']}/members").json()}  # fmt: skip
    owner = make_user("owner@client.test")
    client = make_workspace(owner, name="Client X")
    cc = api_client(owner)
    entity = cc.get(f"/api/w/{client['slug']}/entities").json()[0]
    return {"firm": firm, "fc": fc, "staff": staff, "members": members, "client": client,
            "cc": cc, "entity": entity, "owner": owner}  # fmt: skip


def grant(s: dict[str, Any], scope: list[str], **extra: Any) -> Any:
    return s["cc"].post_json(f"/api/w/{s['client']['slug']}/engagements",
                             {"firm_slug": s["firm"]["slug"], "scope_roles": scope,
                              "valid_until": later(), **extra})  # fmt: skip


def staff(s: dict[str, Any], engagement_id: str, email: str) -> Any:
    return s["fc"].post_json(
        f"/api/w/{s['firm']['slug']}/client-engagements/{engagement_id}/staff",
        {"membership_id": s["members"][email]},
    )


def test_scope_intersection_staffing_and_immediate_revocation(setup: dict[str, Any]) -> None:
    s = setup
    acc = s["staff"]["accountant"]["client"]
    viewer = s["staff"]["read_only"]["client"]
    entities = f"/api/w/{s['client']['slug']}/entities"
    assert acc.get(entities).status_code == 404  # nothing before a grant

    made = grant(s, ["accountant", "read_only"])
    assert made.status_code == 201, made.content
    eid = made.json()["id"]
    assert made.json()["firm_name"] == "Sarlis & Co"
    assert acc.get(entities).status_code == 404  # granted, but not staffed yet

    listed = s["fc"].get(f"/api/w/{s['firm']['slug']}/client-engagements").json()
    assert [(e["client_name"], e["scope_roles"]) for e in listed] == [
        ("Client X", ["accountant", "read_only"])
    ]
    for email in ("acc@firm.test", "view@firm.test"):
        assert staff(s, eid, email).status_code == 201

    # The accountant works inside the client's workspace, as an accountant.
    shown = acc.get("/api/workspaces").json()
    assert [(w["name"], w["via_engagement"]) for w in shown] == [
        ("Sarlis & Co", None),
        ("Client X", "firm"),
    ]
    me = acc.get(f"/api/w/{s['client']['slug']}").json()
    assert me["roles"] == ["accountant", "read_only"]
    assert me["via_engagement"].startswith("Sarlis & Co")
    base = f"{entities}/{s['entity']['id']}"
    assert s["cc"].post_json(f"{base}/accounts/apply-template",
                             {"template": "cy_business"}).status_code == 201  # fmt: skip
    assert acc.get(f"{base}/accounts").status_code == 200
    # Intersection: firm read-only ∩ {accountant, read_only} = read_only.
    assert viewer.get(f"/api/w/{s['client']['slug']}").json()["roles"] == ["read_only"]
    blocked = viewer.post_json(f"{base}/accounts", {"code": "9990", "name": "X", "type": "ASSET"})
    assert blocked.status_code == 403

    # Never the client's administration: members, roles, engagements.
    assert acc.get(f"/api/w/{s['client']['slug']}/members").status_code == 403
    assert acc.get(f"/api/w/{s['client']['slug']}/engagements").status_code == 403

    # The portfolio of the firm includes the client, computed in the client's own context.
    rows = acc.get(f"/api/w/{s['firm']['slug']}/portfolio?month=2026-11-01").json()
    assert [(r["legal_name"], r["client_slug"]) for r in rows] == [
        ("Client X Ltd (Demo)", s["client"]["slug"])
    ]

    # Revoked: refused on the very next request, and gone from the firm's lists.
    gone = s["cc"].post_json(f"/api/w/{s['client']['slug']}/engagements/{eid}/revoke", {})
    assert gone.status_code == 200, gone.content
    assert gone.json()["active"] is False
    assert acc.get(entities).status_code == 404
    assert acc.get(f"/api/w/{s['firm']['slug']}/portfolio?month=2026-11-01").json() == []
    assert s["fc"].get(f"/api/w/{s['firm']['slug']}/client-engagements").json() == []
    assert [w["name"] for w in acc.get("/api/workspaces").json()] == ["Sarlis & Co"]

    # Audited in both workspaces: grant, staff actions by the firm user, staffing, revocation.
    set_context(tenant_id=UUID(s["client"]["id"]))
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"tenancy.engagement.granted", "tenancy.engagement.revoked"} <= actions
    set_context(tenant_id=UUID(s["firm"]["id"]))
    firm_actions = list(AuditEvent.objects.values_list("action", flat=True))
    assert firm_actions.count("tenancy.engagement.staff_added") == 2


def test_firm_user_actions_are_attributed_to_the_firm(setup: dict[str, Any]) -> None:
    s = setup
    eid = grant(s, ["accountant"]).json()["id"]
    staff(s, eid, "acc@firm.test")
    acc = s["staff"]["accountant"]["client"]
    base = f"/api/w/{s['client']['slug']}/entities/{s['entity']['id']}"
    s["cc"].post_json(f"{base}/accounts/apply-template", {"template": "cy_business"})
    added = acc.post_json(f"{base}/counterparties", {"code": "C1", "name": "Customer (Demo)",
                                                     "kind": "CUSTOMER"})  # fmt: skip
    assert added.status_code == 201, added.content
    set_context(tenant_id=UUID(s["client"]["id"]))
    event = AuditEvent.objects.filter(subject_id=added.json()["id"]).get()
    assert event.actor_user_id == s["staff"]["accountant"]["user"].id
    assert event.changes["via_engagement"].startswith(f"Sarlis & Co ({eid})")
    # The owner's own actions carry no engagement.
    own = AuditEvent.objects.filter(action="tenancy.engagement.granted").get()
    assert "via_engagement" not in own.changes


def test_grant_rules_expiry_and_history(
    setup: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    s = setup
    assert grant(s, ["owner"]).status_code == 422  # never ownership or administration
    assert grant(s, []).status_code == 422
    past = (timezone.now() - timedelta(days=1)).isoformat()
    assert grant(s, ["read_only"], valid_until=past).status_code == 422
    assert grant(s, ["read_only"], valid_until=later(4 * 366)).status_code == 422
    wrong = s["cc"].post_json(f"/api/w/{s['client']['slug']}/engagements",
                              {"firm_slug": s["client"]["slug"], "scope_roles": ["read_only"],
                               "valid_until": later()})  # fmt: skip
    assert wrong.status_code == 422  # only firms can be engaged

    # Only the client's administrators grant; staffing is for firm workspaces only.
    acc = s["staff"]["accountant"]["client"]
    assert (
        acc.post_json(
            f"/api/w/{s['client']['slug']}/engagements",
            {"firm_slug": s["firm"]["slug"], "scope_roles": ["read_only"], "valid_until": later()},
        ).status_code
        == 404
    )  # not staffed anywhere: the workspace does not exist for them
    assert s["cc"].get(f"/api/w/{s['client']['slug']}/client-engagements").status_code == 403

    # A personal workspace may let an adviser read, nothing more.
    me = make_user("me@home.test")
    home = make_workspace(me, kind="PERSONAL", name="My finances")
    hc = api_client(me)
    body = {"firm_slug": s["firm"]["slug"], "valid_until": later()}
    assert hc.post_json(f"/api/w/{home['slug']}/engagements",
                        {**body, "scope_roles": ["accountant"]}).status_code == 422  # fmt: skip
    assert hc.post_json(f"/api/w/{home['slug']}/engagements",
                        {**body, "scope_roles": ["read_only"]}).status_code == 201  # fmt: skip

    # Expired grants give no access (checked on every request).
    eid = grant(s, ["read_only"]).json()["id"]
    staff(s, eid, "view@firm.test")
    viewer = s["staff"]["read_only"]["client"]
    assert viewer.get(f"/api/w/{s['client']['slug']}").status_code == 200
    set_context(tenant_id=UUID(s["client"]["id"]))
    expired = Engagement.objects.create(
        tenant_id=UUID(s["client"]["id"]), firm_tenant_id=UUID(s["firm"]["id"]),
        firm_name="Sarlis & Co", scope_roles=["read_only"],
        valid_until=timezone.now() - timedelta(minutes=1), granted_by=s["owner"],
    )  # fmt: skip
    set_context(tenant_id=UUID(s["firm"]["id"]))
    EngagementStaff.objects.create(
        tenant_id=UUID(s["firm"]["id"]), engagement_id=expired.id,
        client_tenant_id=UUID(s["client"]["id"]), membership_id=s["members"]["view@firm.test"],
        added_by=s["owner"],
    )  # fmt: skip
    s["cc"].post_json(f"/api/w/{s['client']['slug']}/engagements/{eid}/revoke", {})
    assert viewer.get(f"/api/w/{s['client']['slug']}").status_code == 404

    # Grants never change and are never deleted (database).
    set_context(tenant_id=UUID(s["client"]["id"]))
    with pytest.raises(DatabaseError), transaction.atomic():
        Engagement.objects.filter(id=eid).update(scope_roles=["accountant"])
    with pytest.raises(DatabaseError), transaction.atomic():
        Engagement.objects.filter(id=eid).delete()


def test_a_grant_can_be_limited_to_one_legal_entity(setup: dict[str, Any]) -> None:
    s = setup
    slug = s["client"]["slug"]
    second = s["cc"].post_json(f"/api/w/{slug}/entities",
                               {"legal_name": "Client X Holdings Ltd (Demo)",
                                "entity_type": "COMPANY"})  # fmt: skip
    assert second.status_code == 201, second.content
    made = grant(s, ["read_only"], legal_entity_id=second.json()["id"])
    assert made.status_code == 201, made.content
    assert staff(s, made.json()["id"], "view@firm.test").status_code == 201
    viewer = s["staff"]["read_only"]["client"]
    seen = viewer.get(f"/api/w/{slug}/entities").json()
    assert [e["legal_name"] for e in seen] == ["Client X Holdings Ltd (Demo)"]
    other = f"/api/w/{slug}/entities/{s['entity']['id']}"
    assert viewer.get(f"{other}/accounts").status_code == 404  # the other entity is not visible
    assert viewer.get(f"/api/w/{slug}/entities/{second.json()['id']}/accounts").status_code == 200
    bad = grant(s, ["read_only"], legal_entity_id=s["firm"]["id"])
    assert bad.status_code == 422  # not one of the client's entities
