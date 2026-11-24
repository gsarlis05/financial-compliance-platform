"""Personal budget, goals and 12-month projection (M5-2). Dates are relative to today, so the
figures below hold on any day.

Fixture: opening balances on the 1st of the month 4 months ago (current account 3,000, savings
1,000, credit card owed 1,200). In each of the last 3 complete months, on the 15th: salary 2,000
in; groceries 400 and rent 800 spent; 300 moved to savings and 200 paid off the card. Today:
current account 3,900, savings 1,900, card 600 owed.
"""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.personal.models import PersonalGoal

from .test_personal import home, tx

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["home"]


def month(k: int) -> date:
    return add_months(month_start(timezone.localdate()), k)


@pytest.fixture
def plan(home: dict[str, Any]) -> dict[str, Any]:
    h, c = home, home["client"]
    for code, amount in (("1100", "3000.00"), ("1110", "1000.00"), ("2100", "1200.00")):
        made = c.post_json(f"{h['p']}/opening-balances",
                           {"account_id": h["a"][code]["id"], "date": month(-4).isoformat(),
                            "amount": amount})  # fmt: skip
        assert made.status_code == 201, made.content
    for k in (-3, -2, -1):
        day = (month(k) + timedelta(days=14)).isoformat()
        for kind, amount, text, account, other in (
            ("RECEIVED", "2000.00", "Salary", "1100", "4000"),
            ("SPENT", "400.00", "Groceries", "1100", "6100"),
            ("SPENT", "800.00", "Rent", "1100", "6000"),
            ("MOVED", "300.00", "Saving", "1100", "1110"),
            ("MOVED", "200.00", "Card", "1100", "2100"),
        ):
            assert tx(h, kind, day, amount, text, account, other).status_code == 201
    return h


def goal(h: dict[str, Any], **body: Any) -> dict[str, Any]:
    made = h["client"].post_json(f"{h['p']}/goals", body)
    assert made.status_code == 201, made.content
    out: dict[str, Any] = made.json()
    return out


def test_goals_savings_emergency_fund_and_debt(plan: dict[str, Any]) -> None:
    h = plan
    target_date = month_end(month(5)).isoformat()  # 5 months left
    savings = goal(h, kind="SAVINGS", name="Holiday fund", account_ids=[h["a"]["1110"]["id"]],
                   target_amount="3000.00", target_date=target_date)  # fmt: skip
    assert (savings["current"], savings["months_left"], savings["needed_per_month"],
            savings["pace_per_month"], savings["projected"], savings["status"]) == (
        "1900.00", 5, "220.00", "300.00", "3400.00", "ON_TRACK")  # fmt: skip
    fund = goal(h, kind="EMERGENCY_FUND", name="Three months", months=3,
                account_ids=[h["a"]["1110"]["id"]], target_date=target_date)  # fmt: skip
    # Spending averaged 1,200 a month: 3 months is 3,600; 3,400 projected misses by more than 5%.
    assert (fund["average_spending"], fund["target"], fund["status"]) == (
        "1200.00", "3600.00", "OFF_TRACK")  # fmt: skip
    debt = goal(h, kind="DEBT_PAYOFF", name="Clear the card", account_ids=[h["a"]["2100"]["id"]],
                target_date=target_date)  # fmt: skip
    assert (debt["current"], debt["pace_per_month"], debt["needed_per_month"], debt["projected"],
            debt["status"]) == ("600.00", "200.00", "120.00", "0.00", "ON_TRACK")  # fmt: skip

    listed = h["client"].get(f"{h['p']}/goals").json()
    assert [g["name"] for g in listed] == ["Clear the card", "Holiday fund", "Three months"]
    retired = h["client"].post_json(f"{h['p']}/goals/{fund['id']}/retire", {})
    assert retired.json()["retired_at"] is not None
    assert h["client"].post_json(f"{h['p']}/goals/{fund['id']}/retire", {}).status_code == 409
    assert len(h["client"].get(f"{h['p']}/goals").json()) == 2
    assert len(h["client"].get(f"{h['p']}/goals?include_retired=true").json()) == 3
    with transaction.atomic():
        set_context(tenant_id=h["ws"]["id"])
        with pytest.raises(DatabaseError, match="only be retired"), transaction.atomic():
            PersonalGoal.objects.filter(id=savings["id"]).update(target_amount=Decimal(1))
        with pytest.raises(DatabaseError, match="kept"), transaction.atomic():
            PersonalGoal.objects.filter(id=savings["id"]).delete()


