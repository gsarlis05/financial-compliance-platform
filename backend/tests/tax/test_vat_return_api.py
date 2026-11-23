"""The 13-box return through the ledger and the API (V1-2c, #214): real entries with the V1-2b
codes, parties and line VAT details; the boxes in the report, the screen's data and both exports.

Q1 2026, quarterly:
  15 Jan  EU service from a French supplier, net 100, RCEU19, half recoverable
  20 Feb  goods from a German supplier, net 1,000, EUGA19
  10 Mar  local sale, net 1,000, S19, tax point 2 April (outside the period: flagged)
Boxes: 1 = 19 + 190 = 209; 2 = 190; 3 = 399; 4 = 9.50 + 190 = 199.50; 5 = 199.50;
       6 = 100 + 1,000 = 1,100; 7 = 100 + 1,000 = 1,100; 11A = 1,000; 11B = 100.
"""

import io
from typing import Any
from uuid import UUID

import pytest
from openpyxl import load_workbook

from fcp.core.db.rls import set_context
from fcp.modules.tax.exports import return_rows
from fcp.modules.tax.models import VatReport

from ..ledger.conftest import books

pytestmark = pytest.mark.django_db
__all__ = ["books"]

RCEU19, EUGA19, S19 = "CY:RCEU19:open", "CY:EUGA19:open", "CY:S19:open"


def party(v: dict[str, Any], code: str, country: str, vat_no: str) -> str:
    made = v["client"].post_json(f"{v['base']}/counterparties", {
        "code": code, "name": f"Supplier {code} (Demo)", "kind": "SUPPLIER", "country": country,
        "vat_no": vat_no})  # fmt: skip
    assert made.status_code == 201, made.content
    return str(made.json()["id"])


def post(v: dict[str, Any], day: str, *lines: dict[str, Any]) -> None:
    acc = v["accounts"]
    rows = [{**ln, "account_id": acc[ln["account_id"]]["id"]} for ln in lines]
    body = {"accounting_date": day, "description": f"VAT return fixture {day}", "lines": rows}
    made = v["client"].post_json(f"{v['base']}/journal-entries", body)
    assert made.status_code == 201, made.content
    posted = v["client"].post_json(f"{v['base']}/journal-entries/{made.json()['id']}/post", {})
    assert posted.status_code == 200, posted.content


def line(account: str, dr: str, cr: str, code: str | None = None, **extra: Any) -> dict[str, Any]:
    return {"account_id": account, "debit": dr, "credit": cr,
            **({"vat_code_id": code} if code else {}), **extra}  # fmt: skip


@pytest.fixture
def v(books: dict[str, Any]) -> dict[str, Any]:
    c, base = books["client"], books["base"]
    assert c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"}).status_code == 200
    fr = party(books, "FR1", "FR", "FR12345678901")
    de = party(books, "DE1", "DE", "DE123456789")
    post(books, "2026-01-15",
         line("6100", "100", "0", RCEU19),
         line("2120", "0", "19", RCEU19),
         line("1220", "9.50", "0", RCEU19, vat_recovery_percent="50", vat_blocked="9.50"),
         line("6100", "9.50", "0"),  # the non-recoverable half is a cost
         line("2100", "0", "100", counterparty_id=fr, reference="FR-77"))  # fmt: skip
    post(books, "2026-02-20",
         line("5000", "1000", "0", EUGA19),
         line("2120", "0", "190", EUGA19),
         line("1220", "190", "0", EUGA19),
         line("2100", "0", "1000", counterparty_id=de, reference="DE-12"))  # fmt: skip
    post(books, "2026-03-10",
         line("1300", "1190", "0"),
         line("4000", "0", "1000", S19, tax_point="2026-04-02"),
         line("2120", "0", "190", S19, tax_point="2026-04-02"))  # fmt: skip
    made = c.post_json(f"{base}/vat-period-schemes", {"months": 3, "effective_from": "2026-01-01"})
    assert made.status_code == 201, made.content
    return books


def test_the_return_from_real_entries(v: dict[str, Any]) -> None:
    made = v["client"].post_json(f"{v['base']}/vat-reports", {"period_start": "2026-01-01"})
    assert made.status_code == 201, made.content
    report = made.json()
    snap = report["snapshot"]
    boxes = {b["box"]: b["amount"] for b in snap["return"]["boxes"]}
    assert {k: boxes[k] for k in ("1", "2", "3", "4", "5")} == {
        "1": "209.00", "2": "190.00", "3": "399.00", "4": "199.50", "5": "199.50"}  # fmt: skip
    assert {k: boxes[k] for k in ("6", "7", "11A", "11B", "8A", "8B", "9", "10")} == {
        "6": "1100.00", "7": "1100.00", "11A": "1000.00", "11B": "100.00",
        "8A": "0.00", "8B": "0.00", "9": "0.00", "10": "0.00"}  # fmt: skip
    # The parties' data reaches the lines from the payable line of each entry.
    service = next(
        ln for ln in snap["lines"] if ln["code"] == "RCEU19" and ln["kind"] == "PURCHASE"
    )
    assert (service["country"], service["vat_no"], service["reference"]) == (
        "FR",
        "FR12345678901",
        "FR-77",
    )
    assert service["boxes"] == {"6": "100.00", "7": "100.00", "11B": "100.00"}
    recovered = next(ln for ln in snap["lines"] if ln["kind"] == "PURCHASE_VAT"
                     and ln["code"] == "RCEU19")  # fmt: skip
    assert (recovered["recovery_percent"], recovered["blocked"], recovered["boxes"]) == (
        "50.00",
        "9.50",
        {"4": "9.50"},
    )
    # The only exceptions: the sale's tax point is in the next quarter (both of its lines).
    assert [(e["kind"], e["entry"]) for e in snap["exceptions"]] == [
        ("TAX_POINT_OUTSIDE_PERIOD", "GJ-3"), ("TAX_POINT_OUTSIDE_PERIOD", "GJ-3")]  # fmt: skip

    # Both exports carry the return as the screen shows it.
    url = f"{v['base']}/vat-reports/{report['id']}/export"
    book = load_workbook(io.BytesIO(v["client"].get(f"{url}?format=xlsx").content))
    summary = [list(r) for r in book["VAT"].iter_rows(values_only=True)]
    printed = {str(r[0]): r[2] for r in summary if r[0] in boxes and len(r) > 2}
    assert {k: f"{printed[k]:.2f}" for k in boxes} == boxes
    assert any("CY-VAT-BOXES@1: not yet verified" in str(r[0]) for r in summary)
    header = [c.value for c in book["Lines"][1]]
    assert header[7:9] == ["Boxes", "Rule"]
    pdf = v["client"].get(f"{url}?format=pdf")
    assert pdf.status_code == 200
    set_context(tenant_id=UUID(v["ws"]["id"]))
    rows = return_rows(VatReport.objects.get(id=report["id"]), "en")
    assert rows[0] == ["Box", "Item", "Amount", "Rounding"]
    assert [r[0] for r in rows[1:]] == ["1", "2", "3", "4", "5", "6", "7", "8A", "8B", "9", "10",
                                        "11A", "11B"]  # fmt: skip
    assert (rows[1][2], rows[6][2]) == ("209.00", "1,100")
    assert return_rows(VatReport.objects.get(id=report["id"]), "el")[6][2] == "1.100"
