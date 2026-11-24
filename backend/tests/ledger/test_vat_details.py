"""VAT details on journal lines (V1-2b, #213): tax point, deductible share and blocked VAT on
input VAT lines, kept through reversals and given to the VAT return; a supplier's country."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from fcp.modules.ledger.api import vat_lines
from fcp.modules.tenancy.services import enter_workspace

from .test_entries import act, reviewer

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
RCEU = "CY:RCEU19:open"
__all__ = ["reviewer"]


def entry(books: dict[str, Any], *lines: dict[str, Any], day: str = "2026-03-15") -> Any:
    acc = books["accounts"]
    body = [{**ln, "account_id": acc[ln.pop("account")]["id"]} for ln in lines]
    return books["client"].post_json(f"{books['base']}/journal-entries",
                                     {"accounting_date": day, "description": "VAT details",
                                      "lines": body})  # fmt: skip


def eu_service(books: dict[str, Any], **extra: Any) -> Any:
    """An EU service of 100 with 19 self-accounted VAT, half deductible (brief 25 §5)."""
    return entry(
        books,
        {"account": "6200", "debit": "109.50", "vat_code_id": RCEU, "tax_point": "2026-03-10"},
        {"account": "1220", "debit": "9.50", "vat_code_id": RCEU, "vat_recovery_percent": "50",
         "vat_blocked": "9.50", **extra},
        {"account": "2120", "credit": "19.00", "vat_code_id": RCEU},
        {"account": "1300", "credit": "100.00"},
    )  # fmt: skip


def test_details_are_kept_hashed_and_reversed(books: dict[str, Any], reviewer: Any) -> None:
    made = eu_service(books)
    assert made.status_code == 201, made.content
    lines = {ln["line_no"]: ln for ln in made.json()["lines"]}
    assert (lines[2]["vat_recovery_percent"], lines[2]["vat_blocked"]) == ("50.00", "9.50")
    assert lines[1]["tax_point"] == "2026-03-10"
    act(books, made.json()["id"], "submit")
    act(books, made.json()["id"], "approve", reviewer)
    assert act(books, made.json()["id"], "post", reviewer).json()["status"] == "POSTED"
    ctx = enter_workspace(books["owner"], books["ws"]["slug"])
    found = vat_lines(ctx, UUID(books["entity"]["id"]), date_from=date(2026, 3, 1),
                      date_to=date(2026, 3, 31))  # fmt: skip
    vat_input = next(v for v in found if v.account_code == "1220")
    assert (vat_input.category, vat_input.vat_recovery_percent, vat_input.vat_blocked) == (
        "RC_EU_SERVICES",
        Decimal(50),
        Decimal("9.5"),
    )
    rev = books["client"].post_json(
        f"{books['base']}/journal-entries/{made.json()['id']}/reverse", {"reason": "Wrong supplier"}
    )
    assert rev.status_code == 201, rev.content
    mirrored = {ln["line_no"]: ln for ln in rev.json()["lines"]}
    assert (mirrored[2]["credit"], mirrored[2]["vat_recovery_percent"],
            mirrored[2]["vat_blocked"], mirrored[1]["tax_point"]) == (
        "9.50", "50.00", "9.50", "2026-03-10")  # fmt: skip


def test_details_are_checked(books: dict[str, Any]) -> None:
    wrong_share = eu_service(books, vat_recovery_percent="40")
    assert wrong_share.status_code == 422
    assert "do not make 40% deductible" in wrong_share.json()["detail"]
    on_output = entry(books, {"account": "1300", "debit": "119.00"},
                      {"account": "4000", "credit": "100.00", "vat_code_id": "CY:S19:open"},
                      {"account": "2120", "credit": "19.00", "vat_code_id": "CY:S19:open",
                       "vat_recovery_percent": "100"})  # fmt: skip
    assert on_output.status_code == 422
    assert "belongs on an input VAT line" in on_output.json()["detail"]
    no_code = entry(books, {"account": "6100", "debit": "50.00", "tax_point": "2026-03-01"},
                    {"account": "1300", "credit": "50.00"})  # fmt: skip
    assert no_code.status_code == 422
    assert "a tax point needs a VAT code" in no_code.json()["detail"]
    assert eu_service(books, vat_recovery_percent="120").status_code == 422
    assert eu_service(books, vat_blocked="-1").status_code == 422


def test_a_supplier_has_a_country(books: dict[str, Any]) -> None:
    url = f"{books['base']}/counterparties"
    made = books["client"].post_json(url, {"code": "S-DE", "name": "Lieferant GmbH (Demo)",
                                           "kind": "SUPPLIER", "vat_no": "de123456789",
                                           "country": "DE"})  # fmt: skip
    assert made.status_code == 201, made.content
    assert (made.json()["country"], made.json()["vat_no"]) == ("DE", "DE123456789")
    assert books["client"].post_json(url, {"code": "S-X", "name": "X", "kind": "SUPPLIER",
                                           "country": "Germany"}).status_code == 422  # fmt: skip
    changed = books["client"].patch_json(f"{url}/{made.json()['id']}", {"country": "AT"})
    assert changed.json()["country"] == "AT"
