"""VIES statements (V1-2g, #218): recorded by the owner as filed (never submitted), reconciled to
the EU supplies in the books and to Boxes 8A and 8B, with missing months, partners on one side
only, rounding, corrections and triangular amounts kept apart.

Q1 2026, quarterly:
  15 Jan  goods to a German business, 1,000 (EUGS)          -> Box 8A
  10 Feb  services to a French business, 300 (EUSS)         -> Box 8B
"""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.tax.models import VatViesLine, VatViesStatement
from fcp.modules.tax.report import vat_key

from ..ledger.conftest import books

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


def party(b: dict[str, Any], code: str, country: str, vat_no: str) -> str:
    made = b["client"].post_json(f"{b['base']}/counterparties", {
        "code": code, "name": f"Customer {code} (Demo)", "kind": "CUSTOMER", "country": country,
        "vat_no": vat_no})  # fmt: skip
    assert made.status_code == 201, made.content
    return str(made.json()["id"])


def sale(b: dict[str, Any], day: str, customer: str, amount: str, code: str) -> None:
    acc = b["accounts"]
    body = {"accounting_date": day, "description": f"EU sale {day}", "lines": [
        {"account_id": acc["1200"]["id"], "debit": amount, "credit": "0",
         "counterparty_id": customer, "reference": f"INV-{day}"},
        {"account_id": acc["4000"]["id"], "debit": "0", "credit": amount,
         "vat_code_id": f"CY:{code}:open"}]}  # fmt: skip
    made = b["client"].post_json(f"{b['base']}/journal-entries", body)
    assert made.status_code == 201, made.content
    posted = b["client"].post_json(f"{b['base']}/journal-entries/{made.json()['id']}/post", {})
    assert posted.status_code == 200, posted.content


@pytest.fixture
def eu(books: dict[str, Any]) -> dict[str, Any]:
    c, base = books["client"], books["base"]
    assert c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"}).status_code == 200
    sale(books, "2026-01-15", party(books, "DE1", "DE", "DE 123 456 789"), "1000.00", "EUGS")
    sale(books, "2026-02-10", party(books, "FR1", "FR", "FR12345678901"), "300.00", "EUSS")
    made = c.post_json(f"{base}/vat-period-schemes", {"months": 3, "effective_from": "2026-01-01"})
    assert made.status_code == 201, made.content
    books["report"] = c.post_json(f"{base}/vat-reports", {"period_start": "2026-01-01"}).json()
    return books


def file(b: dict[str, Any], month: str, *lines: dict[str, Any], kind: str = "ORIGINAL",
         filed_on: str = "2026-04-10", reference: str = "VIES-1") -> Any:  # fmt: skip
    return b["client"].post_json(f"{b['base']}/vat-vies", {
        "month": month, "kind": kind, "filed_on": filed_on, "reference": reference,
        "lines": list(lines)})  # fmt: skip


def vies(b: dict[str, Any]) -> dict[str, Any]:
    found = b["client"].get(f"{b['base']}/vat-reports/{b['report']['id']}").json()["vies"]
    return dict(found)


def test_partner_keys() -> None:
    assert vat_key("DE", "DE 123 456 789") == ("DE", "123456789")
    assert vat_key("GR", "EL-094000000") == ("GR", "094000000")
    assert vat_key("FR", "12345678901") == ("FR", "12345678901")


