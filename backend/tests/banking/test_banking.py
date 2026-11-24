"""Bank accounts, statement imports, matching and reconciliation (M2-5, AC-M2-5)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import DatabaseError, connection, transaction
from django.test import override_settings

from fcp.core.db.rls import set_context
from fcp.devtools.demo.camt import Txn, camt053
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.banking import parsers
from fcp.modules.banking.models import StatementLine
from fcp.modules.banking.services import process_pending
from fcp.modules.ledger.models import JournalEntry, JournalLine

from ..ledger.conftest import books, join
from ..ledger.test_dimensions import commit_point
from ..ledger.test_entries import act
from .test_parsers import LAUGHS, XXE

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]
IBAN = "CY17002001280000001200527600"
RECEIPT = Txn(
    date(2026, 3, 1), Decimal("1190.00"), "Invoice INV-1", "INV-1", "Customer (Demo)", "B1"
)
RENT = Txn(date(2026, 3, 2), Decimal("-250.50"), "Rent March", "", "Landlord (Demo)", "B2")
FEE = Txn(date(2026, 3, 3), Decimal("-4.00"), "Bank fee", "", "", "B3")


@pytest.fixture
def bank(books: dict[str, Any]) -> dict[str, Any]:
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    made = books["client"].post_json(
        f"{books['base']}/bank-accounts",
        {
            "ledger_account_id": books["accounts"]["1300"]["id"],
            "name": "Current account",
            "iban": "CY17 0020 0128 0000 0012 0052 7600",
        },
    )
    assert made.status_code == 201, made.content
    books["bank"] = made.json()
    books["bank_url"] = f"{books['base']}/bank-accounts/{made.json()['id']}"
    return books


def upload(b: dict[str, Any], data: bytes, fmt: str = "CAMT053", name: str = "s.xml") -> Any:
    client = b["client"]
    return client.post(
        f"{b['bank_url']}/imports",
        {"file": SimpleUploadedFile(name, data), "format": fmt},
        headers=client._csrf(),
    )


def statement(*txns: Txn, opening: str = "1000.00", sid: str = "S1") -> bytes:
    return camt053(txns, iban=IBAN, opening=Decimal(opening), statement_id=sid)


def lines(b: dict[str, Any], status: str | None = None) -> list[dict[str, Any]]:
    query = {"status": status} if status else {}
    result: list[dict[str, Any]] = b["client"].get(f"{b['bank_url']}/lines", query).json()
    return result


def post(
    b: dict[str, Any], day: str, debit: str, credit: str, amount: str, reference: str = ""
) -> dict[str, Any]:
    acc = b["accounts"]
    body = {
        "accounting_date": day,
        "description": f"Booked {reference}".strip(),
        "lines": [
            {"account_id": acc[debit]["id"], "debit": amount, "reference": reference},
            {"account_id": acc[credit]["id"], "credit": amount, "reference": reference},
        ],
    }
    draft = b["client"].post_json(f"{b['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    posted = act(b, draft.json()["id"], "post")
    assert posted.status_code == 200, posted.content
    commit_point()
    result: dict[str, Any] = posted.json()
    return result


# --- bank accounts --------------------------------------------------------------------------------


def test_bank_accounts_link_to_a_postable_asset_account(bank: dict[str, Any]) -> None:
    client, base, acc = bank["client"], bank["base"], bank["accounts"]
    assert bank["bank"]["iban"] == IBAN  # normalised
    income = client.post_json(
        f"{base}/bank-accounts", {"ledger_account_id": acc["4000"]["id"], "name": "X"}
    )
    assert income.status_code == 422
    bad_iban = client.post_json(
        f"{base}/bank-accounts",
        {"ledger_account_id": acc["1310"]["id"], "name": "X", "iban": "CY00 1234"},
    )
    assert bad_iban.json()["errors"] == {"iban": ["invalid"]}
    again = client.post_json(
        f"{base}/bank-accounts", {"ledger_account_id": acc["1300"]["id"], "name": "Again"}
    )
    assert again.status_code == 409
    set_context(tenant_id=bank["ws"]["id"])
    event = AuditEvent.objects.get(action="banking.account.created")
    assert event.changes["iban"] == "…7600"  # masked in the audit trail


# --- imports (AC-M2-5) ----------------------------------------------------------------------------


def test_importing_the_same_statement_twice_creates_no_duplicates(bank: dict[str, Any]) -> None:
    first = upload(bank, statement(RECEIPT, RENT))
    assert first.status_code == 201, first.content
    done = first.json()
    assert (done["status"], done["lines_created"], done["closing_balance"]) == (
        "DONE",
        2,
        "1939.50",
    )
    again = upload(bank, statement(RECEIPT, RENT))
    assert again.status_code == 409
    assert again.json()["code"] == "banking.import.duplicate"
    # An overlapping statement (a different file) adds only the new transaction.
    overlap = upload(bank, statement(RECEIPT, RENT, FEE, sid="S2")).json()
    assert (overlap["lines_created"], overlap["lines_duplicate"]) == (1, 2)
    assert len(lines(bank)) == 3


@pytest.mark.parametrize("payload", [XXE, LAUGHS], ids=["xxe", "billion-laughs"])
def test_malicious_xml_is_rejected_and_nothing_is_imported(
    bank: dict[str, Any], payload: bytes
) -> None:
    result = upload(bank, payload).json()
    assert result["status"] == "FAILED"
    assert "refused for safety" in result["error"]
    assert lines(bank) == []


def test_statements_of_another_account_or_too_large_are_refused(bank: dict[str, Any]) -> None:
    other = camt053([RECEIPT], iban="GB82WEST12345698765432", opening=Decimal(0))
    assert "is for account …5432" in upload(bank, other).json()["error"]
    big = upload(bank, b"x" * (parsers.MAX_BYTES + 1))
    assert big.status_code == 422
    assert big.json()["code"] == "banking.statement.invalid"


def test_csv_import_with_a_saved_bank_mapping(bank: dict[str, Any]) -> None:
    mapping = {
        "date": "Datum",
        "amount": "",
        "debit": "Χρέωση",
        "credit": "Πίστωση",
        "description": "Περιγραφή",
        "date_format": "%d/%m/%Y",
        "delimiter": ";",
        "decimal_comma": True,
        "encoding": "utf-8",
    }
    saved = bank["client"].put_json(f"{bank['bank_url']}/csv-mapping", mapping)
    assert saved.status_code == 200, saved.content
    data = "Datum;Περιγραφή;Χρέωση;Πίστωση\n01/03/2026;Είσπραξη;;1.190,00\n".encode()
    result = upload(bank, data, "CSV", "s.csv").json()
    assert (result["status"], result["lines_created"]) == ("DONE", 1)
    assert lines(bank)[0]["amount"] == "1190.00"
    # A failed import can be retried with the same file once the mapping is fixed.
    data2 = "Datum;Ποσό\n02/03/2026;5,00\n".encode()
    failed = upload(bank, data2, "CSV", "s2.csv").json()
    assert failed["status"] == "FAILED"
    fixed = {**mapping, "debit": "", "credit": "", "amount": "Ποσό", "description": ""}
    assert bank["client"].put_json(f"{bank['bank_url']}/csv-mapping", fixed).status_code == 200
    retried = upload(bank, data2, "CSV", "s2.csv").json()
    assert (retried["status"], retried["lines_created"]) == ("DONE", 1)
    wrong = bank["client"].put_json(
        f"{bank['bank_url']}/csv-mapping", {**mapping, "date_format": "%s"}
    )
    assert wrong.status_code == 422


# --- matching -------------------------------------------------------------------------------------


def test_auto_match_uses_amount_date_and_reference_and_never_guesses(bank: dict[str, Any]) -> None:
    upload(bank, statement(RECEIPT, RENT, FEE))
    post(bank, "2026-03-01", "1300", "4000", "1190.00", "INV-1")
    post(bank, "2026-03-03", "6100", "1300", "250.50")
    post(bank, "2026-03-04", "6900", "1300", "4.00")
    post(bank, "2026-03-05", "6900", "1300", "4.00")  # two equal candidates for the fee
    matched = bank["client"].post_json(f"{bank['bank_url']}/auto-match", {})
    assert matched.json() == {"matched": 2}
    fee = next(ln for ln in lines(bank) if ln["amount"] == "-4.00")
    assert fee["status"] == "UNMATCHED"  # ambiguous: left for a person

    line_url = f"{bank['base']}/statement-lines/{fee['id']}"
    candidates = bank["client"].get(f"{line_url}/candidates").json()
    assert len(candidates) == 2
    chosen = bank["client"].post_json(
        f"{line_url}/match", {"journal_line_id": candidates[1]["journal_line_id"]}
    )
    assert chosen.json()["status"] == "MATCHED"
    taken = bank["client"].post_json(
        f"{line_url}/match", {"journal_line_id": candidates[0]["journal_line_id"]}
    )
    assert taken.status_code == 409
    assert bank["client"].post_json(f"{line_url}/unmatch", {}).json()["status"] == "UNMATCHED"
    assert bank["client"].post_json(f"{line_url}/ignore", {"note": "x"}).status_code == 422
    ignored = bank["client"].post_json(f"{line_url}/ignore", {"note": "Booked in bulk"})
    assert ignored.json()["status"] == "IGNORED"


def test_an_unmatched_line_can_be_booked_and_is_then_matched(bank: dict[str, Any]) -> None:
    upload(bank, statement(FEE))
    line = lines(bank)[0]
    created = bank["client"].post_json(
        f"{bank['base']}/statement-lines/{line['id']}/create-entry",
        {"account_id": bank["accounts"]["6900"]["id"], "description": "Bank fee March"},
    )
    assert created.status_code == 201, created.content
    entry = (
        bank["client"].get(f"{bank['base']}/journal-entries/{created.json()['entry_id']}").json()
    )
    set_context(tenant_id=bank["ws"]["id"])
    assert JournalEntry.objects.get(id=entry["id"]).source == "IMPORT"
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in entry["lines"]] == [
        ("1300", "0.00", "4.00"),
        ("6900", "4.00", "0.00"),
    ]
    assert act(bank, entry["id"], "post").status_code == 200
    commit_point()
    assert bank["client"].post_json(f"{bank['bank_url']}/auto-match", {}).json() == {"matched": 1}


def test_payments_suggest_the_open_invoice_they_settle(bank: dict[str, Any]) -> None:
    client, base = bank["client"], bank["base"]
    customer = client.post_json(
        f"{base}/counterparties", {"code": "C1", "name": "Customer (Demo)", "kind": "CUSTOMER"}
    ).json()
    invoice = {
        "accounting_date": "2026-02-01",
        "description": "Invoice INV-1",
        "lines": [
            {
                "account_id": bank["accounts"]["1200"]["id"],
                "debit": "1190.00",
                "counterparty_id": customer["id"],
                "reference": "INV-1",
            },
            {"account_id": bank["accounts"]["4000"]["id"], "credit": "1190.00"},
        ],
    }
    draft = client.post_json(f"{base}/journal-entries", invoice).json()
    assert act(bank, draft["id"], "post").status_code == 200
    commit_point()
    upload(bank, statement(RECEIPT))
    line = lines(bank)[0]
    found = client.get(f"{base}/statement-lines/{line['id']}/suggestions").json()
    assert [(s["counterparty_code"], s["reference"], s["reference_matches"]) for s in found] == [
        ("C1", "INV-1", True)
    ]
    booked = client.post_json(
        f"{base}/statement-lines/{line['id']}/create-entry",
        {
            "account_id": bank["accounts"]["1200"]["id"],
            "counterparty_id": found[0]["counterparty_id"],
        },
    )
    assert booked.status_code == 201, booked.content


# --- reconciliation (AC-M2-5) ---------------------------------------------------------------------


def test_reconciled_only_when_the_ledger_equals_the_statement(bank: dict[str, Any]) -> None:
    upload(bank, statement(RECEIPT, RENT, opening="0.00"))
    url = f"{bank['bank_url']}/reconcile"
    before = bank["client"].post_json(url, {"as_of": "2026-03-02"}).json()
    assert before == {
        "as_of": "2026-03-02",
        "statement_balance": "939.50",
        "ledger_balance": "0.00",
        "difference": "-939.50",
        "unmatched_lines": 2,
        "reconciled": False,
    }
    post(bank, "2026-03-01", "1300", "4000", "1190.00", "INV-1")
    post(bank, "2026-03-02", "6100", "1300", "250.50")
    after = bank["client"].post_json(url, {"as_of": "2026-03-02"}).json()
    assert (after["reconciled"], after["ledger_balance"], after["difference"]) == (
        True,
        "939.50",
        "0.00",
    )
    accounts = bank["client"].get(f"{bank['base']}/bank-accounts").json()
    assert accounts[0]["last_reconciled"]["as_of"] == "2026-03-02"
    missing = bank["client"].post_json(url, {"as_of": "2026-03-10"})
    assert missing.status_code == 422
    given = bank["client"].post_json(url, {"as_of": "2026-03-10", "statement_balance": "939.50"})
    assert given.json()["reconciled"] is True
    assert len(bank["client"].get(f"{bank['bank_url']}/reconciliations").json()) == 2


def test_database_guards_matching_and_reconciliations(bank: dict[str, Any]) -> None:
    upload(bank, statement(RENT))
    rent = post(bank, "2026-03-02", "6100", "1300", "250.50")
    expense = bank["accounts"]["6100"]["id"]
    bank["client"].post_json(
        f"{bank['bank_url']}/reconcile", {"as_of": "2026-03-02", "statement_balance": "-250.50"}
    )
    set_context(tenant_id=bank["ws"]["id"])
    line = StatementLine.objects.get()
    expense_line = JournalLine.objects.get(entry_id=rent["id"], account_id=expense)
    with pytest.raises(DatabaseError, match="matches only a posted line"), transaction.atomic():
        StatementLine.objects.filter(id=line.id).update(
            status="MATCHED", matched_line_id=expense_line.id
        )
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("UPDATE banking_reconciliation SET as_of = as_of - 1")


# --- worker, permissions, isolation ---------------------------------------------------------------


def test_the_worker_parses_pending_imports(bank: dict[str, Any]) -> None:
    with override_settings(BANKING_PROCESS_INLINE=False):
        pending = upload(bank, statement(RECEIPT)).json()
    assert (pending["status"], pending["lines_created"]) == ("PENDING", 0)
    assert process_pending() == 1
    call_command("banking_process_imports")  # nothing left; runs cleanly
    imports = bank["client"].get(f"{bank['bank_url']}/imports").json()
    assert (imports[0]["status"], imports[0]["lines_created"]) == ("DONE", 1)


def test_read_only_users_see_but_do_not_change_and_other_tenants_see_nothing(
    bank: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(
        bank["client"], bank["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    assert viewer.get(f"{bank['base']}/bank-accounts").status_code == 200
    refused = viewer.post(
        f"{bank['bank_url']}/imports",
        {"file": SimpleUploadedFile("s.xml", statement(RECEIPT)), "format": "CAMT053"},
        headers=viewer._csrf(),
    )
    assert refused.status_code == 403
    stranger = api_client(make_user("stranger@example.test"))
    assert stranger.get(f"{bank['base']}/bank-accounts").status_code == 404
