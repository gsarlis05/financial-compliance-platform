"""Bringing existing books in from spreadsheets (R-2, #245; AC-R2, AC-R3). Synthetic files only."""

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook, load_workbook

from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger.models import JournalEntry
from fcp.modules.onboarding import tables, templates
from fcp.modules.onboarding.tables import FORMULA, Problem, TableError

from ..ledger.conftest import books
from ..ledger.test_entries import act

__all__ = ["books"]


def table(*rows: list[object], delimiter: str = ",") -> bytes:
    out = io.StringIO()
    csv.writer(out, delimiter=delimiter, lineterminator="\n").writerows(rows)
    return out.getvalue().encode()


def workbook(*rows: list[object]) -> bytes:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def send(b: dict[str, Any], kind: str, files: dict[str, tuple[str, bytes]],
         commit: bool = False, **form: str) -> Any:  # fmt: skip
    client = b["client"]
    body: dict[str, Any] = {k: SimpleUploadedFile(name, data) for k, (name, data) in files.items()}
    response = client.post(f"{b['base']}/imports/{kind}",
                           {**body, **form, "commit": "true" if commit else "false"},
                           headers=client._csrf())  # fmt: skip
    assert response.status_code == 200, response.content
    return response.json()


def messages(found: dict[str, Any]) -> list[str]:
    return [f"{p['row']}:{p['column']}:{p['message']}" for p in found["problems"]]


# --- reading cells ------------------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [
    ("1250.00", "1250.00"), ("1.250,00", "1250.00"), ("1,250.50", "1250.50"),
    ("1250,5", "1250.50"), ("-4,20", "-4.20"), ("(300.00)", "-300.00"), ("1 250,00", "1250.00"),
    ("€ 1.000.000", "1000000.00"), ("", "0.00"), (None, "0.00"), (12.1, "12.10"), (7, "7.00"),
    (Decimal("3.5"), "3.50"),
])  # fmt: skip
def test_amounts_are_read_exactly(raw: object, expected: str) -> None:
    assert tables.amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["1,250", "1.250", "12.345", "abc", "1.2.3,4,5", True, FORMULA,
                                 "1.005", 10**16])  # fmt: skip
def test_ambiguous_or_malformed_amounts_are_problems(raw: object) -> None:
    assert isinstance(tables.amount(raw), Problem)


def test_dates_text_and_flags() -> None:
    assert tables.day("03/04/2026") == date(2026, 4, 3)  # day first
    assert tables.day("2026-04-03") == tables.day("03.04.2026") == date(2026, 4, 3)
    assert tables.day("") is None
    assert isinstance(tables.day("April 3"), Problem)
    assert tables.text(" Rent ", 10) == "Rent"
    assert tables.text(1010.0, 10) == "1010"  # a code Excel stored as a number
    assert isinstance(tables.text("=HYPERLINK(1)", 50), Problem)
    assert isinstance(tables.text("x" * 11, 10), Problem)
    assert tables.flag("Ναι", False, templates.YES, templates.NO) is True  # noqa: RUF001 - Greek "yes"
    assert tables.flag("no", True, templates.YES, templates.NO) is False
    assert isinstance(tables.flag("maybe", True, templates.YES, templates.NO), Problem)


def test_files_that_cannot_be_read_are_refused() -> None:
    fields = templates.fields("chart")
    ready = lambda f: {"code", "name", "type"} <= f  # noqa: E731
    with pytest.raises(TableError, match="empty"):
        tables.read(b"", "a.csv", fields, ready, "no header")
    with pytest.raises(TableError, match="no header"):
        tables.read(b"x,y\n1,2\n", "a.csv", fields, ready, "no header")
    with pytest.raises(TableError, match=r"not an \.xlsx"):
        tables.read(b"PK\x03\x04broken", "a.xlsx", fields, ready, "no header")
    found = tables.read(
        table(
            ["Title"],
            [],
            ["Κωδικός", "Περιγραφή", "Τύπος", "Extra"],
            ["1", "Assets", "Asset", "ignored"],
        ),
        "g.csv",
        fields,
        ready,
        "-",
    )
    assert found.columns == {"code": "Κωδικός", "name": "Περιγραφή", "type": "Τύπος"}
    assert found.rows == [(4, {"code": "1", "name": "Assets", "type": "Asset"})]


