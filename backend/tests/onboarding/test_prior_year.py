"""The prior year by month, kept as comparatives (R-4, #247; AC-R2, AC-R3). Synthetic files.

The books start on 1 January 2026 (fiscal year 2026). A monthly trial balance of October to
December 2025 becomes movements per month that budget variance, KPIs and statements read for
those months, without any entry; from 1 January 2026 the opening entry carries the balances."""

import io
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import transaction
from openpyxl import load_workbook

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger.models import JournalEntry
from fcp.modules.reporting import actuals
from fcp.modules.reporting.models import FactComparative

from ..ledger.conftest import books
from ..ledger.test_entries import act
from .test_imports import messages, send, table

__all__ = ["books"]
pytestmark = pytest.mark.django_db

HEAD: list[object] = ["Account code", "Account name", "2025-10", "2025-11", "2025-12"]
PRIOR = table(
    HEAD,
    ["1300", "Bank - current account", "9000.00", "9500.00", "12500.00"],
    ["3000", "Share capital", "-5000.00", "-5000.00", "-5000.00"],
    ["3200", "Retained earnings", "-2000.00", "-2000.00", "-2000.00"],
    ["4000", "Sales revenue", "-2500.00", "-3500.00", "-7000.00"],  # year to date
    ["6100", "Rent", "500.00", "1000.00", "1500.00"],
    ["Total", "", "0.00", "0.00", "0.00"],
)
OPENING_TB = table(["Account", "Balance"], ["1300", "12500.00"], ["3000", "-5000.00"],
                   ["3200", "-7500.00"])  # fmt: skip


def prior(b: dict[str, Any], data: bytes = PRIOR, commit: bool = False, **form: str) -> Any:
    return send(b, "prior-year", {"file": ("prior.csv", data)}, commit,
                **{"account_map": "{}", **form})  # fmt: skip


def monthly(b: dict[str, Any], start: str, end: str) -> dict[tuple[str, str], str]:
    got = b["client"].get(f"{b['base']}/actuals/monthly", {"date_from": start, "date_to": end})
    return {(f["account_code"], f["month"]): f["net_debit"] for f in got.json()["facts"]}


def balances(b: dict[str, Any], before: date) -> dict[str, Decimal]:
    codes = {a["id"]: a["code"] for a in b["accounts"].values()}
    with transaction.atomic():
        set_context(tenant_id=b["ws"]["id"])
        _, net = actuals.net_before(b["entity"]["id"], b["ws"]["id"], before=before)
        _, many, _ = actuals.net_before_many(b["entity"]["id"], b["ws"]["id"], cutoffs=[before])
    assert {k: v for k, v in many[before].items() if v} == {k: v for k, v in net.items() if v}
    return {codes[str(k)]: v for k, v in net.items() if v}


def test_the_template_lists_the_twelve_months_before_the_books(books: dict[str, Any]) -> None:
    got = books["client"].get(f"{books['base']}/imports/templates/prior-year")
    header = [c.value for c in load_workbook(io.BytesIO(got.content))["Import"][1]]
    assert header[:3] == ["Account code", "Account name", "Opening"]
    assert header[3:] == [f"2025-{m:02d}" for m in range(1, 13)]


