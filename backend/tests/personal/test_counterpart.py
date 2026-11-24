"""Counterpart hints (M5-3, doc 11 §4.2): opt-in, suggest-only, confirmed in the personal
workspace; nothing flows between workspaces automatically and the business never sees the link."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.personal.models import CounterpartDecision, CounterpartLink

from ..ledger.conftest import books
from ..ledger.test_closing import no_approval, post

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def both(books: dict[str, Any], make_workspace: Make) -> dict[str, Any]:
    """The same person owns a business (books) and a personal workspace."""
    no_approval(books)
    c = books["client"]
    ws = make_workspace(books["owner"], kind="PERSONAL", name="My finances")
    entity = c.get(f"/api/w/{ws['slug']}/entities").json()[0]
    base = f"/api/w/{ws['slug']}/entities/{entity['id']}"
    assert c.post_json(f"{base}/personal/setup", {}).status_code == 200
    accounts = {a["code"]: a for a in c.get(f"{base}/personal/accounts").json()}
    return {"books": books, "c": c, "ws": ws, "p": f"{base}/personal", "base": base,
            "a": accounts}  # fmt: skip


def settle(tenant_id: str) -> None:
    """Run the deferred ledger checks now, in the workspace that posted. Each request commits
    on its own in production; here the whole test is one transaction across two workspaces."""
    set_context(tenant_id=UUID(tenant_id))
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def pay(h: dict[str, Any], *lines: tuple[str, str, str], day: str) -> dict[str, Any]:
    entry = post(h["books"], *lines, day=day)
    settle(h["books"]["ws"]["id"])
    return entry


def link(h: dict[str, Any], client: Any = None) -> Any:
    b = h["books"]
    return (client or h["c"]).post_json(f"{h['p']}/counterpart-links", {
        "business_slug": b["ws"]["slug"], "business_entity_id": b["entity"]["id"],
        "business_account_id": b["accounts"]["2020"]["id"],
        "label": "Demo Trading · 2020 Director loans", "account_id": h["a"]["1100"]["id"],
        "category_id": h["a"]["4000"]["id"], "since": "2026-01-01",
    })  # fmt: skip


def suggestions(h: dict[str, Any], made: dict[str, Any]) -> list[dict[str, Any]]:
    """What the page offers: debits on the linked business account (read in the business
    workspace, with the person's own permission there) not yet decided in the personal one."""
    gl = h["c"].get(
        f"/api/w/{made['business_slug']}/entities/{made['business_entity_id']}/reports/"
        f"general-ledger/{made['business_account_id']}?date_from={made['since']}"
        "&date_to=2026-12-31"
    )
    assert gl.status_code == 200, gl.content
    done = h["c"].get(f"{h['p']}/counterpart-links/{made['id']}/decisions").json()
    seen = {d["business_entry_id"] for d in done}
    return [ln for ln in gl.json()["lines"]
            if ln["debit"] != "0.00" and ln["entry_id"] not in seen]  # fmt: skip


def test_hint_is_opt_in_confirm_only_and_recorded_once(both: dict[str, Any]) -> None:
    h, c = both, both["c"]
    # Nothing is suggested, or recorded, without a link (opt-in).
    assert c.get(f"{h['p']}/counterpart-links").json() == []
    repaid = pay(h, ("2020", "1500.00", "0.00"), ("1300", "0.00", "1500.00"), day="2026-03-20")
    pay(h, ("2020", "0.00", "800.00"), ("1300", "800.00", "0.00"), day="2026-03-25")
    before = c.get(f"{h['p']}/transactions?date_from=2026-01-01&date_to=2026-12-31").json()
    assert before == []

    made = link(h)
    assert made.status_code == 201, made.content
    hints = suggestions(h, made.json())
    assert [(s["entry_id"], s["debit"]) for s in hints] == [(repaid["id"], "1500.00")]

    # Still nothing posted in the personal books until the person confirms.
    assert c.get(f"{h['p']}/transactions?date_from=2026-01-01&date_to=2026-12-31").json() == []
    body = {"business_entry_id": hints[0]["entry_id"], "date": "2026-03-20",
            "amount": "1500.00", "description": "Director loan repaid by Demo Trading"}  # fmt: skip
    confirmed = c.post_json(f"{h['p']}/counterpart-links/{made.json()['id']}/confirm", body)
    assert confirmed.status_code == 201, confirmed.content
    assert confirmed.json()["decision"] == "CONFIRMED"
    listed = c.get(f"{h['p']}/transactions?date_from=2026-01-01&date_to=2026-12-31").json()
    assert [(t["kind"], t["amount"], t["entry_id"]) for t in listed] == [
        ("RECEIVED", "1500.00", confirmed.json()["personal_entry_id"])
    ]
    settle(h["ws"]["id"])
    assert suggestions(h, made.json()) == []  # not offered again

    again = c.post_json(f"{h['p']}/counterpart-links/{made.json()['id']}/confirm", body)
    assert again.status_code == 409, again.content
    dismissed = c.post_json(f"{h['p']}/counterpart-links/{made.json()['id']}/dismiss", body)
    assert dismissed.status_code == 409, dismissed.content

    # The business books are untouched, and the business workspace has no personal route.
    tb = c.get(f"{h['books']['base']}/reports/trial-balance?as_of=2026-12-31").json()
    assert tb["total_debit"] == tb["total_credit"]
    biz = f"{h['books']['base']}/personal/counterpart-links"
    assert c.get(biz).status_code in {403, 404}


def test_dismiss_revoke_and_isolation(both: dict[str, Any], make_user: Make,
                                      api_client: Make) -> None:  # fmt: skip
    h, c = both, both["c"]
    entry = pay(h, ("2020", "200.00", "0.00"), ("1300", "0.00", "200.00"), day="2026-04-02")
    made = link(h).json()
    body = {"business_entry_id": entry["id"], "date": "2026-04-02", "amount": "200.00",
            "description": "Paid a supplier on my behalf"}  # fmt: skip
    dismissed = c.post_json(f"{h['p']}/counterpart-links/{made['id']}/dismiss", body)
    assert dismissed.status_code == 201, dismissed.content
    assert dismissed.json()["personal_entry_id"] is None
    assert c.get(f"{h['p']}/transactions?date_from=2026-01-01&date_to=2026-12-31").json() == []

    # The link is validated against the personal books (money account, income category).
    bad = c.post_json(f"{h['p']}/counterpart-links", {
        **{k: made[k] for k in ("business_slug", "business_entity_id", "business_account_id",
                                "label", "since")},
        "account_id": h["a"]["4000"]["id"], "category_id": h["a"]["1100"]["id"],
    })  # fmt: skip
    assert bad.status_code == 422, bad.content

    # Another person cannot see the link (personal workspaces are private).
    stranger = api_client(make_user("stranger@example.test"))
    assert stranger.get(f"{h['p']}/counterpart-links").status_code == 404

    # Revoked: gone from the list, and no more decisions; earlier ones are kept.
    gone = c.post_json(f"{h['p']}/counterpart-links/{made['id']}/revoke", {})
    assert gone.status_code == 204, gone.content
    assert c.get(f"{h['p']}/counterpart-links").json() == []
    later = c.post_json(f"{h['p']}/counterpart-links/{made['id']}/confirm",
                        {**body, "business_entry_id": h["books"]["entity"]["id"]})  # fmt: skip
    assert later.status_code == 404, later.content

    # Links can only be revoked and decisions never change (database).
    set_context(tenant_id=UUID(h["ws"]["id"]))
    with pytest.raises(DatabaseError), transaction.atomic():
        CounterpartLink.objects.filter(id=made["id"]).update(label="changed")
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        CounterpartDecision.objects.filter(link_id=made["id"]).update(amount="1.00")
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        CounterpartDecision.objects.filter(link_id=made["id"]).delete()