# --- templates ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_templates_download_and_read_back(books: dict[str, Any]) -> None:
    client = books["client"]
    for kind in templates.KINDS:
        got = client.get(f"{books['base']}/imports/templates/{kind}")
        assert got.status_code == 200
        book = load_workbook(io.BytesIO(got.content))
        assert book.sheetnames == ["Import", "How to fill in"]
        assert [c.value for c in book["Import"][1]] == [c.header for c in templates.columns(kind)]
        as_csv = client.get(f"{books['base']}/imports/templates/{kind}", {"format": "csv"})
        assert as_csv.content.decode("utf-8-sig").startswith(templates.columns(kind)[0].header)
    # A filled-in template is read back from its first sheet only.
    got = client.get(f"{books['base']}/imports/templates/counterparties")
    book = load_workbook(io.BytesIO(got.content))
    book["Import"].append(["C-9", "Filled Ltd (Demo)", "Customer", "", "", 15, "CY"])
    out = io.BytesIO()
    book.save(out)
    found = send(books, "counterparties", {"file": ("c.xlsx", out.getvalue())})
    assert (found["counterparties"], found["problems"]) == (["C-9"], [])


# --- 1. chart of accounts -----------------------------------------------------------------------


CHART = table(
    ["Code", "Name", "Type", "Parent code", "Postable", "Control", "VAT role", "Greek name"],
    ["8", "Other headings", "Expense", "", "No", "", "", ""],
    ["8100", "Subscriptions (Demo)", "Expense", "80", "Yes", "", "", ""],
    ["80", "Office costs", "Expense", "8", "No", "", "", "Έξοδα γραφείου"],
    ["4000", "Sales revenue", "Income", "", "", "", "", ""],  # identical: skipped
)


@pytest.mark.django_db
def test_chart_preview_creates_nothing_then_commit_creates_parents_first(
    books: dict[str, Any],
) -> None:
    preview = send(books, "chart", {"file": ("chart.csv", CHART)})
    assert (preview["committed"], preview["problems"]) == (False, [])
    assert preview["accounts"] == ["8", "80", "8100"]
    assert preview["skipped"] == ["4000"]
    codes = {a["code"] for a in books["client"].get(f"{books['base']}/accounts").json()}
    assert "8100" not in codes
    done = send(books, "chart", {"file": ("chart.csv", CHART)}, commit=True)
    assert done["committed"] is True
    chart = {a["code"]: a for a in books["client"].get(f"{books['base']}/accounts").json()}
    assert chart["8100"]["parent_id"] == chart["80"]["id"]
    assert chart["80"]["name_el"] == "Έξοδα γραφείου"
    event = AuditEvent.objects.filter(action="onboarding.import.completed").get()
    assert event.changes["kind"] == "chart"
    assert len(event.changes["files"]["chart.csv"]) == 64
    # The same file again: everything is already there.
    again = send(books, "chart", {"file": ("chart.csv", CHART)})
    assert (again["accounts"], sorted(again["skipped"])) == ([], ["4000", "8", "80", "8100"])


@pytest.mark.django_db
def test_chart_problems_are_listed_by_row_and_nothing_is_created(books: dict[str, Any]) -> None:
    bad = table(
        ["Code", "Name", "Type", "Parent code", "Postable"],
        ["8100", "Subscriptions", "Spending", "", ""],
        ["8200", "", "Expense", "", ""],
        ["8300", "Travel", "Expense", "1300", ""],  # parent postable
        ["8400", "Gifts", "Expense", "77", ""],  # parent unknown
        ["4000", "Turnover", "Income", "", ""],  # differs from the chart
        ["8500", "Fees", "Expense", "", "maybe"],
        ["8600", "Ok", "Expense", "", ""],
        ["8600", "Twice", "Expense", "", ""],
    )
    found = send(books, "chart", {"file": ("c.csv", bad)}, commit=True)
    assert found["committed"] is False
    assert messages(found) == [
        "2:Type:Enter Asset, Liability, Equity, Income or Expense.",
        "3:Name:Enter the account name.",
        "4:Parent code:1300 is postable; a parent must be a heading (Postable: No).",
        "5:Parent code:77 is neither in this file nor in the chart.",
        "6:Code:4000 is already in the chart as 'Sales revenue' (Income).",
        "7:Postable:Enter Yes or No.",
        "9:Code:8600 is also on row 8.",
    ]
    codes = {a["code"] for a in books["client"].get(f"{books['base']}/accounts").json()}
    assert "8600" not in codes


# --- 2. customers and suppliers -----------------------------------------------------------------


