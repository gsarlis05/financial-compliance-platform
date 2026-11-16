"""AC-G5: the sample dataset loads and the demo script runs end to end through the API."""

import json
import os
from decimal import Decimal
from pathlib import Path
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
@pytest.mark.usefixtures("reference_data", "document_bucket")
def test_demo_walkthrough_runs_end_to_end() -> None:
    viewer = User.objects.create(idp_subject="https://idp.test|viewer", email="viewer@example.test")
    said: list[str] = []
    result = run(share_with="Viewer@Example.test", say=said.append)

    assert result.integrity_status == "PASSED"
    assert result.locked_periods == 11
    books = build_demo_books()
    assert result.entries_posted == len(books.entries) + 3
    assert Decimal(result.bank_balance) == books.bank_closing_balance - Decimal("350.00")
    assert len(result.steps) == 26
    budget_step = next(s for s in result.steps if s.startswith("budget "))
    assert "approved by the owner: total 738000.00" in budget_step
    assert "sales 600000.00 phased like" in budget_step
    goals_step = next(s for s in result.steps if "sample goals" in s)
    assert goals_step.startswith("6 sample goals for 2027 set with frozen 2026 baselines")
    assert "Revenue 500k ON_TRACK" in goals_step, goals_step
    alerts_step = next(s for s in result.steps if "in-app alert" in s)
    assert alerts_step.startswith("1 in-app alert(s) raised"), alerts_step
    assert "Goal DSO 30 days is off track" in alerts_step
    board_step = next(s for s in result.steps if s.startswith("CFO dashboard"))
    assert "kpis ok, cash ok" in board_step, board_step
    assert board_step.endswith("6 KPI cards"), board_step
    # 6,500 + 12,000 + 2,500 - 640 - 380.25 - 95.40 + 310,000 (valuation) - 142,000 = 187,884.35
    assert (
        "personal workspace (separate books): net worth 187884.35 on 2026-01-31, including a "
        "home valuation (estimate)"
    ) in result.steps, result.steps
    assert any(s.startswith("personal budget (groceries 400 a month) and 2 goals: Emergency fund")
               for s in result.steps), result.steps  # fmt: skip
    assert (
        "counterpart hint (opt-in): 1 business payment to the owner suggested, 1500.00 recorded "
        "in the personal books only after confirmation"
    ) in result.steps, result.steps
    assert any(s.startswith("client portfolio refused in a business workspace")
               for s in result.steps), result.steps  # fmt: skip
    assert all(line.startswith("✔") for line in said)
    _assert_golden_statements(result.statements)

    # The shared user sees the workspace through the API, with the granted role.
    client = DemoClient(viewer, "testserver")
    slugs = [w["slug"] for w in client.call("GET", "/api/workspaces")]
    assert result.slug in slugs
    base = f"/api/w/{result.slug}/entities/{result.entity_id}"
    forecast_run = client.call("GET", f"{base}/calc-runs/{result.forecast['run_id']}")
    _assert_golden_forecast(result.forecast, forecast_run["input_refs"])
    entries: list[dict[str, Any]] = client.call("GET", f"{base}/journal-entries?limit=500")
    statuses = {e["status"] for e in entries}
    assert statuses == {"POSTED", "VOID"}
    reversed_ = [e for e in entries if e["entry_type"] == "REVERSAL"]
    assert len(reversed_) == 1
    assert reversed_[0]["reverses_entry_id"]


GOLDEN = Path(__file__).parent / "golden" / "demo_statements_2026.json"


def _assert_golden_statements(statements: dict[str, Any]) -> None:
    """AC-M2-8: Demo Trading's statements match the reviewed golden file (rows and checks).
    Regenerate with ``UPDATE_GOLDEN=1`` only after reviewing the change."""
    compact = {
        key: {
            "rows": [[r["kind"], r["code"], r["current"]] for r in statements[key]["rows"]],
            "checks": {c["code"]: c["values"] for c in statements[key]["checks"]},
        }
        for key in ("profit_and_loss", "balance_sheet", "cash_flow")
    }
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(compact, indent=1) + "\n", encoding="utf-8")
    assert compact == json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("reference_data", "document_bucket")
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


GOLDEN_FORECAST = Path(__file__).parent / "golden" / "demo_cash_13w.json"


def _assert_golden_forecast(forecast: dict[str, Any], refs: dict[str, Any]) -> None:
    """AC-CW5 (pending sign-off): the 13-week forecast for Demo Trading.

    1. Independently of the engine, recompute each week's closing from the run's stored inputs
       with the plain reference calculation (tests/cashflow/test_engine.py).
    2. Compare with the reviewed golden file. It is marked ``signed_off: false`` until a finance
       professional has checked it (brief §3); regenerate with ``UPDATE_GOLDEN=1`` only after
       reviewing the change.
    """
    from datetime import date  # noqa: PLC0415

    from ..cashflow.test_engine import reference  # noqa: PLC0415

    closings, shortfall = reference(
        Decimal(forecast["opening_cash"]),
        refs["flows"],
        date.fromisoformat(forecast["as_of"]),
        Decimal(refs["minimum_cash"]),
    )
    assert [Decimal(w["closing"]) for w in forecast["weeks"]] == closings
    first = forecast["first_shortfall"]
    assert (
        None if first is None else (date.fromisoformat(first["date"]), Decimal(first["balance"]))
    ) == shortfall
    compact = {
        "signed_off": False,
        "note": "Computed by the engine and cross-checked against the independent reference; "
        "not yet signed off by a finance professional.",
        "as_of": forecast["as_of"],
        "opening_cash": forecast["opening_cash"],
        "weeks": [
            [w["label"], w["opening"], w["inflows"], w["outflows"], w["closing"], w["shortfall"]]
            for w in forecast["weeks"]
        ],
        "first_shortfall": forecast["first_shortfall"],
        "overdue": forecast["overdue"],
        "warnings": sorted(w["code"] for w in forecast["warnings"]),
    }
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_FORECAST.write_text(json.dumps(compact, indent=1) + "\n", encoding="utf-8")
    assert compact == json.loads(GOLDEN_FORECAST.read_text(encoding="utf-8"))
