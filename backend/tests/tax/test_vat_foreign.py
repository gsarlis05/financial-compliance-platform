"""Foreign currency in the VAT report (V1-2h, #219): the return is in euros; each line keeps its
original amount, currency, rate, the rate's date and time and its source, and the report states
the conversion policy (owner's decision, 2026-11-23)."""

import csv
import io
from typing import Any

import pytest

from ..ledger.conftest import books
from ..ledger.test_foreign_currency import AT, BANK, switch

pytestmark = pytest.mark.django_db
__all__ = ["books"]
S19 = "CY:S19:open"


def fx(amount: str) -> dict[str, Any]:
    return {"txn_currency": "USD", "txn_amount": amount, "exchange_rate": "0.92", "rate_at": AT,
            "rate_source": BANK}  # fmt: skip


def test_a_dollar_purchase_in_the_return(books: dict[str, Any]) -> None:
    c, base, acc = books["client"], books["base"], books["accounts"]
    assert c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"}).status_code == 200
    switch(books)
    supplier = c.post_json(f"{base}/counterparties", {
        "code": "US1", "name": "Supplier US (Demo)", "kind": "SUPPLIER",
        "country": "US"}).json()["id"]  # fmt: skip
    made = c.post_json(f"{base}/journal-entries", {
        "accounting_date": "2026-02-10", "description": "Laptop from a US shop", "lines": [
            {"account_id": acc["6100"]["id"], "debit": "92.00", "vat_code_id": S19, **fx("100")},
            {"account_id": acc["1220"]["id"], "debit": "17.48", "vat_code_id": S19, **fx("19")},
            {"account_id": acc["2100"]["id"], "credit": "109.48", "counterparty_id": supplier,
             "reference": "US-55", **fx("119")}]})  # fmt: skip
    assert made.status_code == 201, made.content
    assert c.post_json(f"{base}/journal-entries/{made.json()['id']}/post", {}).status_code == 200
    c.post_json(f"{base}/vat-period-schemes", {"months": 3, "effective_from": "2026-01-01"})
    report = c.post_json(f"{base}/vat-reports", {"period_start": "2026-01-01"}).json()
    snap = report["snapshot"]
    assert "exchange rate of the transaction's date and time" in snap["currency_policy"]
    boxes = {b["box"]: b["amount"] for b in snap["return"]["boxes"]}
    assert (boxes["4"], boxes["7"]) == ("17.48", "92.00")  # in euros
    vat = next(ln for ln in snap["lines"] if ln["kind"] == "PURCHASE_VAT")
    assert (vat["amount"], vat["txn_currency"], vat["txn_amount"], vat["exchange_rate"],
            vat["rate_source"]) == ("17.48", "USD", "19.00", "0.9200000000", BANK)  # fmt: skip
    assert vat["rate_at"].startswith("2026-03-10T12:32:00")
    exported = c.get(f"{base}/vat-reports/{report['id']}/export?format=csv")
    rows = list(csv.DictReader(io.StringIO(exported.content.decode("utf-8"))))
    line = next(r for r in rows if r["kind"] == "PURCHASE")
    assert (line["amount"], line["txn_currency"], line["txn_amount"], line["rate_source"]) == (
        "92.00",
        "USD",
        "100.00",
        BANK,
    )
