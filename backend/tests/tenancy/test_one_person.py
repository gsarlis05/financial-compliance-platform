"""One-person workspaces (V1-1, #207, ADR-0055): the person who prepared something may approve it,
only while the workspace has exactly one member; every such approval is recorded as
self-approved, and the database refuses a self-approval anywhere else."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.kpi.models import CustomKpi
from fcp.modules.ledger.models import JournalEntry, PeriodUnlock
from fcp.modules.mgmt_reporting.exports import status_line
from fcp.modules.mgmt_reporting.models import ReportPack
from fcp.modules.tenancy.models import Membership, Tenant

from ..goals.test_goals import budget, g
from ..kpi.test_kpis import k
from ..ledger.conftest import books, join
from ..ledger.test_corrections import _decide, _lock_march, _request
from ..ledger.test_entries import SALE, act, create
from ..mgmt_reporting.test_packs import act as pack_act
from ..mgmt_reporting.test_packs import explain_all, generate

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "g", "k"]


def one_person(books: dict[str, Any], enabled: bool = True, client: Any = None) -> Any:
    return (client or books["client"]).put_json(
        f"/api/w/{books['ws']['slug']}/one-person", {"enabled": enabled}
    )


def _events(books: dict[str, Any], action: str) -> list[AuditEvent]:
    set_context(tenant_id=UUID(books["ws"]["id"]))
    return list(AuditEvent.objects.filter(action=action).order_by("occurred_at"))


def test_the_setting_holds_only_for_one_person(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    slug, client = books["ws"]["slug"], books["client"]
    shown = client.get(f"/api/w/{slug}/one-person").json()
    assert shown == {"enabled": False, "active": False, "blockers": []}
    assert client.get(f"/api/w/{slug}").json()["one_person"] is False

    on = one_person(books)
    assert on.status_code == 200, on.content
    assert on.json() == {"enabled": True, "active": True, "blockers": []}
    assert client.get(f"/api/w/{slug}").json()["one_person"] is True
    assert [e.changes for e in _events(books, "tenancy.one_person.enabled")] == [
        {"one_person": True}
    ]

    # While it is on, nobody can be added: no invitation, no engagement grant.
    invite = client.post_json(
        f"/api/w/{slug}/invitations", {"email": "x@example.test", "role_key": "reviewer"}
    )
    assert invite.status_code == 409
    assert "one-person workspace" in invite.json()["detail"]
    grant = client.post_json(
        f"/api/w/{slug}/engagements",
        {"firm_slug": "any-firm", "scope_roles": ["accountant"],
         "valid_until": (timezone.now() + timedelta(days=30)).isoformat()},
    )  # fmt: skip
    assert grant.status_code == 409

    # Off again: a second person can join, and then it cannot be turned on.
    assert one_person(books, False).json()["enabled"] is False
    join(client, slug, make_user("second@example.test"), api_client, "reviewer")
    refused = one_person(books)
    assert refused.status_code == 409
    assert "2 active members" in refused.json()["detail"]
    blockers = client.get(f"/api/w/{slug}/one-person").json()["blockers"]
    assert blockers == ["The workspace has 2 active members; it must have exactly one."]


def test_pending_invitations_and_permissions(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    slug, client = books["ws"]["slug"], books["client"]
    issued = client.post_json(
        f"/api/w/{slug}/invitations", {"email": "later@example.test", "role_key": "reviewer"}
    )
    assert issued.status_code == 201
    refused = one_person(books)
    assert refused.status_code == 409
    assert "An invitation is still pending." in refused.json()["detail"]
    # Only people who manage members may see or change the setting.
    viewer = join(client, slug, make_user("ro@example.test"), api_client, "read_only")
    assert viewer.get(f"/api/w/{slug}/one-person").status_code == 403
    assert one_person(books, client=viewer).status_code == 403


def test_the_database_holds_the_rule(books: dict[str, Any], make_user: Make) -> None:
    tenant_id = UUID(books["ws"]["id"])
    set_context(tenant_id=tenant_id)
    # A self-approval outside a one-person workspace is refused, whatever the code does.
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    with pytest.raises(DatabaseError, match="only in a one-person workspace"), transaction.atomic():
        JournalEntry.objects.filter(id=entry["id"]).update(
            status="APPROVED", approved_by=books["owner"], approved_at=timezone.now(),
            self_approved=True,
        )  # fmt: skip
    # Without the flag, the approver can never be the preparer.
    with (
        pytest.raises(DatabaseError, match="ledger_entry_approver_not_preparer"),
        transaction.atomic(),
    ):
        JournalEntry.objects.filter(id=entry["id"]).update(
            status="APPROVED", approved_by=books["owner"], approved_at=timezone.now()
        )
    Tenant.objects.filter(id=tenant_id).update(one_person=True)
    # While it is on, a second active member cannot be added, even directly.
    with pytest.raises(DatabaseError, match="turn that setting off"), transaction.atomic():
        Membership.objects.create(tenant_id=tenant_id, user=make_user("sneak@example.test"))
    # And it cannot be switched on while two members exist.
    Tenant.objects.filter(id=tenant_id).update(one_person=False)
    Membership.objects.create(tenant_id=tenant_id, user=make_user("second@example.test"))
    with pytest.raises(DatabaseError, match="exactly one active member"), transaction.atomic():
        Tenant.objects.filter(id=tenant_id).update(one_person=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT tenancy_one_person(%s)", [tenant_id])
        assert cursor.fetchone() == (False,)


def test_journal_entries_and_period_unlocks(books: dict[str, Any]) -> None:
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    assert act(books, entry["id"], "approve").status_code == 403  # setting off
    assert one_person(books).status_code == 200
    approved = act(books, entry["id"], "approve")
    assert approved.status_code == 200, approved.content
    assert approved.json()["self_approved"] is True
    posted = act(books, entry["id"], "post")
    assert posted.json()["status"] == "POSTED"
    assert posted.json()["self_approved"] is True
    audited = _events(books, "ledger.entry.approved")[-1]
    assert audited.changes["self_approved"] is True

    # A locked period opens on the requester's own approval, recorded as such.
    period_id = _lock_march(books)
    unlock = _request(books, books["client"], period_id).json()
    opened = _decide(books, books["client"], unlock["id"])
    assert opened.status_code == 200, opened.content
    assert (opened.json()["status"], opened.json()["self_approved"]) == ("ACTIVE", True)
    assert opened.json()["second_approver_id"] is None
    late = create(books, *SALE).json()
    act(books, late["id"], "submit")
    act(books, late["id"], "approve")
    assert act(books, late["id"], "post").json()["unlock_request_id"] == unlock["id"]

    # Turned off, the rule is back at once.
    one_person(books, False)
    again = create(books, *SALE, day="2026-04-15").json()
    act(books, again["id"], "submit")
    refused = act(books, again["id"], "approve")
    assert refused.json()["code"] == "ledger.entry.sod_violation"
    set_context(tenant_id=UUID(books["ws"]["id"]))
    assert PeriodUnlock.objects.get(id=unlock["id"]).self_approved is True


def test_budgets_kpis_and_report_packs(g: dict[str, Any]) -> None:
    c, base = g["client"], g["base"]
    assert one_person(g).status_code == 200
    # Budget: segregation of duties stays on; the submitter approves as self-approved.
    assert c.get(f"{base}/budget-settings").json()["sod_required"] is True
    made = c.post_json(f"{base}/budgets", {"name": "Plan 2026", "fiscal_year_id": g["fy"]["id"]})
    version = made.json()["open_version_id"]
    lines = [{"taxonomy_code": "REV.SALES", "amounts": {"2026-01-01": "100.00"}}]
    c.put_json(f"{base}/budget-versions/{version}/lines", {"lines": lines})
    c.post_json(f"{base}/budget-versions/{version}/submit", {})
    approved = c.post_json(f"{base}/budget-versions/{version}/approve", {})
    assert approved.status_code == 200, approved.content
    assert (approved.json()["self_approved"], approved.json()["sod_applied"]) == (True, False)

    # Workspace KPI: its author decides.
    kpi = c.post_json(f"{base}/custom-kpis", {
        "key": "MARKUP", "name": "Mark-up", "formula": 'flow("REVENUE") / flow("COST_OF_SALES")',
        "display": "ratio", "direction": "HIGHER_BETTER", "scope": "WORKSPACE",
    }).json()  # fmt: skip
    decided = c.post_json(f"{base}/custom-kpis/{kpi['id']}/approve", {})
    assert decided.status_code == 200, decided.content
    assert (decided.json()["status"], decided.json()["self_approved"]) == ("APPROVED", True)

    # Report pack: its preparer finalises; the exports say so.
    pack = generate(g)
    explain_all(g, pack)
    pack_act(c, g, pack["id"], "regenerate")
    assert pack_act(c, g, pack["id"], "submit").status_code == 200
    final = pack_act(c, g, pack["id"], "finalise")
    assert final.status_code == 200, final.content
    assert (final.json()["status"], final.json()["self_approved"]) == ("FINAL", True)
    set_context(tenant_id=UUID(g["ws"]["id"]))
    stored = ReportPack.objects.get(id=pack["id"])
    assert status_line(stored, "en") == (
        "Status: Final · Version 1 · self-approved (one-person workspace)"
    )
    assert status_line(stored, "el").endswith("αυτοέγκριση (χώρος εργασίας ενός ατόμου)")
    assert CustomKpi.objects.get(id=kpi["id"]).self_approved is True
    assert _events(g, "mgmt_reporting.pack_finalised")[-1].changes["self_approved"] is True


def test_without_the_setting_nothing_changes(g: dict[str, Any]) -> None:
    """The earlier rules hold: the preparer of a pack cannot finalise it."""
    budget(g)
    pack = generate(g)
    explain_all(g, pack)
    pack_act(g["client"], g, pack["id"], "regenerate")
    pack_act(g["client"], g, pack["id"], "submit")
    own = pack_act(g["client"], g, pack["id"], "finalise")
    assert own.status_code == 403
    set_context(tenant_id=UUID(g["ws"]["id"]))
    with pytest.raises(DatabaseError, match="cannot be its preparer"), transaction.atomic():
        ReportPack.objects.filter(id=pack["id"]).update(
            status="FINAL", reviewed_by=g["owner"], finalised_at=timezone.now()
        )
    # Marked self-approved, it is still refused: the workspace is not one-person.
    with pytest.raises(DatabaseError, match="cannot be its preparer"), transaction.atomic():
        ReportPack.objects.filter(id=pack["id"]).update(
            status="FINAL", reviewed_by=g["owner"], finalised_at=timezone.now(),
            self_approved=True,
        )  # fmt: skip