def test_a_prior_year_becomes_comparatives_never_entries(books: dict[str, Any]) -> None:
    # Before the opening balances: the comparatives cannot be checked against them yet.
    early = prior(books)
    assert early["problems"] == []
    assert early["months"] == ["2025-10", "2025-11", "2025-12"]
    assert "No opening entry was imported yet" in early["warnings"][0]
    assert not FactComparative.objects.exists()
    opened = send(books, "opening-balances", {"file": ("tb.csv", OPENING_TB)}, True,
                  as_of="2026-01-01", account_map="{}")  # fmt: skip
    assert opened["committed"] is True
    done = prior(books, commit=True)
    assert (done["committed"], done["problems"], done["warnings"]) == (True, [], [])
    assert JournalEntry.objects.count() == 1  # the opening entry only
    # Movements per month: balance-sheet changes, and income and expense from year to date.
    facts = monthly(books, "2025-10-01", "2025-12-31")
    assert facts[("4000", "2025-10-01")] == "-2500.00"  # the year to October, as given
    assert facts[("4000", "2025-11-01")] == "-1000.00"
    assert facts[("4000", "2025-12-01")] == "-3500.00"
    assert facts[("1300", "2025-12-01")] == "3000.00"
    assert facts[("6100", "2025-11-01")] == "500.00"
    # Balances up to the books start come from the comparatives …
    assert balances(books, date(2025, 12, 1))["1300"] == Decimal("9500.00")
    assert balances(books, date(2026, 1, 1))["1300"] == Decimal("12500.00")
    # … and from then on from the ledger alone: the opening entry is not counted twice.
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    assert act(books, opened["entry_id"], "post").status_code == 200
    after = balances(books, date(2026, 2, 1))
    assert after == {"1300": Decimal("12500.00"), "3000": Decimal("-5000.00"),
                     "3200": Decimal("-7500.00")}  # fmt: skip
    assert monthly(books, "2026-01-01", "2026-01-31")[("1300", "2026-01-01")] == "12500.00"
    event = AuditEvent.objects.get(action="reporting.comparatives.replaced")
    assert event.changes["months"] == ["2025-10", "2025-11", "2025-12"]
    # Importing again replaces the set.
    assert prior(books, commit=True)["committed"] is True
    assert FactComparative.objects.filter(month="2025-11-01").count() == 3


def test_monthly_amounts_for_income_and_expense(books: dict[str, Any]) -> None:
    data = table(HEAD, ["1300", "Bank", "9000.00", "9500.00", "12500.00"],
                 ["3000", "Capital", "-5000.00", "-5000.00", "-5000.00"],
                 ["3200", "Retained", "-2000.00", "-2000.00", "-2000.00"],
                 ["4000", "Sales", "-2500.00", "-1000.00", "-3500.00"],
                 ["6100", "Rent", "500.00", "500.00", "500.00"])  # fmt: skip
    found = prior(books, data, commit=True, profit_and_loss="month")
    assert (found["committed"], found["problems"]) == (True, [])
    assert monthly(books, "2025-11-01", "2025-11-30")[("4000", "2025-11-01")] == "-1000.00"


def test_prior_year_refusals(books: dict[str, Any]) -> None:
    inside = table(["Account code", "2025-12", "2026-01"], ["1300", "1", "1"], ["3000", "-1", "-1"])
    assert messages(prior(books, inside)) == [
        "1:2026-01:2026-01 is inside the books (from 01/01/2026); the prior year is the months "
        "before."]  # fmt: skip
    gap = table(["Account code", "2025-10", "2025-12"], ["1300", "1", "1"], ["3000", "-1", "-1"])
    assert messages(prior(books, gap)) == [
        "1:2025-12:The months must follow one another: 2025-10 is followed by 2025-12."
    ]
    unbalanced = table(["Account code", "Nov 2025", "Dec 2025"], ["1300", "100", "150"],
                       ["3000", "-100", "-100"], ["OLD", "0", "x"])  # fmt: skip
    found = messages(prior(books, unbalanced))
    assert "1:Dec 2025:2025-12 does not balance: the movements differ by 50.00." in found
    assert "4:Dec 2025:'x' is not an amount this import can read unambiguously; write it as " \
           "1250.00 or 1.250,00." in found  # fmt: skip
    send(books, "opening-balances", {"file": ("tb.csv", OPENING_TB)}, True, as_of="2026-01-01",
         account_map="{}")  # fmt: skip
    disagree = table(["Account code", "2025-12"], ["1300", "12000.00"], ["3000", "-12000.00"])
    assert messages(prior(books, disagree)) == [
        "0:Account code:1300 Bank - current account: the last month ends at 12000.00 but the "
        "opening entry has 12500.00."]  # fmt: skip
    assert not FactComparative.objects.exists()
