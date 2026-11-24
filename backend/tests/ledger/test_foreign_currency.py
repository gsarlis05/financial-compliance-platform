"""Foreign-currency lines (V1-2h, #219; owner decision 2026-11-23): an amount in a foreign
currency is converted into euros at the rate of the transaction's date and time, recorded on the
line with when it applied and its source; foreign currency is switched on per entity with the
account exchange differences go to."""

from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger.models import JournalLine

from .conftest import books
from .test_entries import act

pytestmark = pytest.mark.django_db
__all__ = ["books"]
AT = "2026-03-10T14:32:00+02:00"
BANK = "Bank of Cyprus card statement (Demo)"


def switch(b: dict[str, Any], on: bool = True, account: str | None = "7020") -> Any:
    body = {"multi_currency_enabled": on,
            "fx_account_id": b["accounts"][account]["id"] if account else None}  # fmt: skip
    return b["client"].put_json(f"{b['base']}/currency-settings", body)


def usd(amount: str = "100.00", rate: str = "0.9200", **extra: Any) -> dict[str, Any]:
    return {"txn_currency": "USD", "txn_amount": amount, "exchange_rate": rate, "rate_at": AT,
            "rate_source": BANK, **extra}  # fmt: skip


def purchase(b: dict[str, Any], euros: str = "92.00", **fx: Any) -> Any:
    """Software bought in dollars on account: expense and payable both in USD."""
    acc = b["accounts"]
    if "supplier" not in b:
        b["supplier"] = b["client"].post_json(f"{b['base']}/counterparties", {
            "code": "US1", "name": "Supplier US (Demo)", "kind": "SUPPLIER",
            "country": "US"}).json()["id"]  # fmt: skip
    supplier = b["supplier"]
    lines = [{"account_id": acc["6100"]["id"], "debit": euros, **usd(**fx)},
             {"account_id": acc["2100"]["id"], "credit": euros, "counterparty_id": supplier,
              "reference": "INV-US-7", **usd(**fx)}]  # fmt: skip
    return b["client"].post_json(f"{b['base']}/journal-entries", {
        "accounting_date": "2026-03-10", "description": "Software subscription (USD)",
        "lines": lines})  # fmt: skip


def test_the_switch_needs_an_exchange_differences_account(books: dict[str, Any]) -> None:
    url = f"{books['base']}/currency-settings"
    assert books["client"].get(url).json() == {
        "functional_currency": "EUR",
        "multi_currency_enabled": False,
        "fx_account_id": None,
    }
    refused = purchase(books)
    assert refused.status_code == 422
    assert "foreign currency is off for this entity" in refused.json()["detail"]
    assert switch(books, account=None).status_code == 422
    assert switch(books, account="1300").status_code == 422  # not an income or expense account
    on = switch(books)
    assert on.status_code == 200, on.content
    assert on.json() == {"functional_currency": "EUR", "multi_currency_enabled": True,
                         "fx_account_id": books["accounts"]["7020"]["id"]}  # fmt: skip
    assert books["client"].get(books["base"]).json()["multi_currency_enabled"] is True
    set_context(tenant_id=UUID(books["ws"]["id"]))
    assert AuditEvent.objects.filter(action="ledger.currency_settings.updated").count() == 1


def test_a_purchase_in_dollars(books: dict[str, Any]) -> None:
    switch(books)
    # The euro amount must be the dollar amount at the rate, rounded half up to the cent.
    wrong = purchase(books, euros="92.01")
    assert wrong.status_code == 422
    assert "100.00 USD at 0.9200 is 92.00 EUR, not 92.01" in wrong.json()["detail"]
    assert purchase(books, rate_source=" ").status_code == 422
    assert purchase(books, rate_at=None).status_code == 422
    assert purchase(books, amount="100.001").status_code == 422
    assert purchase(books, rate="0").status_code == 422
    # Half up: 33.33 USD at 0.915 is 30.49695, so 30.50 EUR.
    assert purchase(books, euros="30.50", amount="33.33", rate="0.915").status_code == 201

    made = purchase(books)
    assert made.status_code == 201, made.content
    line = made.json()["lines"][0]
    assert (line["debit"], line["txn_currency"], line["txn_amount"], line["exchange_rate"],
            line["rate_source"]) == ("92.00", "USD", "100.0000", "0.9200000000", BANK)  # fmt: skip
    assert line["rate_at"].startswith("2026-03-10T12:32:00")  # stored in UTC
    entry_id = made.json()["id"]
    assert act(books, entry_id, "submit").status_code == 200


def test_posting_reversal_and_the_database(books: dict[str, Any]) -> None:
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    switch(books)
    made = purchase(books).json()
    posted = act(books, made["id"], "post")
    assert posted.status_code == 200, posted.content
    # The reversal mirrors the foreign amounts and the rate.
    reversed_ = books["client"].post_json(
        f"{books['base']}/journal-entries/{made['id']}/reverse",
        {"reason": "Wrong supplier", "reversal_date": "2026-03-12"},
    ).json()  # fmt: skip
    mirror = reversed_["lines"][0]
    assert (mirror["credit"], mirror["txn_currency"], mirror["txn_amount"],
            mirror["rate_source"]) == ("92.00", "USD", "100.0000", BANK)  # fmt: skip
    assert act(books, reversed_["id"], "post").status_code == 200
    # Switched off again: posted lines stay; new foreign lines are refused.
    assert switch(books, on=False).status_code == 200
    assert purchase(books).status_code == 422
    set_context(tenant_id=UUID(books["ws"]["id"]))
    stored = JournalLine.objects.filter(entry_id=made["id"])
    assert all(ln.txn_currency == "USD" for ln in stored)
    with pytest.raises(DatabaseError), transaction.atomic():
        JournalLine.objects.filter(entry_id=made["id"]).update(rate_source="")


def test_the_stored_rate_is_only_a_suggestion(books: dict[str, Any]) -> None:
    c, base = books["client"], books["base"]
    url = f"{base}/exchange-rates/suggestion"
    none = c.get(url, query_params={"currency": "USD", "on": "2026-03-10"})
    assert none.status_code == 404
    for day, rate, kind in (("2026-03-09", "1.0870", "SPOT"), ("2026-03-09", "1.0900", "AVERAGE"),
                            ("2026-03-11", "1.0500", "SPOT")):  # fmt: skip
        made = c.post_json(f"{base}/exchange-rates", {
            "rate_date": day, "base_currency": "EUR", "quote_currency": "USD", "rate": rate,
            "rate_type": kind, "source": f"ECB reference rate {kind} (Demo)"})  # fmt: skip
        assert made.status_code == 201, made.content
    found = c.get(url, query_params={"currency": "USD", "on": "2026-03-10"}).json()
    # The latest on or before the date, spot first; inverted to euros per dollar.
    assert (found["rate"], found["rate_date"], found["rate_type"]) == (
        "0.9199632015",
        "2026-03-09",
        "SPOT",
    )
    c.post_json(f"{base}/exchange-rates", {
        "rate_date": "2026-03-10", "base_currency": "GBP", "quote_currency": "EUR",
        "rate": "1.1712", "rate_type": "SPOT", "source": "ECB (Demo)"})  # fmt: skip
    pounds = c.get(url, query_params={"currency": "GBP", "on": "2026-03-10"}).json()
    assert pounds["rate"] == "1.1712000000"
