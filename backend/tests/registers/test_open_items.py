"""Customers, suppliers, open items, allocations and ageing (M2-2, AC-M2-2)."""

import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.registers.models import Allocation

from ..ledger.conftest import books, join
from ..ledger.test_entries import act

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def ar(books: dict[str, Any]) -> dict[str, Any]:
    """Books with no approval step (entries post directly) and two customers and a supplier."""
    client = books["client"]
    assert client.put_json(f"{books['base']}/ledger-settings",
                           {"approval_policy": "NONE"}).status_code == 200  # fmt: skip
    parties = {}
    for code, kind, terms in (("C1", "CUSTOMER", 30), ("C2", "CUSTOMER", 14),
                              ("S1", "SUPPLIER", 45)):  # fmt: skip
        made = client.post_json(
            f"{books['base']}/counterparties",
            {"code": code, "name": f"{code} Ltd (Demo)", "kind": kind,
             "payment_terms_days": terms, "email": f"{code.lower()}@example.test"},
        )  # fmt: skip
        assert made.status_code == 201, made.content
        parties[code] = made.json()["id"]
    return {**books, "parties": parties}


def post(ar: dict[str, Any], day: str, lines: list[dict[str, Any]], desc: str = "Entry") -> Any:
    acc = ar["accounts"]
    body = {
        "accounting_date": day,
        "description": desc,
        "lines": [{**ln, "account_id": acc[ln["account_id"]]["id"]} for ln in lines],
    }
    draft = ar["client"].post_json(f"{ar['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    posted = act(ar, draft.json()["id"], "post")
    assert posted.status_code == 200, posted.content
    return posted.json()


def invoice(ar: dict[str, Any], party: str, day: str, gross: str, ref: str = "",
            due: str | None = None) -> dict[str, Any]:  # fmt: skip
    net = (Decimal(gross) / Decimal("1.19")).quantize(Decimal("0.01"))
    line = {"account_id": "1200", "debit": gross, "counterparty_id": ar["parties"][party],
            "reference": ref, **({"due_date": due} if due else {})}  # fmt: skip
    posted: dict[str, Any] = post(ar, day, [line, {"account_id": "4000", "credit": f"{net:.2f}"},
                          {"account_id": "2120", "credit": f"{Decimal(gross) - net:.2f}"}],
                f"Invoice {ref}")  # fmt: skip
    return posted


def receipt(ar: dict[str, Any], party: str, day: str, amount: str, ref: str = "") -> Any:
    return post(ar, day, [
        {"account_id": "1300", "debit": amount},
        {"account_id": "1200", "credit": amount, "counterparty_id": ar["parties"][party],
         "reference": ref},
    ], f"Receipt {ref}")  # fmt: skip


def items(ar: dict[str, Any], as_of: str, **query: str) -> list[dict[str, Any]]:
    params = "&".join(f"{k}={v}" for k, v in {"as_of": as_of, **query}.items())
    response = ar["client"].get(f"{ar['base']}/open-items?{params}")
    assert response.status_code == 200, response.content
    result: list[dict[str, Any]] = response.json()
    return result


def ageing(ar: dict[str, Any], as_of: str, side: str = "RECEIVABLE") -> dict[str, Any]:
    response = ar["client"].get(f"{ar['base']}/reports/ageing?as_of={as_of}&side={side}")
    assert response.status_code == 200, response.content
    result: dict[str, Any] = response.json()
    return result


def tb_balance(ar: dict[str, Any], code: str, as_of: str) -> Decimal:
    tb = ar["client"].get(f"{ar['base']}/reports/trial-balance?as_of={as_of}").json()
    row = next((r for r in tb["rows"] if r["code"] == code), None)
    return Decimal(row["balance"]) if row else Decimal(0)


# --- counterparty register ----------------------------------------------------------------------


def test_counterparties_are_created_listed_and_personal_data_is_masked_in_audit(
    ar: dict[str, Any],
) -> None:
    listed = ar["client"].get(f"{ar['base']}/counterparties?kind=CUSTOMER").json()
    assert [c["code"] for c in listed] == ["C1", "C2"]
    set_context(tenant_id=ar["ws"]["id"])
    event = AuditEvent.objects.filter(action="registers.counterparty.created").first()
    assert event is not None
    assert "C1 Ltd" not in str(event.changes)
    assert "example.test" not in str(event.changes)


def test_counterparty_validation_and_updates(ar: dict[str, Any]) -> None:
    url = f"{ar['base']}/counterparties"
    duplicate = ar["client"].post_json(url, {"code": "c1", "name": "x", "kind": "CUSTOMER"})
    assert duplicate.status_code == 409
    bad = ar["client"].post_json(url, {"code": "bad code", "name": "x", "kind": "CUSTOMER"})
    assert bad.status_code == 422
    csrf = {"X-CSRFToken": ar["client"].cookies["__Host-fcp_csrftoken"].value}
    patched = ar["client"].patch(
        f"{url}/{ar['parties']['C2']}",
        {"payment_terms_days": 60, "vat_no": "cy99999999l", "status": "INACTIVE"},
        content_type="application/json", headers=csrf,
    )  # fmt: skip
    assert patched.json()["payment_terms_days"] == 60
    assert patched.json()["vat_no"] == "CY99999999L"
    missing = ar["client"].get(f"{url}/{uuid.uuid4()}")
    assert missing.status_code == 404


def test_read_only_users_cannot_change_registers(
    ar: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(ar["client"], ar["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{ar['base']}/counterparties").status_code == 200
    denied = viewer.post_json(
        f"{ar['base']}/counterparties", {"code": "X", "name": "X", "kind": "CUSTOMER"}
    )
    assert denied.status_code == 403


def test_other_workspaces_cannot_see_counterparties(
    ar: dict[str, Any], make_user: Make, make_workspace: Make, api_client: Make
) -> None:
    stranger = make_user("stranger@example.test")
    make_workspace(stranger, name="Elsewhere")
    response = api_client(stranger).get(f"{ar['base']}/counterparties/{ar['parties']['C1']}")
    assert response.status_code == 404


# --- control accounts ---------------------------------------------------------------------------


def test_template_marks_control_accounts_and_type_freezes_after_posting(ar: dict[str, Any]) -> None:
    accounts = {a["code"]: a for a in ar["client"].get(f"{ar['base']}/accounts").json()}
    assert accounts["1200"]["control_type"] == "RECEIVABLE"
    assert accounts["2100"]["control_type"] == "PAYABLE"
    csrf = {"X-CSRFToken": ar["client"].cookies["__Host-fcp_csrftoken"].value}

    def patch(code: str, control: str) -> Any:
        return ar["client"].patch(f"{ar['base']}/accounts/{accounts[code]['id']}",
                                  {"control_type": control}, content_type="application/json",
                                  headers=csrf)  # fmt: skip

    assert patch("1210", "RECEIVABLE").status_code == 200
    assert patch("1210", "PAYABLE").status_code == 422  # an asset cannot be a payables account
    invoice(ar, "C1", "2026-01-10", "119.00")
    frozen = patch("1200", "")
    assert frozen.status_code == 409


def test_control_lines_need_a_counterparty_of_this_entity(
    ar: dict[str, Any], make_user: Make, make_workspace: Make, api_client: Make
) -> None:
    acc = ar["accounts"]
    lines = [{"account_id": acc["1200"]["id"], "debit": "10.00"},
             {"account_id": acc["4000"]["id"], "credit": "10.00"}]  # fmt: skip
    draft = ar["client"].post_json(f"{ar['base']}/journal-entries",
                                   {"accounting_date": "2026-01-10", "description": "x",
                                    "lines": lines}).json()  # fmt: skip
    refused = act(ar, draft["id"], "post")
    assert refused.status_code == 422
    assert refused.json()["code"] == "ledger.line.counterparty_required"
    other = make_user("o@example.test")
    ws = make_workspace(other, name="Other")
    oc = api_client(other)
    oe = oc.get(f"/api/w/{ws['slug']}/entities").json()[0]
    foreign = oc.post_json(f"/api/w/{ws['slug']}/entities/{oe['id']}/counterparties",
                           {"code": "F", "name": "F", "kind": "CUSTOMER"}).json()  # fmt: skip
    lines[0]["counterparty_id"] = foreign["id"]
    response = ar["client"].post_json(f"{ar['base']}/journal-entries",
                                      {"accounting_date": "2026-01-10", "description": "x",
                                       "lines": lines})  # fmt: skip
    assert response.status_code == 422
    assert response.json()["code"] == "ledger.line.counterparty_invalid"


def test_database_rejects_a_control_line_without_counterparty(ar: dict[str, Any]) -> None:
    acc = ar["accounts"]
    draft = ar["client"].post_json(f"{ar['base']}/journal-entries", {
        "accounting_date": "2026-01-10", "description": "x",
        "lines": [{"account_id": acc["1200"]["id"], "debit": "10.00"},
                  {"account_id": acc["4000"]["id"], "credit": "10.00"}]}).json()  # fmt: skip
    period = next(p["id"] for p in ar["fy"]["periods"] if p["number"] == 1)

    def post_bypassing_the_application() -> None:
        with transaction.atomic():
            set_context(tenant_id=ar["ws"]["id"])
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                cursor.execute(
                    "UPDATE ledger_journal_entry SET status='POSTED', entry_no=900, "
                    "posting_seq=900, period_id=%s, posted_at=now() WHERE id=%s",
                    [period, draft["id"]],
                )

    with pytest.raises(DatabaseError, match="without a counterparty"):
        post_bypassing_the_application()


# --- open items, allocation and ageing ----------------------------------------------------------


def test_open_items_allocation_and_ageing_reconcile_to_the_control_account(
    ar: dict[str, Any],
) -> None:
    inv1 = invoice(ar, "C1", "2026-01-10", "1190.00", "INV-1")  # due 2026-02-09 (30 days)
    inv2 = invoice(ar, "C1", "2026-02-01", "500.00", "INV-2", due="2026-02-15")
    invoice(ar, "C2", "2026-03-01", "238.00", "INV-3")  # due 2026-03-15 (14 days)
    receipt(ar, "C1", "2026-03-05", "800.00", "INV-2")

    open_now = items(ar, "2026-03-31", counterparty_id=ar["parties"]["C1"])
    assert sorted((i["kind"], i["open_amount"]) for i in open_now) == [
        ("INVOICE", "1190.00"), ("INVOICE", "500.00"), ("PAYMENT", "800.00")]  # fmt: skip

    auto = ar["client"].post_json(
        f"{ar['base']}/counterparties/{ar['parties']['C1']}/auto-allocate", {"as_of": "2026-03-31"}
    )
    assert auto.status_code == 200
    # Same reference first (INV-2, 500.00), then the oldest invoice (INV-1, 300.00).
    assert sorted(a["amount"] for a in auto.json()) == ["300.00", "500.00"]
    after = {i["reference"]: i for i in items(ar, "2026-03-31", include_settled="true")}
    assert after["INV-2"]["status"] == "SETTLED"
    assert after["INV-1"]["status"] == "PARTIAL"
    assert after["INV-1"]["open_amount"] == "890.00"

    report = ageing(ar, "2026-03-31")
    assert report["reconciles"] is True
    assert Decimal(report["total"]) == tb_balance(ar, "1200", "2026-03-31") == Decimal("1128.00")
    c1 = next(r for r in report["rows"] if r["counterparty_code"] == "C1")
    assert c1["buckets"]["31_60"] == "890.00"  # INV-1 due 2026-02-09: 50 days overdue
    c2 = next(r for r in report["rows"] if r["counterparty_code"] == "C2")
    assert c2["buckets"]["1_30"] == "238.00"  # INV-3 due 2026-03-15: 16 days overdue

    # Before the payment date the allocations do not count yet: ageing is reproducible.
    earlier = ageing(ar, "2026-03-01")
    assert earlier["reconciles"] is True
    c1_then = next(r for r in earlier["rows"] if r["counterparty_code"] == "C1")
    assert c1_then["buckets"]["1_30"] == "1690.00"
    assert inv1["status"] == inv2["status"] == "POSTED"


def test_allocation_rules(ar: dict[str, Any]) -> None:
    invoice(ar, "C1", "2026-01-10", "100.00", "A")
    invoice(ar, "C1", "2026-01-11", "50.00", "B")
    receipt(ar, "C1", "2026-01-20", "120.00")
    receipt(ar, "C2", "2026-01-20", "10.00")
    by_ref = {i["reference"] or i["counterparty_code"] + i["kind"]: i
              for i in items(ar, "2026-12-31")}  # fmt: skip
    url = f"{ar['base']}/allocations"
    c1_pay = next(i for i in items(ar, "2026-12-31", counterparty_id=ar["parties"]["C1"])
                  if i["kind"] == "PAYMENT")  # fmt: skip
    c2_pay = by_ref["C2PAYMENT"]

    def match(inv: dict[str, Any], pay: dict[str, Any], amount: str) -> Any:
        return ar["client"].post_json(url, {"invoice_line_id": inv["line_id"],
                                            "payment_line_id": pay["line_id"],
                                            "amount": amount})  # fmt: skip

    assert match(by_ref["A"], c1_pay, "100.01").status_code == 409  # more than the invoice
    assert match(by_ref["A"], c2_pay, "5.00").status_code == 409  # another customer
    assert match(by_ref["A"], by_ref["B"], "5.00").status_code == 409  # two invoices
    assert match(by_ref["A"], c1_pay, "0.001").status_code == 422
    first = match(by_ref["A"], c1_pay, "100.00")
    assert first.status_code == 201
    assert match(by_ref["B"], c1_pay, "30.00").status_code == 409  # payment has only 20 left
    assert match(by_ref["A"], c1_pay, "1.00").status_code == 409  # already matched pair
    listed = ar["client"].get(f"{ar['base']}/open-items/{by_ref['A']['line_id']}/allocations")
    assert [a["amount"] for a in listed.json()] == ["100.00"]
    removed = ar["client"].delete_json(f"{url}/{first.json()['id']}")
    assert removed.status_code == 204
    assert ar["client"].delete_json(f"{url}/{first.json()['id']}").status_code == 404
    reopened = {i["reference"]: i for i in items(ar, "2026-12-31")}
    assert reopened["A"]["open_amount"] == "100.00"


def test_database_refuses_over_allocation_even_without_the_application(ar: dict[str, Any]) -> None:
    invoice(ar, "C1", "2026-01-10", "100.00", "A")
    receipt(ar, "C1", "2026-01-20", "500.00")
    found = {i["kind"]: i for i in items(ar, "2026-12-31")}

    def insert_directly() -> None:
        with transaction.atomic():
            set_context(tenant_id=ar["ws"]["id"])
            Allocation.objects.create(
                tenant_id=ar["ws"]["id"],
                legal_entity_id=ar["entity"]["id"],
                debit_line_id=found["INVOICE"]["line_id"],
                credit_line_id=found["PAYMENT"]["line_id"],
                amount=Decimal("100.01"),
                allocated_on="2026-01-20",
                created_by=ar["owner"],
            )

    with pytest.raises(DatabaseError, match="exceeds"):
        insert_directly()


def test_payables_side_reconciles(ar: dict[str, Any]) -> None:
    supplier = ar["parties"]["S1"]
    post(ar, "2026-02-01", [
        {"account_id": "5000", "debit": "300.00"},
        {"account_id": "2100", "credit": "300.00", "counterparty_id": supplier,
         "reference": "PI-9"},
    ])  # fmt: skip
    post(ar, "2026-02-20", [
        {"account_id": "2100", "debit": "120.00", "counterparty_id": supplier},
        {"account_id": "1300", "credit": "120.00"},
    ])  # fmt: skip
    found = {i["kind"]: i for i in items(ar, "2026-03-31", side="PAYABLE")}
    assert found["INVOICE"]["due_date"] == "2026-03-18"  # 45 days
    report = ageing(ar, "2026-03-31", "PAYABLE")
    assert report["reconciles"] is True
    assert report["total"] == "180.00"
    assert report["unapplied"] == "120.00"
    assert tb_balance(ar, "2100", "2026-03-31") == Decimal("180.00")  # normal (credit) side


def test_disputed_invoices_are_skipped_by_auto_allocation(ar: dict[str, Any]) -> None:
    invoice(ar, "C1", "2026-01-10", "100.00", "A")
    invoice(ar, "C1", "2026-01-11", "100.00", "B")
    receipt(ar, "C1", "2026-01-20", "100.00")
    first = next(i for i in items(ar, "2026-12-31") if i["reference"] == "A")
    flag = ar["client"].put_json(f"{ar['base']}/open-items/{first['line_id']}/flag",
                                 {"disputed": True, "note": "Goods damaged"})  # fmt: skip
    assert flag.json()["disputed"] is True
    ar["client"].post_json(f"{ar['base']}/counterparties/{ar['parties']['C1']}/auto-allocate",
                           {"as_of": "2026-12-31"})  # fmt: skip
    status = {i["reference"]: i["status"] for i in items(ar, "2026-12-31", include_settled="true")
              if i["kind"] == "INVOICE"}  # fmt: skip
    assert status == {"A": "OPEN", "B": "SETTLED"}
    not_control = ar["client"].put_json(f"{ar['base']}/open-items/{uuid.uuid4()}/flag",
                                        {"disputed": True})  # fmt: skip
    assert not_control.status_code == 404


def test_reversing_an_invoice_creates_a_matching_credit_note(ar: dict[str, Any]) -> None:
    original = invoice(ar, "C1", "2026-01-10", "119.00", "INV-X")
    reversal = (
        ar["client"]
        .post_json(
            f"{ar['base']}/journal-entries/{original['id']}/reverse", {"reason": "Wrong customer"}
        )
        .json()
    )
    assert reversal["lines"][0]["counterparty_id"] == ar["parties"]["C1"]
    assert reversal["lines"][0]["reference"] == "INV-X"
    assert act(ar, reversal["id"], "post").status_code == 200
    ar["client"].post_json(f"{ar['base']}/counterparties/{ar['parties']['C1']}/auto-allocate",
                           {"as_of": "2026-12-31"})  # fmt: skip
    assert items(ar, "2026-12-31") == []
    assert ageing(ar, "2026-12-31")["total"] == "0.00"


def test_ageing_csv_is_formula_safe(ar: dict[str, Any]) -> None:
    ar["client"].post_json(f"{ar['base']}/counterparties",
                           {"code": "EVIL", "name": '=HYPERLINK("x")',
                            "kind": "CUSTOMER"})  # fmt: skip
    evil = next(c["id"] for c in ar["client"].get(f"{ar['base']}/counterparties").json()
                if c["code"] == "EVIL")  # fmt: skip
    ar["parties"]["EVIL"] = evil
    invoice(ar, "EVIL", "2026-01-10", "10.00")
    csv_text = (
        ar["client"]
        .get(f"{ar['base']}/reports/ageing.csv?as_of=2026-12-31&side=RECEIVABLE")
        .content.decode()
    )
    assert "'=HYPERLINK" in csv_text
    assert csv_text.splitlines()[0].startswith("code,name,current")


def test_inactive_counterparties_cannot_be_used_on_new_lines(ar: dict[str, Any]) -> None:
    csrf = {"X-CSRFToken": ar["client"].cookies["__Host-fcp_csrftoken"].value}
    ar["client"].patch(f"{ar['base']}/counterparties/{ar['parties']['C2']}",
                       {"status": "INACTIVE"}, content_type="application/json",
                       headers=csrf)  # fmt: skip
    acc = ar["accounts"]
    response = ar["client"].post_json(f"{ar['base']}/journal-entries", {
        "accounting_date": "2026-01-10", "description": "x",
        "lines": [{"account_id": acc["1200"]["id"], "debit": "10.00",
                   "counterparty_id": ar["parties"]["C2"]},
                  {"account_id": acc["4000"]["id"], "credit": "10.00"}]})  # fmt: skip
    assert response.status_code == 422
    assert response.json()["errors"]["lines.0.counterparty_id"] == ["inactive"]
    active = ar["client"].get(f"{ar['base']}/counterparties?status=ACTIVE").json()
    assert "C2" not in {c["code"] for c in active}


def test_bad_inputs_are_rejected(ar: dict[str, Any]) -> None:
    bad_kind = ar["client"].post_json(f"{ar['base']}/counterparties",
                                      {"code": "K", "name": "K", "kind": "ALIEN"})  # fmt: skip
    assert bad_kind.status_code == 422
    side = ar["client"].get(f"{ar['base']}/reports/ageing?as_of=2026-12-31&side=SIDEWAYS")
    assert side.status_code == 422
    unknown = ar["client"].post_json(f"{ar['base']}/allocations", {
        "invoice_line_id": str(uuid.uuid4()), "payment_line_id": str(uuid.uuid4()),
        "amount": "1.00"})  # fmt: skip
    assert unknown.status_code == 404
    rent = post(ar, "2026-01-05", [{"account_id": "6100", "debit": "5.00"},
                                   {"account_id": "1300", "credit": "5.00"}])  # fmt: skip
    not_control = ar["client"].put_json(
        f"{ar['base']}/open-items/{_line_id(ar, rent)}/flag",
        {"disputed": True},
    )
    assert not_control.status_code == 404


def _line_id(ar: dict[str, Any], entry: dict[str, Any]) -> str:
    from fcp.modules.ledger.api import JournalLine  # noqa: PLC0415 - test helper

    set_context(tenant_id=ar["ws"]["id"])
    return str(JournalLine.objects.filter(entry_id=entry["id"]).first().id)  # type: ignore[union-attr]