PARTIES = table(
    ["Code", "Name", "Kind", "VAT number", "Email", "Payment terms (days)", "Country"],
    ["c-001", "Example Customer Ltd (Demo)", "Customer", "cy00000000x", "", "30", "cy"],
    ["S-001", "Example Supplier Ltd (Demo)", "Supplier", "", "a@example.test", "", "GR"],
)


@pytest.mark.django_db
def test_counterparties_import(books: dict[str, Any]) -> None:
    found = send(books, "counterparties", {"file": ("p.csv", PARTIES)}, commit=True)
    assert (found["committed"], found["counterparties"]) == (True, ["C-001", "S-001"])
    rows = {c["code"]: c for c in books["client"].get(f"{books['base']}/counterparties").json()}
    assert (rows["C-001"]["vat_no"], rows["C-001"]["country"]) == ("CY00000000X", "CY")
    assert rows["S-001"]["payment_terms_days"] == 30
    bad = table(["Code", "Name", "Kind", "Payment terms (days)", "Country"],
                ["C-001", "Someone else", "Customer", "", ""],
                ["C-002", "X", "Friend", "400", "C1"])  # fmt: skip
    found = send(books, "counterparties", {"file": ("p.csv", bad)})
    assert messages(found) == [
        "2:Code:C-001 is already used by another customer or supplier.",
        "3:Country:Enter two letters, such as CY.",
        "3:Kind:Enter Customer, Supplier or Both.",
        "3:Payment terms (days):Enter whole days from 0 to 365.",
    ]


# --- 3. opening balances with the open invoices -------------------------------------------------


TB = table(
    ["Account code", "Account name", "Debit", "Credit"],
    ["1300", "Bank - current account", "12.500,00", ""],
    ["1200", "Trade receivables", "4.000,50", ""],
    ["2100", "Trade payables", "", "1.000,00"],
    ["2120", "VAT payable (output VAT)", "", "600,00"],
    ["OLD-30", "Capital (old chart)", "", "14.900,50"],
    ["", "Total", "16.500,50", "16.500,50"],  # a totals row without an account: ignored
    delimiter=";",
)
ITEMS = table(
    ["Account code", "Customer or supplier code", "Invoice number", "Invoice date", "Due date",
     "Amount outstanding"],
    ["1200", "C-001", "INV-0017", "15/12/2025", "", "3400.50"],
    ["1200", "C-001", "INV-0018", "20/12/2025", "19/01/2026", "700.00"],
    ["1200", "C-001", "CN-0003", "28/12/2025", "", "-100.00"],
    ["2100", "S-001", "B-555", "10/12/2025", "", "1000.00"],
)  # fmt: skip


def opening(b: dict[str, Any], tb: bytes = TB, items: bytes | None = ITEMS, commit: bool = False,
            account_map: str = '{"OLD-30": "3000"}', as_of: str = "2026-01-01") -> Any:  # fmt: skip
    files = {"file": ("tb.csv", tb)}
    if items is not None:
        files["open_items"] = ("items.csv", items)
    return send(b, "opening-balances", files, commit, as_of=as_of, account_map=account_map)


