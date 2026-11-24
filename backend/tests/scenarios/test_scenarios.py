"""Scenarios (M7-1, AC-SC1 and the database part of AC-SC5): a draft on an approved base, its
typed overrides in order, private until shared, never changed once shared, copied and rebased,
and protected by the database."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.scenarios.models import Scenario, ScenarioOverride

from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


def approved_set(b: dict[str, Any], *, cutover: str = "2026-12-31", loan: bool = True) -> str:
    c, base = b["client"], b["base"]
    made = c.post_json(
        f"{base}/assumption-sets",
        {"name": "Plan", "cutover": cutover, "months": 12, "start_from": "EMPTY"},
    )
    assert made.status_code == 201, made.content
    set_id = made.json()["id"]
    if loan:
        added = c.post_json(
            f"{base}/assumption-sets/{set_id}/loans",
            {
                "code": "TERM-1",
                "name": "Term loan",
                "kind": "NEW",
                "structure": "ANNUITY",
                "term_months": 36,
                "annual_rate": "5",
                "amount": "30000",
                "drawdown_month": "2027-02-01",
            },
        )
        assert added.status_code == 201, added.content
    assert c.post_json(f"{base}/assumption-sets/{set_id}/approve", {}).status_code == 200
    return str(set_id)


@pytest.fixture
def plan(books: dict[str, Any]) -> dict[str, Any]:
    books["set_id"] = approved_set(books)
    books["url"] = f"{books['base']}/scenarios"
    return books


EIGHT = [
    ("PCT_CHANGE", {"driver": "revenue", "percent": "-15", "start_month": "2027-03"}),
    ("ABS_CHANGE", {"driver": "opex", "line": "OPEX.PAYROLL", "amount": "8000"}),
    ("TIMING_SHIFT", {"driver": "dso", "days": 60}),
    (
        "NEW_DEBT",
        {
            "code": "NEW-1",
            "amount": "200000",
            "drawdown_month": "2027-04",
            "term_months": 60,
            "annual_rate": "6",
        },
    ),
    ("NEW_HIRE", {"role": "Analyst", "gross_monthly_salary": "3000", "start_month": "2027-03"}),
    ("CAPEX", {"amount": "150000", "month": "2027-05", "useful_life_months": 96}),
    ("ONE_OFF", {"amount": "40000", "month": "2027-07", "treatment": "EXPENSE"}),
    ("RATE_CHANGE", {"target": "LOANS", "loans": ["TERM-1"], "points": "2"}),
]


def test_draft_overrides_share_copy_and_archive(  # noqa: PLR0915 (one story)
    plan: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    c, url, set_id = plan["client"], plan["url"], plan["set_id"]
    made = c.post_json(
        url, {"name": "Downside", "base_set_id": set_id, "description": "Revenue falls"}
    )
    assert made.status_code == 201, made.content
    s = made.json()
    assert (s["status"], s["nature"], s["base_set_id"]) == ("DRAFT", "HYPOTHETICAL", set_id)
    surl = f"{url}/{s['id']}"

    ids = []
    for kind, params in EIGHT:
        added = c.post_json(
            f"{surl}/overrides", {"type": kind, "params": params, "rationale": f"why {kind}"}
        )
        assert added.status_code == 201, (kind, added.content)
        ids.append(added.json()["id"])
    refused = c.post_json(
        f"{surl}/overrides",
        {
            "type": "PCT_CHANGE",
            "params": {"driver": "revenue", "percent": "5", "start_month": "2029-01"},
        },
    )
    assert refused.status_code == 422
    assert "outside the base's horizon" in refused.json()["detail"]
    assert c.post_json(f"{surl}/overrides", {"type": "MAGIC", "params": {}}).status_code == 422

    detail = c.get(surl).json()
    assert [o["type"] for o in detail["overrides"]] == [k for k, _ in EIGHT]
    assert [o["seq"] for o in detail["overrides"]] == list(range(1, 9))
    assert detail["base"] == {
        "id": set_id,
        "name": "Plan",
        "version": 1,
        "status": "APPROVED",
        "newer_version_approved": False,
        "first_month": "2027-01-01",
        "last_month": "2027-12-01",
        "loans": ["TERM-1"],
    }

    # Change, reorder and remove (the rest close up in order).
    changed = c.put_json(
        f"{surl}/overrides/{ids[0]}",
        {
            "type": "PCT_CHANGE",
            "params": {"driver": "revenue", "percent": "-20"},
            "rationale": "worse",
        },
    )
    assert changed.status_code == 200, changed.content
    assert changed.json()["params"]["percent"] == "-20"
    order = list(reversed(ids))
    reordered = c.put_json(f"{surl}/overrides", {"order": order})
    assert [o["id"] for o in reordered.json()] == order
    assert c.put_json(f"{surl}/overrides", {"order": order[:-1]}).status_code == 422
    assert c.delete_json(f"{surl}/overrides/{ids[3]}").status_code == 204
    left = c.get(surl).json()["overrides"]
    assert [o["seq"] for o in left] == list(range(1, 8))
    assert ids[3] not in [o["id"] for o in left]
    renamed = c.patch_json(surl, {"name": "Downside 20%", "description": "Revenue -20%"})
    assert renamed.json()["name"] == "Downside 20%"

    # A draft is private to its author.
    other = join(c, plan["ws"]["slug"], make_user("acc@example.test"), api_client, "accountant")
    assert other.get(surl).status_code == 404
    assert s["id"] not in [x["id"] for x in other.get(url).json()]

    shared = c.post_json(f"{surl}/share", {})
    assert shared.status_code == 200, shared.content
    assert shared.json()["status"] == "SHARED"
    assert other.get(surl).status_code == 200
    for late in (
        c.post_json(f"{surl}/overrides", {"type": EIGHT[0][0], "params": EIGHT[0][1]}),
        c.patch_json(surl, {"name": "X"}),
        c.delete_json(f"{surl}/overrides/{ids[0]}"),
        c.post_json(f"{surl}/share", {}),
    ):
        assert late.status_code == 409, late.content

    # Anyone who can run plans can copy a shared scenario into a draft of their own.
    copied = other.post_json(f"{surl}/copy", {})
    assert copied.status_code == 201, copied.content
    cp = copied.json()
    assert (cp["status"], cp["name"], cp["copied_from_id"]) == (
        "DRAFT",
        "Copy of Downside 20%",
        s["id"],
    )
    assert [o["params"] for o in other.get(f"{url}/{cp['id']}").json()["overrides"]] == [
        o["params"] for o in left
    ]
    assert c.get(f"{url}/{cp['id']}").status_code == 404  # the copy is the other user's draft

    # Archiving someone else's scenario needs planning.publish; the author can.
    assert other.post_json(f"{surl}/archive", {}).status_code == 403
    archived = c.post_json(f"{surl}/archive", {})
    assert archived.json()["status"] == "ARCHIVED"
    assert c.post_json(f"{surl}/archive", {}).status_code == 409

    actions = list(
        AuditEvent.objects.filter(subject_id=s["id"])
        .order_by("seq")
        .values_list("action", flat=True)
    )
    assert actions[0] == "scenarios.created"
    assert actions[-2:] == ["scenarios.shared", "scenarios.archived"]
    assert {
        "scenarios.override_added",
        "scenarios.override_changed",
        "scenarios.reordered",
        "scenarios.override_removed",
        "scenarios.renamed",
    } <= set(actions)


def test_base_rules_rebase_and_permissions(
    plan: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    c, url, base = plan["client"], plan["url"], plan["base"]
    draft_set = c.post_json(
        f"{base}/assumption-sets",
        {"name": "Draft", "cutover": "2026-12-31", "months": 12, "start_from": "EMPTY"},
    )
    refused = c.post_json(url, {"name": "S", "base_set_id": draft_set.json()["id"]})
    assert refused.status_code == 422
    assert "approved assumption set (this one is draft)" in refused.json()["detail"]
    unknown = c.post_json(url, {"name": "S", "base_set_id": "00000000-0000-0000-0000-000000000000"})
    assert unknown.status_code == 422

    s = c.post_json(url, {"name": "Rates up", "base_set_id": plan["set_id"]}).json()
    surl = f"{url}/{s['id']}"
    for kind, params in (
        EIGHT[0],
        EIGHT[7],
        ("ONE_OFF", {"amount": "500", "month": "2027-01", "treatment": "EXPENSE"}),
    ):
        assert c.post_json(f"{surl}/overrides", {"type": kind, "params": params}).status_code == 201

    # A newer approved version of the base: the scenario keeps its base and says so.
    v2 = c.post_json(f"{base}/assumption-sets/{plan['set_id']}/revise", {}).json()
    c.post_json(f"{base}/assumption-sets/{v2['id']}/approve", {})
    b = c.get(surl).json()["base"]
    assert (b["status"], b["newer_version_approved"]) == ("SUPERSEDED", True)
    rebased = c.post_json(f"{surl}/copy", {"name": "Rates up (v2)", "base_set_id": v2["id"]})
    assert rebased.status_code == 201, rebased.content
    assert rebased.json()["base_set_id"] == v2["id"]
    assert len(c.get(f"{url}/{rebased.json()['id']}").json()["overrides"]) == 3
    # A base whose horizon starts later, with no TERM-1 loan: overrides that do not fit refuse.
    later = approved_set(plan, cutover="2027-06-30", loan=False)
    misfit = c.post_json(f"{surl}/copy", {"base_set_id": later})
    assert misfit.status_code == 422
    assert misfit.json()["detail"] == (
        "Override 1 (PCT_CHANGE) does not fit the new base: start_month: 03/2027 is outside "
        "the base's horizon (07/2027 to 06/2028)."
    )

    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client, "read_only")
    assert viewer.get(url).status_code == 200
    assert viewer.post_json(url, {"name": "S", "base_set_id": plan["set_id"]}).status_code == 403
    manager = join(
        c, plan["ws"]["slug"], make_user("fm@example.test"), api_client, "finance_manager"
    )
    c.post_json(f"{surl}/share", {})
    assert manager.post_json(f"{surl}/archive", {}).status_code == 200  # planning.publish


def test_the_database_keeps_scenarios(plan: dict[str, Any]) -> None:
    c, url = plan["client"], plan["url"]
    s = c.post_json(url, {"name": "S", "base_set_id": plan["set_id"]}).json()
    o = c.post_json(f"{url}/{s['id']}/overrides", {"type": EIGHT[0][0], "params": EIGHT[0][1]})
    c.post_json(f"{url}/{s['id']}/share", {})
    set_context(tenant_id=UUID(plan["ws"]["id"]))
    shared = Scenario.objects.get(id=s["id"])
    with pytest.raises(DatabaseError, match="copy it to change it"), transaction.atomic():
        Scenario.objects.filter(id=s["id"]).update(name="Changed")
    with pytest.raises(DatabaseError, match="never change"), transaction.atomic():
        Scenario.objects.filter(id=s["id"]).update(
            base_set_id=shared.base_set_id,
            created_by_id=plan["owner"].id,
            legal_entity_id=UUID(int=1),
        )
    with (
        pytest.raises(DatabaseError, match="kept"),
        transaction.atomic(),
        connection.cursor() as cur,
    ):
        cur.execute("DELETE FROM scenarios_scenario WHERE id = %s", [s["id"]])
    with pytest.raises(DatabaseError, match="draft"), transaction.atomic():
        ScenarioOverride.objects.filter(id=o.json()["id"]).update(rationale="later")
    with pytest.raises(DatabaseError, match="draft"), transaction.atomic():
        ScenarioOverride.objects.filter(id=o.json()["id"]).delete()
    with pytest.raises(DatabaseError, match="starts as a draft"), transaction.atomic():
        Scenario.objects.create(
            tenant_id=shared.tenant_id,
            legal_entity_id=shared.legal_entity_id,
            base_set_id=shared.base_set_id,
            name="X",
            status="SHARED",
            shared_at=shared.shared_at,
            created_by_id=plan["owner"].id,
        )
    draft_set = c.post_json(
        f"{plan['base']}/assumption-sets",
        {"name": "Draft", "cutover": "2026-12-31", "months": 12, "start_from": "EMPTY"},
    ).json()
    set_context(tenant_id=UUID(plan["ws"]["id"]))
    with pytest.raises(DatabaseError, match="approved assumption set"), transaction.atomic():
        Scenario.objects.create(
            tenant_id=shared.tenant_id,
            legal_entity_id=shared.legal_entity_id,
            base_set_id=draft_set["id"],
            name="X",
            created_by_id=plan["owner"].id,
        )
    # Archiving a shared scenario is allowed; nothing changes after that.
    Scenario.objects.filter(id=s["id"]).update(status="ARCHIVED", archived_at=shared.shared_at)
    with pytest.raises(DatabaseError), transaction.atomic():
        Scenario.objects.filter(id=s["id"]).update(status="SHARED")