def test_reconciliation_to_8a_and_8b(eu: dict[str, Any]) -> None:
    # Nothing recorded yet: both months with EU supplies are missing, both partners not filed.
    start = vies(eu)
    assert start["missing_months"] == ["2026-01-01", "2026-02-01"]
    assert sorted(p["status"] for p in start["partners"]) == ["NOT_FILED", "NOT_FILED"]
    assert start["agrees"] is False

    # Validation, then January as filed.
    assert file(eu, "2026-01-15", {"country": "DE", "vat_no": "123456789",
                                   "goods": "1000"}).status_code == 422  # fmt: skip
    assert file(eu, "2026-01-01", {"country": "DE", "vat_no": "1"},
                ).status_code == 422  # no amount  # fmt: skip
    assert file(eu, "2026-01-01", {"country": "DE", "vat_no": "123456789", "goods": "1"},
                {"country": "DE", "vat_no": "DE123456789", "goods": "1"},
                ).status_code == 422  # the same partner twice  # fmt: skip
    january = file(eu, "2026-01-01", {"country": "DE", "vat_no": "123456789", "goods": "1000"})
    assert january.status_code == 201, january.content
    assert file(eu, "2026-01-01", {"country": "DE", "vat_no": "123456789", "goods": "1000"},
                ).status_code == 409  # one original per month  # fmt: skip

    # February with a 40-cent difference on the French services, and a triangular line.
    file(eu, "2026-02-01", {"country": "FR", "vat_no": "FR12345678901", "services": "300.40"},
         {"country": "IT", "vat_no": "IT01234567890", "triangular": "500"},
         reference="VIES-2")  # fmt: skip
    found = vies(eu)
    assert found["missing_months"] == []
    by_country = {p["country"]: p for p in found["partners"]}
    assert by_country["DE"]["status"] == "MATCH"
    assert (by_country["FR"]["status"], by_country["FR"]["difference_services"]) == (
        "ROUNDING", "0.40")
    assert by_country["IT"]["status"] == "TRIANGULAR"
    assert found["triangular"] == "500.00"
    totals = {t["box"]: t for t in found["totals"]}
    assert (totals["8A"]["vies"], totals["8A"]["box_exact"], totals["8A"]["difference"]) == (
        "1000.00", "1000.00", "0.00")
    assert (totals["8B"]["vies"], totals["8B"]["box_exact"], totals["8B"]["difference"]) == (
        "300.40", "300.00", "0.40")
    assert found["agrees"] is False  # the rounding is shown, not hidden

    # A correction for February replaces the original: everything agrees.
    corrected = file(eu, "2026-02-01",
                     {"country": "FR", "vat_no": "12345678901", "services": "300"},
                     {"country": "IT", "vat_no": "IT01234567890", "triangular": "500"},
                     kind="CORRECTION", filed_on="2026-04-20", reference="VIES-2C")  # fmt: skip
    assert corrected.status_code == 201, corrected.content
    final = vies(eu)
    assert final["agrees"] is True
    assert [(m["month"], m["kind"]) for m in final["months"]] == [
        ("2026-01-01", "ORIGINAL"), ("2026-02-01", "CORRECTION"), ("2026-03-01", "")]
    listed = eu["client"].get(f"{eu['base']}/vat-vies", query_params={
        "date_from": "2026-01-01", "date_to": "2026-03-31"}).json()  # fmt: skip
    assert [s["reference"] for s in listed] == ["VIES-1", "VIES-2", "VIES-2C"]


def test_statements_are_kept(eu: dict[str, Any]) -> None:
    made = file(eu, "2026-01-01", {"country": "DE", "vat_no": "123456789", "goods": "1000"}).json()
    url = f"{eu['base']}/vat-vies/{made['id']}/void"
    assert eu["client"].post_json(url, {"reason": " "}).status_code == 422
    assert eu["client"].post_json(url, {"reason": "Wrong month"}).status_code == 200
    assert eu["client"].post_json(url, {"reason": "Again"}).status_code == 409
    assert vies(eu)["missing_months"] == ["2026-01-01", "2026-02-01"]  # a void one counts not
    set_context(tenant_id=UUID(eu["ws"]["id"]))
    rows = VatViesStatement.objects.filter(id=made["id"])
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        rows.update(reference="EDITED")
    with pytest.raises(DatabaseError, match="are kept"), transaction.atomic():
        rows.delete()
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        VatViesLine.objects.filter(statement_id=made["id"]).update(goods=Decimal(1))
    with pytest.raises(DatabaseError, match="active VIES statement"), transaction.atomic():
        VatViesLine.objects.create(tenant_id=UUID(eu["ws"]["id"]), statement_id=made["id"],
                                   country="DE", vat_no="999", goods=Decimal(1))  # fmt: skip