@pytest.mark.django_db
def test_opening_balances_become_one_balanced_draft_equal_to_the_source(
    books: dict[str, Any],
) -> None:
    send(books, "counterparties", {"file": ("p.csv", PARTIES)}, commit=True)
    unmapped = opening(books, account_map="{}")
    assert [u["code"] for u in unmapped["unknown_accounts"]] == ["OLD-30"]
    assert unmapped["unknown_accounts"][0]["name"] == "Capital (old chart)"
    preview = opening(books)
    assert preview["problems"] == []
    # The credit note is a credit line of its own: gross totals 16,500.50 + 100.00 each side.
    assert (preview["total_debit"], preview["total_credit"]) == ("16600.50", "16600.50")
    assert not JournalEntry.objects.filter(source="IMPORT").exists()
    done = opening(books, commit=True)
    assert done["committed"] is True
    entry = JournalEntry.objects.get(id=done["entry_id"])
    assert (entry.status, entry.source) == ("DRAFT", "IMPORT")
    assert entry.description == "Opening balances at 01/01/2026 (imported)"
    lines = {(ln.account.code, ln.reference): ln for ln in entry.lines.select_related("account")}
    assert lines[("1200", "INV-0017")].due_date == date(2026, 1, 14)  # 15/12 + 30 days
    assert lines[("1200", "CN-0003")].credit == Decimal("100.00")
    assert lines[("2120", "")].vat_code_id == "CY:SETTLE:open"
    # Approved and posted as usual: the trial balance equals the source to the cent.
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    assert act(books, done["entry_id"], "post").status_code == 200
    tb = books["client"].get(f"{books['base']}/reports/trial-balance",
                             {"as_of": "2026-01-01"}).json()  # fmt: skip
    rows = {r["code"]: (r["debit"], r["credit"]) for r in tb["rows"]}
    assert rows == {"1300": ("12500.00", "0.00"), "1200": ("4000.50", "0.00"),
                    "2100": ("0.00", "1000.00"), "2120": ("0.00", "600.00"),
                    "3000": ("0.00", "14900.50")}  # fmt: skip
    # Each invoice is an open item of its customer or supplier, with its due date.
    items = books["client"].get(f"{books['base']}/open-items",
                                {"as_of": "2026-01-01", "side": "RECEIVABLE"}).json()  # fmt: skip
    assert sorted((i["reference"], i["kind"], i["open_amount"], i["due_date"]) for i in items) == [
        ("CN-0003", "PAYMENT", "100.00", "2026-01-27"),  # a credit line: payment or credit note
        ("INV-0017", "INVOICE", "3400.50", "2026-01-14"),
        ("INV-0018", "INVOICE", "700.00", "2026-01-19"),
    ]
    # Imported once: a second opening import is refused.
    again = opening(books)
    assert any("already imported" in m for m in messages(again))
    # The invoices are now in the books: listing them again is refused too.
    assert any("INV-0017 of C-001 is already in the books" in m for m in messages(again))


@pytest.mark.django_db
def test_opening_refusals_name_the_row_and_the_reason(books: dict[str, Any]) -> None:
    send(books, "counterparties", {"file": ("p.csv", PARTIES)}, commit=True)
    unbalanced = table(["Account", "Balance"], ["1300", "100.00"], ["3000", "-90.00"],
                       ["9998", "5"], ["6100", "12,5x"])  # fmt: skip
    found = opening(books, unbalanced, None, account_map="{}")
    assert messages(found) == [
        "0::The trial balance does not balance: debits 100.00, credits 90.00, difference 10.00.",
        "4:Account:9998 is not in the chart: map it to an account, or import the chart first.",
        "5:Balance:'12,5x' is not an amount this import can read unambiguously; write it as "
        "1250.00 or 1.250,00.",
    ]
    items = table(["Account code", "Customer or supplier code", "Invoice number",
                   "Amount outstanding"],
                  ["1200", "C-001", "INV-1", "100.00"], ["1200", "C-001", "inv-1", "50.00"],
                  ["1300", "C-404", "", ""])  # fmt: skip
    tb = table(["Account code", "Debit", "Credit"], ["1200", "100.00", ""], ["3000", "", "100"])
    found = opening(books, tb, items, account_map="{}")
    joined = "\n".join(messages(found))
    assert "3:Invoice number:Invoice inv-1 of C-001 is also on row 2." in joined
    assert "4:Account code:1300 is not a receivables or payables account of the chart." in joined
    assert "4:Customer or supplier code:C-404 is not set up" in joined
    assert "4:Invoice number:Enter the invoice number." in joined
    assert "4:Amount outstanding:Enter the amount outstanding." in joined
    assert len(found["problems"]) == 5
    assert not JournalEntry.objects.exists()
    # A control account without its invoices; no fiscal year at that date.
    found = opening(books, tb, None, account_map="{}", as_of="2030-01-01")
    joined = "\n".join(messages(found))
    assert "No fiscal year contains 01/01/2030" in joined
    assert "no open invoices are listed for it" in joined


@pytest.mark.django_db
def test_opening_balances_from_a_workbook_with_a_signed_balance(books: dict[str, Any]) -> None:
    data = workbook(["Opening balances (Demo)"], [], ["Code", "Name", "Balance"],
                    ["1300", "Bank", 2500.1], ["6100", "Rent", "100"], ["3000", "Capital", -2600.1],
                    ["1350", "Formula", "=1+1"])  # fmt: skip
    found = opening(books, data, None, account_map="{}")
    assert messages(found) == ["7:Balance:Formulas are not accepted; enter the value."]
    data = workbook(["Code", "Name", "Balance"], ["1300", "Bank", 2500.1], ["6100", "Rent", "100"],
                    ["3000", "Capital", -2600.1])  # fmt: skip
    found = opening(books, data, None, account_map="{}", commit=True)
    assert found["committed"] is True
    assert found["warnings"]
    assert "Income and expense accounts" in found["warnings"][0]
