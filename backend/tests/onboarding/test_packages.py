"""An accountant's trial balance and accounting-package report exports (R-3, #246; AC-R2, AC-R3).

Every file here is synthetic. The layouts are typical (a title, section headings, subtotals, a
total; "Dr" and "Cr"; aged reports with a contact column and ageing buckets), not copies of any
package's real export: the package presets stay "to be confirmed"."""

from decimal import Decimal
from typing import Any

import pytest

from fcp.modules.ledger.models import JournalEntry
from fcp.modules.registers.models import Counterparty

from ..ledger.conftest import books
from .test_imports import PARTIES, messages, send, table

__all__ = ["books"]
pytestmark = pytest.mark.django_db


def opening(b: dict[str, Any], files: dict[str, tuple[str, bytes]], commit: bool = False,
            **form: str) -> Any:  # fmt: skip
    return send(b, "opening-balances", files, commit,
                **{"as_of": "2026-01-01", "account_map": "{}", **form})  # fmt: skip


# An accountant's year-end trial balance, as delivered: a title, headings, codes and names in one
# column, Dr and Cr, subtotals, a total, and the year's income and expense still open.
ACCOUNTANT = table(
    ["Demo Trading Ltd (Demo)"],
    ["Trial balance at 31 December 2025"],
    [],
    ["Account", "Debit", "Credit"],
    ["Current assets", "", ""],
    ["1300 Bank - current account", "10.500,00", ""],
    ["1200 Trade receivables", "2.000,00", ""],
    ["Total current assets", "12.500,00", ""],
    ["Equity", "", ""],
    ["Share capital", "", "5.000,00"],  # matched by its name
    ["1350 Cash in hand", "0,00", "0,00"],  # no balance: skipped
    ["Sales revenue", "", "20.000,00"],
    ["Rent", "12.500,00", ""],
    ["Total", "25.000,00", "25.000,00"],
    delimiter=";",
)

AGED = table(
    ["Aged receivables detail (Demo)"],
    ["Contact", "Invoice Number", "Invoice Date", "Due Date", "Current", "1 - 30", "Total"],
    ["Example Customer Ltd (Demo)", "INV-0017", "15 Dec 2025", "14 Jan 2026", "1500.00", "",
     "1500.00"],
    ["Example Customer Ltd (Demo)", "INV-0018", "20 Dec 2025", "", "", "300.00", "300.00"],
    ["Total Example Customer Ltd (Demo)", "", "", "", "1500.00", "300.00", "1800.00"],
    ["New Client Ltd (Demo)", "INV-0020", "28 Dec 2025", "27 Jan 2026", "200.00", "", "200.00"],
    ["Total", "", "", "", "1700.00", "300.00", "2000.00"],
)  # fmt: skip


def test_an_accountants_year_end_trial_balance_opens_the_next_year(books: dict[str, Any]) -> None:
    send(books, "counterparties", {"file": ("p.csv", PARTIES)}, commit=True)
    found = opening(books, {"file": ("tb.csv", ACCOUNTANT), "aged_receivables": ("ar.csv", AGED)})
    # The year's income and expense are still open; and one customer is not set up yet.
    assert found["warnings"]
    assert "Income and expense accounts" in found["warnings"][0]
    assert found["unknown_counterparties"] == [
        {"name": "New Client Ltd (Demo)", "side": "RECEIVABLE", "rows": [6]}]  # fmt: skip
    assert "6:Contact:New Client Ltd (Demo) is not set up" in "\n".join(messages(found))
    done = opening(
        books,
        {"file": ("tb.csv", ACCOUNTANT), "aged_receivables": ("ar.csv", AGED)},
        commit=True,
        results_account="3200",
        create_counterparties="true",
    )
    assert (done["committed"], done["problems"], done["warnings"]) == (True, [], [])
    assert done["counterparties"] == ["NEW-CLIENT-LTD-DEMO"]
    entry = JournalEntry.objects.get(id=done["entry_id"])
    nets: dict[str, Decimal] = {}
    for ln in entry.lines.select_related("account"):
        nets[ln.account.code] = nets.get(ln.account.code, Decimal(0)) + ln.debit - ln.credit
    # Sales 20,000 less rent 12,500: a profit of 7,500 carried into retained earnings.
    assert nets == {"1300": Decimal("10500.00"), "1200": Decimal("2000.00"),
                    "3000": Decimal("-5000.00"), "3200": Decimal("-7500.00")}  # fmt: skip
    refs = {ln.reference: ln for ln in entry.lines.filter(account__code="1200")}
    assert set(refs) == {"INV-0017", "INV-0018", "INV-0020"}
    assert str(refs["INV-0017"].due_date) == "2026-01-14"
    assert str(refs["INV-0018"].due_date) == "2026-01-19"  # 20 Dec + 30 days' terms
    created = Counterparty.objects.get(code="NEW-CLIENT-LTD-DEMO")
    assert (created.name, created.kind) == ("New Client Ltd (Demo)", "CUSTOMER")


