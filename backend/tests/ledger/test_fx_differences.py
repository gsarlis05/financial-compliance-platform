"""Exchange differences (V1-2h2, #230): a payable in dollars is revalued at the closing rate
(unrealised) and, once paid at another rate, the euros left are cleared (realised); both as one
draft entry against the exchange-differences account, never posted automatically."""

from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.ledger.models import JournalLine

from .conftest import books
from .test_entries import act
from .test_foreign_currency import purchase, switch, usd

pytestmark = pytest.mark.django_db
__all__ = ["books"]


def setup(b: dict[str, Any]) -> None:
    b["client"].put_json(f"{b['base']}/ledger-settings", {"approval_policy": "NONE"})
    assert switch(b).status_code == 200
    made = purchase(b).json()  # 100 USD at 0.92: payable 92.00
    assert act(b, made["id"], "post").status_code == 200


def closing(b: dict[str, Any], day: str, rate: str) -> None:
    made = b["client"].post_json(f"{b['base']}/exchange-rates", {
        "rate_date": day, "base_currency": "USD", "quote_currency": "EUR", "rate": rate,
        "rate_type": "CLOSING", "source": "ECB reference rate (Demo)"})  # fmt: skip
    assert made.status_code == 201, made.content


def positions(b: dict[str, Any], on: str) -> dict[str, Any]:
    got = b["client"].get(f"{b['base']}/fx-positions?on={on}")
    assert got.status_code == 200, got.content
    return dict(got.json())


def prepare(b: dict[str, Any], on: str) -> Any:
    return b["client"].post_json(f"{b['base']}/fx-differences", {"on": on})


def test_revaluation_then_realised_on_payment(books: dict[str, Any]) -> None:
    setup(books)
    acc = books["accounts"]
    closing(books, "2026-03-31", "0.95")
    found = positions(books, "2026-03-31")
    # Only the payable: the expense is not a monetary item and keeps its rate.
    [p] = found["positions"]
    assert (p["account_code"], p["currency"], p["foreign"], p["euros"], p["revalued"],
            p["difference"], p["kind"]) == ("2100", "USD", "-100.00", "-92.00", "-95.00",
                                            "-3.00", "UNREALISED")  # fmt: skip
    assert (found["unrealised"], found["realised"]) == ("-3.00", "0.00")

    made = prepare(books, "2026-03-31")
    assert made.status_code == 201, made.content
    entry = made.json()
    assert entry["status"] == "DRAFT"  # never posted automatically
    lines = {ln["account_id"]: ln for ln in entry["lines"]}
    payable, loss = lines[acc["2100"]["id"]], lines[acc["7020"]["id"]]
    assert (payable["credit"], payable["txn_currency"], payable["txn_amount"],
            payable["fx_difference"], payable["counterparty_id"]) == (
        "3.00", "USD", "0.0000", "UNREALISED", books["supplier"])  # fmt: skip
    assert loss["debit"] == "3.00"
    # Waiting: a second draft is refused, so nothing is booked twice.
    assert positions(books, "2026-03-31")["waiting_entry_id"] == entry["id"]
    assert prepare(books, "2026-03-31").status_code == 409
    assert act(books, entry["id"], "post").status_code == 200
    assert positions(books, "2026-03-31")["positions"][0]["kind"] == ""
    assert prepare(books, "2026-03-31").status_code == 422  # nothing left to record

    # Paid on 15 April: 100 USD at 0.90 = 90.00 from the euro bank account.
    paid = books["client"].post_json(f"{books['base']}/journal-entries", {
        "accounting_date": "2026-04-15", "description": "Pay US supplier", "lines": [
            {"account_id": acc["2100"]["id"], "debit": "90.00",
             "counterparty_id": books["supplier"], "reference": "INV-US-7",
             **usd("100.00", "0.90")},
            {"account_id": acc["1300"]["id"], "credit": "90.00"}]}).json()  # fmt: skip
    assert act(books, paid["id"], "post").status_code == 200
    [p] = positions(books, "2026-04-30")["positions"]
    assert (p["foreign"], p["euros"], p["difference"], p["kind"]) == (
        "0.00", "-5.00", "5.00", "REALISED")  # fmt: skip
    realised = prepare(books, "2026-04-30").json()
    lines = {ln["account_id"]: ln for ln in realised["lines"]}
    assert (lines[acc["2100"]["id"]]["debit"], lines[acc["2100"]["id"]]["fx_difference"],
            lines[acc["2100"]["id"]]["exchange_rate"]) == ("5.00", "REALISED", None)  # fmt: skip
    assert lines[acc["7020"]["id"]]["credit"] == "5.00"
    assert act(books, realised["id"], "post").status_code == 200
    assert positions(books, "2026-04-30")["positions"][0]["euros"] == "0.00"

    # A posted difference is corrected like any entry: its reversal mirrors it exactly.
    back = books["client"].post_json(
        f"{books['base']}/journal-entries/{realised['id']}/reverse",
        {"reason": "Test of the reversal", "reversal_date": "2026-04-30"})  # fmt: skip
    assert back.status_code == 201, back.content
    mirror = {ln["account_id"]: ln for ln in back.json()["lines"]}[acc["2100"]["id"]]
    assert (mirror["credit"], mirror["fx_difference"]) == ("5.00", "REALISED")


def test_a_missing_rate_is_shown_never_guessed(books: dict[str, Any]) -> None:
    setup(books)
    found = positions(books, "2026-03-31")
    assert found["missing_rates"] == ["USD"]
    assert [p["kind"] for p in found["positions"]] == ["NO_RATE"]
    refused = prepare(books, "2026-03-31")
    assert refused.status_code == 422
    assert "no exchange differences" in refused.json()["detail"]


def test_the_database_keeps_difference_lines_in_shape(books: dict[str, Any]) -> None:
    assert switch(books).status_code == 200
    draft = purchase(books).json()  # a draft, so only the shape constraint can refuse
    set_context(tenant_id=UUID(books["ws"]["id"]))
    line = JournalLine.objects.get(entry_id=draft["id"], line_no=1)
    # A foreign amount on a difference line, or a rate on a realised one, is refused.
    for change in ({"fx_difference": "UNREALISED"},
                   {"fx_difference": "REALISED", "txn_debit": 0, "txn_credit": 0}):  # fmt: skip
        with pytest.raises(DatabaseError) as refused, transaction.atomic():
            JournalLine.objects.filter(id=line.id).update(**change)
        assert "ledger_line_txn_currency_shape" in str(refused.value)