def test_goal_validation(plan: dict[str, Any]) -> None:
    h, later = plan, month_end(month(5)).isoformat()
    for body, field in (
        ({"kind": "SAVINGS", "account_ids": [h["a"]["1110"]["id"]], "target_amount": "0",
          "target_date": later}, "target_amount"),
        ({"kind": "SAVINGS", "account_ids": [h["a"]["1110"]["id"]], "target_amount": "10",
          "target_date": month(-1).isoformat()}, "target_date"),
        ({"kind": "DEBT_PAYOFF", "account_ids": [h["a"]["1110"]["id"]], "target_date": later},
         "account_ids"),
        ({"kind": "EMERGENCY_FUND", "account_ids": [h["a"]["1110"]["id"]], "months": 0,
          "target_date": later}, "months"),
    ):  # fmt: skip
        refused = h["client"].post_json(f"{h['p']}/goals", {"name": "x", **body})
        assert refused.status_code == 422, (body, refused.content)
        assert field in refused.json()["errors"], refused.json()


def test_budget_and_projection(plan: dict[str, Any]) -> None:
    h, c = plan, plan["client"]
    last = month(-1).isoformat()
    groceries = {"account_id": h["a"]["6100"]["id"], "from_month": last}
    set_ = c.put_json(f"{h['p']}/budget", {**groceries, "monthly_amount": "350.00"})
    assert set_.status_code == 200, set_.content
    lines = {x["name"]: x for x in set_.json()["lines"]}
    assert (lines["Groceries"]["budgeted"], lines["Groceries"]["actual"],
            lines["Groceries"]["remaining"], lines["Groceries"]["over"]) == (
        "350.00", "400.00", "-50.00", True)  # fmt: skip
    assert (lines["Housing"]["budgeted"], lines["Housing"]["actual"]) == ("0.00", "800.00")
    assert (lines["Salary"]["actual"], lines["Salary"]["over"]) == ("2000.00", False)
    # A correction for the same month supersedes the earlier amount.
    again = c.put_json(f"{h['p']}/budget", {**groceries, "monthly_amount": "450.00"})
    assert {x["name"]: x for x in again.json()["lines"]}["Groceries"]["over"] is False

    # Cash today: 3,900 + 1,900. Each month: salary 2,000 (average) - groceries 450 (budget)
    # - rent 800 (average) = +750.
    p = c.get(f"{h['p']}/projection").json()
    assert p["opening_cash"] == "5800.00"
    first = p["months"][0]
    assert (first["month"], first["income"], first["spending"], first["closing_cash"],
            first["nature"]) == (month(1).isoformat(), "2000.00", "1250.00", "6550.00",
                                 "FORECAST")  # fmt: skip
    assert p["months"][-1]["closing_cash"] == "14800.00"
    assert p["first_negative"] is None
    c.put_json(f"{h['p']}/budget", {"account_id": h["a"]["6900"]["id"],
                                    "monthly_amount": "7000.00",
                                    "from_month": month(2).isoformat()})  # fmt: skip
    tight = c.get(f"{h['p']}/projection").json()
    # Month 2: 6,550 + 2,000 - 8,250 = 300; month 3: 300 - 6,250, below zero.
    assert tight["first_negative"] == month(3).isoformat()
