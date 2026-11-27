"""Dashboard v2 (M8-4, AC-DB2): arranged layouts (order and width), the waterfall and scenario
widgets, the last-twelve-months preset, saved views, and the response time with every widget.

The waterfall, by hand, on the goals fixture to the end of March 2026 (year to date): budgeted
result 3,000 sales - 1,800 cost of sales - 300 rent - 150 depreciation = 750; actual result
1,000 - 600 - 100 - 50 = 250. Steps: sales -2,000; cost of sales +1,200; rent +200; depreciation
+100. 750 - 2,000 + 1,200 + 200 + 100 = 250."""

import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from ..goals.test_goals import budget, g
from ..kpi.test_kpis import k
from ..ledger.conftest import books, join
from ..scenarios.test_runs_api import plan, scenario
from .test_dashboard import board, widget

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "g", "k", "plan"]


def arrange(g: dict[str, Any], widgets: list[dict[str, Any]], client: Any = None) -> Any:
    return (client or g["client"]).put_json(f"{g['base']}/dashboard-layout", {"widgets": widgets})


def test_waterfall_from_budget_to_actual(g: dict[str, Any]) -> None:
    budget(g)
    mine = [{"type": "waterfall"}, {"type": "budget", "width": "half"},
            {"type": "goals", "width": "half"}]  # fmt: skip
    saved = arrange(g, mine)
    assert saved.json()["widgets"] == mine, saved.content
    body = board(g)
    assert [(w["type"], w["options"]) for w in body["widgets"]] == [
        ("waterfall", {}), ("budget", {"width": "half"}), ("goals", {"width": "half"})]  # fmt: skip
    data = widget(body, "waterfall")["data"]
    assert (data["start"], data["start_nature"], data["end"], data["end_nature"]) == (
        "750.00", "BUDGET", "250.00", "ACTUAL")  # fmt: skip
    assert [(s["line"], s["value"]) for s in data["steps"]] == [
        ("REV.SALES", "-2000.00"), ("COGS", "1200.00"), ("OPEX.RENT", "200.00"),
        ("DA.DEPRECIATION", "100.00")]  # fmt: skip
    total = Decimal(data["start"]) + sum(Decimal(s["value"]) for s in data["steps"])
    assert total == Decimal(data["end"])
    # Only the widgets in the layout are built.
    assert {w["type"] for w in body["widgets"]} == {"waterfall", "budget", "goals"}
    for bad in ([{"type": "cash", "width": "wide"}], [{"type": "scenario"}],
                [{"type": "scenario", "scenario_id": "not-a-uuid"}]):  # fmt: skip
        assert arrange(g, bad).status_code == 422, bad


def test_last_twelve_months(g: dict[str, Any]) -> None:
    budget(g)
    arrange(g, [{"type": "budget"}, {"type": "waterfall"}, {"type": "kpis"}])
    body = board(g, preset="LTM")
    assert (body["period"]["date_from"], body["period"]["date_to"]) == ("2025-04-01",
                                                                        "2026-03-31")  # fmt: skip
    for kind in ("budget", "waterfall"):
        w = widget(body, kind)
        assert (w["status"], w["reason"]) == ("empty", (
            "Budgets follow the fiscal year: choose the month, quarter to date or year to date "
            "to compare with the budget."))  # fmt: skip
    assert widget(body, "kpis")["reason"] == "No KPI set for this period yet."


def test_scenario_widget(plan: dict[str, Any], make_user: Make, api_client: Make) -> None:
    """A shared scenario against its base: the same totals as its comparison, hypothetical."""
    surl = scenario(plan, ("PCT_CHANGE", {"driver": "revenue", "percent": "50"}))
    sid = surl.rsplit("/", 1)[1]
    arrange(plan, [{"type": "scenario", "scenario_id": sid, "width": "half"}])
    draft = widget(board(plan, month="2027-01-01"), "scenario")
    assert (draft["status"], draft["reason"]) == (
        "empty",
        "Choose a shared scenario for this widget.",
    )
    plan["client"].post_json(f"{surl}/share", {})
    data = widget(board(plan, month="2027-01-01"), "scenario")["data"]
    compared = plan["client"].get(f"{surl}/comparison").json()
    assert data["changes"] == compared["effects"][-1]["changes"]
    assert (data["nature"], data["engine_status"]) == (
        "HYPOTHETICAL",
        "OWNER_CHECKED",
    )
    assert data["changes"]["PL.REVENUE"] == "6000.00"  # 12 x 1,000 x 50%
    viewer = join(plan["client"], plan["ws"]["slug"], make_user("viewer@example.test"),
                  api_client, "read_only")  # fmt: skip
    arrange(plan, [{"type": "scenario", "scenario_id": sid}], viewer)
    seen = widget(board(plan, viewer, month="2027-01-01"), "scenario")
    assert seen["status"] == "denied"  # running a scenario needs planning.run


def test_saved_views(g: dict[str, Any], make_user: Make, api_client: Make) -> None:
    c, url = g["client"], f"{g['base']}/dashboard-views"
    made = c.put_json(url, {"name": "Board", "preset": "QTD", "comparison": "PRIOR_YEAR"})
    assert made.status_code == 200, made.content
    c.put_json(url, {"name": "Monthly", "preset": "MONTH", "comparison": "BUDGET"})
    c.put_json(url, {"name": "Board", "preset": "LTM", "comparison": "PRIOR_YEAR"})  # replaces
    listed = c.get(url).json()
    assert [(v["name"], v["preset"]) for v in listed] == [("Board", "LTM"), ("Monthly", "MONTH")]
    other = join(c, g["ws"]["slug"], make_user("acc@example.test"), api_client, "accountant")
    assert other.get(url).json() == []  # views are personal
    assert other.delete_json(f"{url}/{listed[0]['id']}").status_code == 404
    assert c.delete_json(f"{url}/{listed[0]['id']}").status_code == 204
    for n in range(19):
        c.put_json(url, {"name": f"V{n}", "preset": "YTD", "comparison": "BUDGET"})
    refused = c.put_json(url, {"name": "One too many", "preset": "YTD", "comparison": "BUDGET"})
    assert refused.status_code == 422
    assert c.put_json(url, {"name": "x", "preset": "WEEK", "comparison": "BUDGET"}
                      ).status_code == 422  # fmt: skip


def test_response_time_with_every_widget(g: dict[str, Any]) -> None:
    """AC-DB2: first load p95 below 1.5 s with all the widgets except the scenario (measured
    separately by the scenario tests: one engine run, well under the limit)."""
    budget(g)
    arrange(g, [{"type": t} for t in ("kpis", "cash", "budget", "top_variances", "goals",
                                      "alerts", "waterfall")])  # fmt: skip
    g["client"].post_json(
        f"{g['base']}/dashboard/refresh", {"preset": "YTD", "month": "2026-03-01"}
    )
    timings = []
    for _ in range(10):
        started = time.perf_counter()
        body = board(g)
        timings.append(time.perf_counter() - started)
        assert widget(body, "waterfall")["status"] == "ok"
    p95 = sorted(timings)[int(len(timings) * 0.95) - 1]
    assert p95 < 1.5, timings