def test_the_files_own_total_is_checked_against_its_lines(books: dict[str, Any]) -> None:
    wrong = table(["Account", "Debit", "Credit"], ["1300", "100.00", ""], ["3000", "", "100.00"],
                  ["Total", "110.00", "100.00"])  # fmt: skip
    found = opening(books, {"file": ("tb.csv", wrong)})
    assert messages(found) == [
        "4:Debit:The file's total (110.00 / 100.00) differs from its lines (100.00 / 100.00)."
    ]
    signed = table(["Code", "Closing balance"], ["1300", "100.00 Dr"], ["3000", "100.00 Cr"],
                   ["Grand total", "0.00"])  # fmt: skip
    assert opening(books, {"file": ("tb.csv", signed)})["problems"] == []


def test_a_month_first_aged_payables_report(books: dict[str, Any]) -> None:
    send(books, "counterparties", {"file": ("p.csv", PARTIES)}, commit=True)
    tb = table(["Account", "Balance"], ["1300", "1000.00"], ["2100", "-1000.00"])
    report = table(
        ["Vendor", "Num", "Date", "Due Date", "Open Balance"],
        ["Example Supplier Ltd (Demo)", "B-555", "12/15/2025", "01/14/2026", "1,000.00"],
        ["Total for Example Supplier Ltd (Demo)", "", "", "", "1,000.00"],
    )  # fmt: skip
    files = {"file": ("tb.csv", tb), "aged_payables": ("ap.csv", report)}
    day_first = opening(books, files)
    assert messages(day_first)[0] == ("2:Date:'12/15/2025' reads only month first (12/31/2026): "
                                      "choose that date order for this file.")  # fmt: skip
    found = opening(books, files, commit=True, date_order="month")
    assert found["committed"] is True
    line = JournalEntry.objects.get(id=found["entry_id"]).lines.get(account__code="2100")
    assert (line.credit, line.reference, str(line.due_date)) == (
        Decimal("1000.00"), "B-555", "2026-01-14")  # fmt: skip


def test_a_package_chart_of_accounts(books: dict[str, Any]) -> None:
    chart = table(
        ["*Code", "*Name", "*Type", "Tax Code", "Description"],
        ["8200", "Debtors (Demo)", "Accounts Receivable", "", ""],
        ["8300", "Credit card (Demo)", "Credit Card", "", ""],
        ["8400", "Consulting income (Demo)", "Revenue", "", ""],
        ["8500", "Office overheads (Demo)", "Overhead", "", ""],
    )  # fmt: skip
    found = send(books, "chart", {"file": ("chart.csv", chart)}, commit=True)
    assert (found["committed"], found["problems"]) == (True, [])
    rows = {a["code"]: a for a in books["client"].get(f"{books['base']}/accounts").json()}
    assert (rows["8200"]["type"], rows["8200"]["control_type"]) == ("ASSET", "RECEIVABLE")
    assert [rows[c]["type"] for c in ("8300", "8400", "8500")] == [
        "LIABILITY", "INCOME", "EXPENSE"]  # fmt: skip


def test_presets_are_to_be_confirmed(books: dict[str, Any]) -> None:
    presets = books["client"].get(f"{books['base']}/imports/presets").json()
    assert [(p["key"], p["day_first"], p["status"]) for p in presets] == [
        ("XERO", True, "TO_BE_CONFIRMED"), ("QUICKBOOKS", False, "TO_BE_CONFIRMED")]  # fmt: skip


def test_two_receivables_accounts_need_an_account_column(books: dict[str, Any]) -> None:
    send(books, "chart", {"file": ("c.csv", table(
        ["Code", "Name", "Type", "Control"], ["1201", "Other debtors", "Asset", "Receivable"]))},
        commit=True)  # fmt: skip
    found = opening(books, {"file": ("tb.csv", table(["Account", "Balance"], ["1300", "1"],
                                                     ["3000", "-1"])),
                            "aged_receivables": ("ar.csv", AGED)})  # fmt: skip
    assert ("0::The chart has no single receivables account; add an Account code column to the "
            "report.") in messages(found)  # fmt: skip
