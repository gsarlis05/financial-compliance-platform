"""Personal finances (M5-1, doc 11 §5): plain-words transactions over balanced, posted entries;
valuations as EXPECTED; net worth; spending by category; personal workspaces only."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.personal.models import Valuation

from ..ledger.conftest import join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]


@pytest.fixture
def home(make_user: Make, api_client: Make, make_workspace: Make) -> dict[str, Any]:
    owner = make_user("me@example.test")
    ws = make_workspace(owner, kind="PERSONAL", name="My finances")
    client = api_client(owner)
    entity = client.get(f"/api/w/{ws['slug']}/entities").json()[0]
    base = f"/api/w/{ws['slug']}/entities/{entity['id']}"
    done = client.post_json(f"{base}/personal/setup", {})
    assert done.json() == {"created": True}, done.content
    accounts = {a["code"]: a for a in client.get(f"{base}/personal/accounts").json()}
    return {"ws": ws, "client": client, "base": base, "p": f"{base}/personal", "a": accounts,
            "owner": owner}  # fmt: skip


def tx(  # noqa: PLR0917 (a readable test helper)
    h: dict[str, Any], kind: str, day: str, amount: str, text: str, account: str,
       other: str, client: Any = None) -> Any:  # fmt: skip
    body: dict[str, Any] = {"kind": kind, "date": day, "amount": amount, "description": text,
                            "account_id": h["a"][account]["id"]}  # fmt: skip
    body["to_account_id" if kind == "MOVED" else "category_id"] = h["a"][other]["id"]
    return (client or h["client"]).post_json(f"{h['p']}/transactions", body)


def balances(h: dict[str, Any], as_of: str = "2026-06-30") -> dict[str, str]:
    rows = h["client"].get(f"{h['p']}/accounts?as_of={as_of}").json()
    return {r["code"]: r["balance"] for r in rows}


def test_simplified_transactions_are_balanced_posted_entries(home: dict[str, Any]) -> None:
    h, c = home, home["client"]
    assert c.post_json(f"{h['p']}/setup", {}).json() == {"created": False}  # safe to repeat
    for code, amount in (("1100", "2000.00"), ("2100", "300.00")):
        made = c.post_json(f"{h['p']}/opening-balances",
                           {"account_id": h["a"][code]["id"], "date": "2026-01-01",
                            "amount": amount})  # fmt: skip
        assert made.status_code == 201, made.content
        assert made.json()["kind"] == "OPENING"
    spent = tx(h, "SPENT", "2026-01-10", "120.00", "Supermarket", "1100", "6100")
    assert spent.status_code == 201, spent.content
    assert (spent.json()["kind"], spent.json()["amount"]) == ("SPENT", "120.00")
    assert tx(h, "RECEIVED", "2026-01-25", "3000.00", "January salary", "1100", "4000"
              ).status_code == 201  # fmt: skip
    assert tx(h, "MOVED", "2026-01-28", "300.00", "Pay the card", "1100", "2100").status_code == 201
    b = balances(h)
    assert (b["1100"], b["2100"], b["6100"], b["4000"]) == ("4580.00", "0.00", "120.00", "3000.00")

    # Underneath: posted, balanced entries in the ledger (trial balance in balance).
    tb = c.get(f"{h['base']}/reports/trial-balance?as_of=2026-06-30").json()
    assert tb["total_debit"] == tb["total_credit"]
    posted = c.get(f"{h['base']}/journal-entries?status=POSTED").json()
    assert len(posted) == 5

    listed = c.get(f"{h['p']}/transactions?date_from=2026-01-01&date_to=2026-01-31").json()
    assert [t["kind"] for t in listed] == ["MOVED", "RECEIVED", "SPENT", "OPENING", "OPENING"]

    # Undo is a reversal (the original is kept, marked undone).
    undone = c.post_json(f"{h['p']}/transactions/{spent.json()['entry_id']}/undo",
                         {"reason": "Entered twice"})  # fmt: skip
    assert undone.status_code == 201, undone.content
    assert undone.json()["kind"] == "UNDO"
    later = c.get(f"{h['p']}/transactions?date_from=2026-01-01&date_to=2026-12-31").json()
    original = next(t for t in later if t["entry_id"] == spent.json()["entry_id"])
    assert original["undone"] is True
    assert c.post_json(f"{h['p']}/transactions/{spent.json()['entry_id']}/undo",
                       {"reason": "again"}).status_code == 409  # fmt: skip

    summary = c.get(f"{h['p']}/spending?date_from=2026-01-01&date_to=2026-12-31").json()
    assert [(x["name"], x["amount"]) for x in summary["income"]] == [("Salary", "3000.00")]
    assert summary["spending"] == []  # the groceries were undone
    assert (summary["total_income"], summary["left_over"]) == ("3000.00", "3000.00")


def test_valuations_are_expected_and_never_posted(home: dict[str, Any]) -> None:
    h, c = home, home["client"]
    c.post_json(
        f"{h['p']}/opening-balances",
        {"account_id": h["a"]["1100"]["id"], "date": "2026-01-01", "amount": "5000.00"},
    )
    c.post_json(f"{h['p']}/opening-balances",
                {"account_id": h["a"]["2200"]["id"], "date": "2026-01-01",
                 "amount": "150000.00"})  # fmt: skip
    house = {"account_id": h["a"]["1300"]["id"], "date": "2026-03-31", "value": "240000.00"}
    assert c.post_json(f"{h['p']}/valuations", house).status_code == 201
    corrected = c.post_json(f"{h['p']}/valuations", {**house, "value": "250000.00",
                                                       "note": "Agent's estimate"})  # fmt: skip
    assert corrected.json()["nature"] == "EXPECTED"
    history = c.get(f"{h['p']}/accounts/{h['a']['1300']['id']}/valuations").json()
    assert [(v["value"], v["superseded_at"] is None) for v in history] == [
        ("250000.00", True), ("240000.00", False)]  # fmt: skip

    nw = c.get(f"{h['p']}/net-worth?as_of=2026-06-30").json()
    lines = {a["code"]: a for a in nw["assets"] + nw["liabilities"]}
    assert (lines["1300"]["amount"], lines["1300"]["nature"], lines["1300"]["balance"]) == (
        "250000.00", "EXPECTED", "0.00")  # fmt: skip
    assert (lines["1100"]["amount"], lines["1100"]["nature"]) == ("5000.00", "ACTUAL")
    assert (nw["total_assets"], nw["total_liabilities"], nw["net_worth"]) == (
        "255000.00", "150000.00", "105000.00")  # fmt: skip
    assert nw["includes_valuations"] is True
    trend = {p["date"]: p for p in nw["trend"]}
    assert trend["2026-02-28"] == {"date": "2026-02-28", "net_worth": "-145000.00",
                                   "includes_valuations": False}  # fmt: skip
    assert trend["2026-06-30"]["net_worth"] == "105000.00"
    # The books hold only what happened: the valuation is not in the trial balance.
    tb = c.get(f"{h['base']}/reports/trial-balance?as_of=2026-06-30").json()
    assert all(r["code"] != "1300" or Decimal(r["debit"]) == 0 for r in tb["rows"])
    with transaction.atomic():
        set_context(tenant_id=h["ws"]["id"])
        with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
            Valuation.objects.filter(superseded_at__isnull=True).update(value=Decimal(1))
        with pytest.raises(DatabaseError, match="kept"), transaction.atomic():
            Valuation.objects.all().delete()


def test_validation_categories_and_years(home: dict[str, Any]) -> None:
    h, c = home, home["client"]
    for kind, account, other, amount, field in (
        ("SPENT", "1100", "4000", "10.00", "category_id"),  # income is not spending
        ("RECEIVED", "1100", "6100", "10.00", "category_id"),
        ("MOVED", "1100", "1100", "10.00", "to_account_id"),
        ("SPENT", "6100", "6200", "10.00", "account_id"),  # not a money account
        ("SPENT", "1100", "6100", "0", "amount"),
    ):
        refused = tx(h, kind, "2026-02-01", amount, "x", account, other)
        assert refused.status_code == 422, (kind, refused.content)
        assert field in refused.json()["errors"], refused.json()
    assert tx(h, "SPENT", "2026-02-01", "1.234", "x", "1100", "6100").status_code == 422
    # A new category; a transaction in an earlier year opens that year.
    pets = c.post_json(f"{h['p']}/accounts", {"kind": "EXPENSE", "name": "Pets"})
    assert pets.status_code == 201, pets.content
    assert pets.json()["code"] == "6910"
    h["a"]["6910"] = pets.json()
    assert tx(h, "SPENT", "2025-12-20", "40.00", "Vet", "1100", "6910").status_code == 201
    years = [y["name"] for y in c.get(f"{h['base']}/fiscal-years").json()]
    assert "2025" in years


def test_personal_workspaces_only_and_roles(
    home: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    business = make_workspace(home["owner"], kind="BUSINESS", name="My company")
    client = home["client"]
    entity = client.get(f"/api/w/{business['slug']}/entities").json()[0]
    refused = client.post_json(f"/api/w/{business['slug']}/entities/{entity['id']}/personal/setup",
                               {})  # fmt: skip
    assert refused.status_code == 403
    viewer = join(client, home["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{home['p']}/net-worth").status_code == 200
    assert tx(home, "SPENT", "2026-02-01", "5.00", "x", "1100", "6100", viewer).status_code == 403
    partner = join(client, home["ws"]["slug"], make_user("hm@example.test"), api_client,
                   "household_member")  # fmt: skip
    assert tx(home, "SPENT", "2026-02-01", "5.00", "Coffee", "1100", "6600",
              partner).status_code == 201  # fmt: skip
