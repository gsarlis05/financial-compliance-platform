"""VAT codes on journal lines (M2-3, AC-M2-3)."""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.conf import settings
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.ledger.models import VatCode

from .test_entries import act, reviewer

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["reviewer"]
S19 = "CY:S19:open"


def vat_sale(books: dict[str, Any], day: str = "2026-03-15", code: str | None = S19) -> Any:
    acc = books["accounts"]
    vat_line: dict[str, Any] = {"account_id": acc["2120"]["id"], "credit": "19.00"}
    if code:
        vat_line["vat_code_id"] = code
    return books["client"].post_json(f"{books['base']}/journal-entries", {
        "accounting_date": day, "description": "Cash sale",
        "lines": [{"account_id": acc["1300"]["id"], "debit": "119.00"},
                  {"account_id": acc["4000"]["id"], "credit": "100.00", "vat_code_id": code},
                  vat_line]})  # fmt: skip


@pytest.fixture
def window_code() -> str:
    """A test-only CY code valid in January 2026 (the catalogue is versioned by date)."""
    VatCode.objects.create(
        id="CY:TST:2026-01-01", jurisdiction="CY", code="TST", name="Test rate",
        treatment="STANDARD", rate="0.19", valid_from=date(2026, 1, 1),
        valid_to=date(2026, 1, 31),
    )  # fmt: skip
    return "CY:TST:2026-01-01"


def test_catalogue_lists_codes_flagged_unverified(books: dict[str, Any]) -> None:
    codes = books["client"].get(f"{books['base']}/vat-codes").json()
    assert {c["code"] for c in codes} == {"S19", "R9", "R5", "Z0", "EX", "RC", "OUT", "SETTLE"}
    assert all(c["verified"] is False for c in codes)
    assert "tax professional" in codes[0]["verification_note"]
    s19 = next(c for c in codes if c["code"] == "S19")
    assert s19["rate"] == "0.1900"


def test_catalogue_filters_by_date(books: dict[str, Any], window_code: str) -> None:
    url = f"{books['base']}/vat-codes"
    assert "TST" in {c["code"] for c in books["client"].get(f"{url}?on=2026-01-15").json()}
    assert "TST" not in {c["code"] for c in books["client"].get(f"{url}?on=2026-02-15").json()}


def test_runtime_role_can_only_read_the_catalogue() -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE table_name = 'ledger_vat_code' AND grantee = %s",
            [settings.DB_APP_ROLE_NAME],
        )
        privileges = {row[0] for row in cursor.fetchall()}
    assert privileges == {"SELECT"}


def test_template_marks_vat_accounts_and_role_rules(books: dict[str, Any]) -> None:
    acc = books["accounts"]
    assert acc["1220"]["vat_role"] == "INPUT"
    assert acc["2120"]["vat_role"] == "OUTPUT"
    csrf = {"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value}

    def patch(code: str, role: str) -> Any:
        return books["client"].patch(f"{books['base']}/accounts/{acc[code]['id']}",
                                     {"vat_role": role}, content_type="application/json",
                                     headers=csrf)  # fmt: skip

    assert patch("2110", "INPUT").status_code == 422  # a liability cannot hold input VAT
    assert patch("2110", "OUTPUT").status_code == 200
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    draft = vat_sale(books).json()
    assert act(books, draft["id"], "post").status_code == 200
    assert patch("2120", "").status_code == 409  # frozen once posted


def test_vat_account_lines_need_a_code(books: dict[str, Any]) -> None:
    draft = vat_sale(books, code=None).json()
    refused = act(books, draft["id"], "submit")
    assert refused.status_code == 422
    assert refused.json()["code"] == "ledger.line.vat_code_required"
    assert refused.json()["errors"]["lines.2.vat_code_id"] == ["required"]


def test_unknown_or_foreign_codes_are_rejected(books: dict[str, Any]) -> None:
    VatCode.objects.create(id="GR:S24:open", jurisdiction="GR", code="S24", name="Greek rate",
                           treatment="STANDARD", rate="0.24")  # fmt: skip
    for code in ("CY:NOPE:open", "GR:S24:open"):
        response = vat_sale(books, code=code)
        assert response.status_code == 422
        assert response.json()["code"] == "ledger.line.vat_code_invalid"


def test_code_outside_its_validity_window_is_rejected(
    books: dict[str, Any], window_code: str, reviewer: Any
) -> None:
    late = vat_sale(books, day="2026-03-15", code=window_code).json()
    refused = act(books, late["id"], "submit")
    assert refused.status_code == 422
    assert "not valid on 2026-03-15" in refused.json()["detail"]
    inside = vat_sale(books, day="2026-01-15", code=window_code).json()
    for action, client in (("submit", None), ("approve", reviewer), ("post", reviewer)):
        assert act(books, inside["id"], action, client).status_code == 200


def test_reversal_of_an_entry_with_an_expired_code_is_allowed(
    books: dict[str, Any], window_code: str, reviewer: Any
) -> None:
    original = vat_sale(books, day="2026-01-15", code=window_code).json()
    for action, client in (("submit", None), ("approve", reviewer), ("post", reviewer)):
        assert act(books, original["id"], action, client).status_code == 200
    reversal = (
        books["client"]
        .post_json(
            f"{books['base']}/journal-entries/{original['id']}/reverse",
            {"reason": "Wrong customer", "reversal_date": "2026-03-20"},
        )
        .json()
    )
    assert reversal["lines"][2]["vat_code"] == "TST"
    for action, client in (("submit", None), ("approve", reviewer), ("post", reviewer)):
        response = act(books, reversal["id"], action, client)
        assert response.status_code == 200, response.content


def test_vat_code_is_part_of_the_approved_content(books: dict[str, Any]) -> None:
    standard = vat_sale(books).json()
    zero = vat_sale(books, code="CY:Z0:open").json()
    act(books, standard["id"], "submit")
    act(books, zero["id"], "submit")
    hashes = {e["id"]: e["content_hash"]
              for e in books["client"].get(f"{books['base']}/journal-entries").json()}  # fmt: skip
    assert hashes[standard["id"]] != hashes[zero["id"]]


def _post_bypassing_the_application(books: dict[str, Any], entry_id: str) -> None:
    with transaction.atomic():
        set_context(tenant_id=books["ws"]["id"])
        period = next(p["id"] for p in books["fy"]["periods"] if p["number"] == 3)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "UPDATE ledger_journal_entry SET status='POSTED', entry_no=990, posting_seq=990, "
                "period_id=%s, posted_at=now() WHERE id=%s",
                [period, entry_id],
            )


def test_database_rejects_vat_lines_without_code(books: dict[str, Any]) -> None:
    draft = vat_sale(books, code=None).json()
    with pytest.raises(DatabaseError, match="without a VAT code"):
        _post_bypassing_the_application(books, draft["id"])


def test_database_rejects_an_expired_code(books: dict[str, Any], window_code: str) -> None:
    draft = vat_sale(books, day="2026-03-15", code=window_code).json()
    with pytest.raises(DatabaseError, match="not valid for its date"):
        _post_bypassing_the_application(books, draft["id"])
