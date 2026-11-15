"""Currency foundation (M6F-1, #80; owner decision D8): ISO 4217 everywhere, the transaction /
functional / reporting split ready in the database, exchange rates as sourced data, and
multi-currency transactions refused until their full accounting treatment exists."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.core.money.currency import get_currency
from fcp.modules.ledger.models import Account, ExchangeRate, JournalEntry, JournalLine
from fcp.modules.tenancy.models import LegalEntity

from .conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


def entry(b: dict[str, Any], **extra: Any) -> Any:
    acc = b["accounts"]
    return b["client"].post_json(f"{b['base']}/journal-entries", {
        "accounting_date": "2026-03-01", "description": "Cash sale", **extra,
        "lines": [{"account_id": acc["1300"]["id"], "debit": "100.00"},
                  {"account_id": acc["4000"]["id"], "credit": "100.00"}]})  # fmt: skip


def test_reference_table_matches_the_money_module() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT code, minor_units FROM core_currency ORDER BY code")
        rows = cursor.fetchall()
    assert len(rows) == 19
    for code, minor_units in rows:
        assert get_currency(code.strip()).minor_units == minor_units


def test_entity_currencies_and_the_disabled_switch(books: dict[str, Any]) -> None:
    entity = books["client"].get(books["base"]).json()
    assert (entity["functional_currency"], entity["reporting_currency"]) == ("EUR", "EUR")
    assert entity["multi_currency_enabled"] is False
    set_context(tenant_id=UUID(books["ws"]["id"]))
    rows = LegalEntity.objects.filter(id=entity["id"])
    with pytest.raises(DatabaseError, match="not a supported ISO 4217"), transaction.atomic():
        rows.update(functional_currency="XYZ")
    with pytest.raises(DatabaseError, match="not a supported ISO 4217"), transaction.atomic():
        rows.update(reporting_currency="eur")
    with pytest.raises(DatabaseError, match="multi_currency_off"), transaction.atomic():
        rows.update(multi_currency_enabled=True)
    accounts = Account.objects.filter(id=books["accounts"]["1300"]["id"])
    with pytest.raises(DatabaseError, match="not a supported ISO 4217"), transaction.atomic():
        accounts.update(currency="ABC")
    accounts.update(currency="")  # blank: the account accepts any currency
    accounts.update(currency="EUR")


def test_foreign_currency_entries_are_refused(books: dict[str, Any]) -> None:
    refused = entry(books, currency="USD")
    assert refused.status_code == 422, refused.content
    assert refused.json()["errors"]["currency"] == [
        "Transactions in USD are not available yet: this entity records EUR only "
        "(multi-currency is disabled in this release)."
    ]
    assert entry(books, currency="EUR").status_code == 201
    made = entry(books)
    assert made.status_code == 201
    assert made.json()["currency"] == "EUR"
    # The database refuses the same, whatever the application does.
    set_context(tenant_id=UUID(books["ws"]["id"]))
    with pytest.raises(DatabaseError, match="functional currency"), transaction.atomic():
        JournalEntry.objects.filter(id=made.json()["id"]).update(currency="USD")
    lines = JournalLine.objects.filter(entry_id=made.json()["id"], debit__gt=0)
    with pytest.raises(DatabaseError, match="multi-currency transactions are disabled"), \
            transaction.atomic():  # fmt: skip
        lines.update(txn_currency="USD", txn_debit=110, txn_credit=0, exchange_rate="0.909")
    with pytest.raises(DatabaseError, match="txn_currency_shape"), transaction.atomic():
        lines.update(exchange_rate="1")  # a rate without the transaction amounts


def test_exchange_rates_are_sourced_data(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    c, url = books["client"], f"{books['base']}/exchange-rates"
    body = {"rate_date": "2026-03-31", "base_currency": "EUR", "quote_currency": "USD",
            "rate": "1.0812", "rate_type": "CLOSING", "source": "ECB reference rate (Demo)",
            "source_hash": "ab" * 32}  # fmt: skip
    made = c.post_json(url, body)
    assert made.status_code == 201, made.content
    assert (made.json()["rate"], made.json()["rate_type"]) == ("1.0812", "CLOSING")
    assert c.post_json(url, body).status_code == 409  # once per date, pair, type and source
    for bad, field in (({"base_currency": "XYZ"}, "base_currency"),
                       ({"quote_currency": "EUR"}, "quote_currency"),
                       ({"rate": "0"}, "rate"), ({"source": " "}, "source")):  # fmt: skip
        refused = c.post_json(url, {**body, **bad})
        assert refused.status_code == 422, (bad, refused.content)
        assert field in refused.json()["errors"], refused.json()
    assert [r["rate"] for r in c.get(url).json()] == ["1.0812"]
    viewer = join(c, books["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(url).status_code == 200
    assert viewer.post_json(url, {**body, "source": "other"}).status_code == 403
    # Never changed or deleted (database).
    set_context(tenant_id=UUID(books["ws"]["id"]))
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        ExchangeRate.objects.filter(id=made.json()["id"]).update(rate="2")
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        ExchangeRate.objects.filter(id=made.json()["id"]).delete()
