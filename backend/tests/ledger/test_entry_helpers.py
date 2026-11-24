"""Help for data entry (V1-2i, #231): favourite VAT codes per user and company, VAT code usage
and each account's usual code, and typing suggestions from the company's own entries only."""

from typing import Any

import pytest

from .conftest import Make, join

pytestmark = pytest.mark.django_db
S19, R9, Z0 = "CY:S19:open", "CY:R9:open", "CY:Z0:open"


def entry(books: dict[str, Any], description: str, *, memo: str = "", reference: str = "",
          vat: str | None = None, account: str = "6100") -> str:  # fmt: skip
    acc = books["accounts"]
    made = books["client"].post_json(f"{books['base']}/journal-entries", {
        "accounting_date": "2026-02-10", "description": description, "lines": [
            {"account_id": acc[account]["id"], "debit": "100.00", "memo": memo,
             "reference": reference, "vat_code_id": vat},
            {"account_id": acc["1300"]["id"], "credit": "100.00"}]})  # fmt: skip
    assert made.status_code == 201, made.content
    return str(made.json()["id"])


def suggest(books: dict[str, Any], field: str, q: str) -> list[tuple[str, int]]:
    got = books["client"].get(f"{books['base']}/entry-suggestions?field={field}&q={q}")
    assert got.status_code == 200, got.content
    return [(s["value"], s["uses"]) for s in got.json()]


def test_favourites_are_per_user_and_idempotent(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    c, base = books["client"], books["base"]
    assert c.get(f"{base}/vat-favourites").json() == {"vat_code_ids": []}
    assert c.put_json(f"{base}/vat-favourites/{R9}", {}).status_code == 200
    assert c.put_json(f"{base}/vat-favourites/{S19}", {}).status_code == 200
    again = c.put_json(f"{base}/vat-favourites/{R9}", {})
    assert again.json() == {"vat_code_ids": [R9, S19]}
    assert c.delete_json(f"{base}/vat-favourites/{R9}").json() == {"vat_code_ids": [S19]}
    assert c.delete_json(f"{base}/vat-favourites/{R9}").status_code == 200
    assert c.put_json(f"{base}/vat-favourites/CY:NOPE:open", {}).status_code == 404

    colleague = join(c, books["ws"]["slug"], make_user("acc@example.test"), api_client,
                     "accountant")  # fmt: skip
    assert colleague.get(f"{base}/vat-favourites").json() == {"vat_code_ids": []}


def test_suggestions_rank_by_start_then_use_and_skip_voided(books: dict[str, Any]) -> None:
    for text in ("Office rent March", "Office rent March", "Office rent April", "Back office"):
        entry(books, text)
    voided = entry(books, "Office party")
    c = books["client"]
    assert c.post_json(f"{books['base']}/journal-entries/{voided}/void", {}).status_code == 200
    assert suggest(books, "description", "office") == [
        ("Office rent March", 2), ("Office rent April", 1), ("Back office", 1)]  # fmt: skip
    assert suggest(books, "description", "OFFICE RENT A") == [("Office rent April", 1)]
    assert suggest(books, "description", "zzz") == []
    assert suggest(books, "description", "")[0] == ("Office rent March", 2)


def test_memo_and_reference_suggestions(books: dict[str, Any]) -> None:
    entry(books, "Fuel", memo="Fuel for van", reference="INV-1001")
    entry(books, "Fuel", memo="Fuel for van", reference="INV-1002")
    assert suggest(books, "memo", "fuel") == [("Fuel for van", 2)]
    # Equal use: the most recent first.
    assert [v for v, _ in suggest(books, "reference", "inv-")] == ["INV-1002", "INV-1001"]
    bad = books["client"].get(f"{books['base']}/entry-suggestions?field=account&q=x")
    assert bad.status_code == 422


def test_vat_usage_and_the_usual_code_of_an_account(books: dict[str, Any]) -> None:
    acc = books["accounts"]
    entry(books, "Stationery", vat=S19)
    entry(books, "Stationery", vat=S19)
    entry(books, "Books", vat=Z0)
    entry(books, "Hotel", vat=R9, account="6200")
    got = books["client"].get(f"{books['base']}/vat-usage").json()
    assert got["codes"] == [{"vat_code_id": S19, "uses": 2}, {"vat_code_id": R9, "uses": 1},
                            {"vat_code_id": Z0, "uses": 1}]  # fmt: skip
    usual = {a["account_id"]: a["vat_code_id"] for a in got["accounts"]}
    assert usual == {acc["6100"]["id"]: S19, acc["6200"]["id"]: R9}


def test_nothing_crosses_workspaces(
    books: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    entry(books, "Secret supplier invoice", vat=S19)
    books["client"].put_json(f"{books['base']}/vat-favourites/{S19}", {})
    other = make_user("other@example.test")
    ws = make_workspace(other, name="Other Co")
    oc = api_client(other)
    entity = oc.get(f"/api/w/{ws['slug']}/entities").json()[0]
    base = f"/api/w/{ws['slug']}/entities/{entity['id']}"
    assert oc.get(f"{base}/entry-suggestions?field=description&q=secret").json() == []
    assert oc.get(f"{base}/vat-usage").json() == {"codes": [], "accounts": []}
    assert oc.get(f"{base}/vat-favourites").json() == {"vat_code_ids": []}
    # And the other workspace's user cannot reach the first company at all.
    assert oc.get(f"{books['base']}/entry-suggestions?field=description&q=s").status_code in (
        403, 404)  # fmt: skip
