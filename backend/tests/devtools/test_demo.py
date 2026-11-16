"""AC-G5: the sample dataset loads and the demo script runs end to end through the API."""

from decimal import Decimal
from typing import Any

import pytest

from fcp.devtools.demo import __main__ as demo_cli
from fcp.devtools.demo.books import DemoEntry, build_demo_books
from fcp.devtools.demo.walkthrough import DemoClient, DemoStepError, run
from fcp.modules.identity.models import User


def test_demo_books_are_balanced_deterministic_and_complete() -> None:
    books = build_demo_books(seed=42)
    again = build_demo_books(seed=42)
    assert books.fingerprint == again.fingerprint
    assert books.company == "Demo Trading Ltd (Demo)"
    assert all(e.is_balanced() for e in books.entries)
    assert all(e.accounting_date.year == 2026 for e in books.entries)
    # Every bank movement is booked: the bank account ends at the statement's closing balance.
    bank = sum((dr - cr for e in books.entries for code, dr, cr in e.netted() if code == "1300"),
               Decimal(0))  # fmt: skip
    assert bank == books.bank_closing_balance
    assert build_demo_books(seed=7).fingerprint != books.fingerprint


def test_demo_entry_nets_each_account_to_one_side() -> None:
    entry = DemoEntry(build_demo_books().fiscal_year_start, "x")
    entry.add("1300", debit=Decimal("10.00"))
    entry.add("1300", credit=Decimal("4.00"))
    entry.signed("4000", Decimal("-6.00"))
    entry.signed("9999", Decimal("0"))
    assert entry.netted() == [("1300", Decimal("6.00"), Decimal(0)),
                              ("4000", Decimal(0), Decimal("6.00"))]  # fmt: skip
    assert entry.is_balanced()


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data")
def test_demo_walkthrough_runs_end_to_end() -> None:
    viewer = User.objects.create(idp_subject="https://idp.test|viewer", email="viewer@example.test")
    said: list[str] = []
    result = run(share_with="Viewer@Example.test", say=said.append)

    assert result.integrity_status == "PASSED"
    assert result.locked_periods == 11
    books = build_demo_books()
    assert result.entries_posted == len(books.entries) + 3
    assert Decimal(result.bank_balance) == books.bank_closing_balance - Decimal("350.00")
    assert len(result.steps) == 12
    assert all(line.startswith("✔") for line in said)

    # The shared user sees the workspace through the API, with the granted role.
    client = DemoClient(viewer, "testserver")
    slugs = [w["slug"] for w in client.call("GET", "/api/workspaces")]
    assert result.slug in slugs
    base = f"/api/w/{result.slug}/entities/{result.entity_id}"
    entries: list[dict[str, Any]] = client.call("GET", f"{base}/journal-entries?limit=500")
    statuses = {e["status"] for e in entries}
    assert statuses == {"POSTED", "VOID"}
    reversed_ = [e for e in entries if e["entry_type"] == "REVERSAL"]
    assert len(reversed_) == 1
    assert reversed_[0]["reverses_entry_id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data")
def test_demo_share_with_unknown_user_is_reported_not_fatal() -> None:
    said: list[str] = []
    result = run(share_with="nobody@example.test", say=said.append)
    assert any("no user with email nobody@example.test" in line for line in said)
    assert result.integrity_status == "PASSED"


@pytest.mark.django_db
def test_demo_client_reports_unexpected_status() -> None:
    user = User.objects.create(idp_subject="https://idp.test|x", email="x@example.test")
    with pytest.raises(DemoStepError, match="returned 404"):
        DemoClient(user, "testserver").call("GET", "/api/w/missing")


def test_demo_cli_refuses_without_debug(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo_cli.main([]) == 2
    assert "only allowed with DEBUG" in capsys.readouterr().err
