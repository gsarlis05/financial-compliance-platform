"""The CFO dashboard (M4-8, AC-DB3 to AC-DB5): widgets equal the reports they come from, presets
and comparisons apply to every widget, layouts per user with a workspace default, permission-aware
widgets, and the response time on a 3-year fixture."""

import time
from decimal import Decimal
from typing import Any

import pytest

from fcp.core.errors import NotFoundError, PermissionDeniedError
from fcp.modules.dashboards.overview import _guard

from ..goals.test_goals import budget, evaluate, g, goal
from ..kpi.test_kpis import _post, k
from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
__all__ = ["books", "g", "k"]


def board(g: dict[str, Any], client: Any = None, **query: str) -> dict[str, Any]:
    q = {"preset": "YTD", "month": "2026-03-01", "comparison": "BUDGET", **query}
    got = (client or g["client"]).get(
        f"{g['base']}/dashboard?" + "&".join(f"{a}={b}" for a, b in q.items())
    )
    assert got.status_code == 200, got.content
    out: dict[str, Any] = got.json()
    return out


def widget(body: dict[str, Any], kind: str) -> dict[str, Any]:
    return next(w for w in body["widgets"] if w["type"] == kind)


def test_widgets_equal_the_reports(g: dict[str, Any]) -> None:
    budget(g)
    made = goal(g, "Revenue 12k", "REVENUE", "ABSOLUTE", "12000")
    evaluate(g, made["id"])
    body = board(g)
    assert body["period"] == {"preset": "YTD", "month": "2026-03-01", "date_from": "2026-01-01",
                              "date_to": "2026-03-31", "fiscal_year_start": "2026-01-01",
                              "comparison": "BUDGET"}  # fmt: skip
    assert body["layout_source"] == "BUILT_IN"
    assert [w["type"] for w in body["widgets"]] == [
        "kpis", "cash", "budget", "top_variances", "goals", "alerts"]  # fmt: skip
    kpis = widget(body, "kpis")
    assert (kpis["status"], kpis["reason"]) == ("empty", "No KPI set for this period yet.")
    assert widget(body, "cash")["status"] == "empty"

    # Budget vs actual is the variance report, line for line.
    data = widget(body, "budget")["data"]
    report = (
        g["client"]
        .get(
            f"{g['base']}/budget-versions/{data['version_id']}/variance"
            "?month=2026-03-01&view=YTD&comparison=ACTUAL_VS_BUDGET"
        )
        .json()
    )
    assert [(r["line"], r["actual"], r["comparison"], r["variance"], r["percent"])
            for r in data["rows"]] == [
        (r["taxonomy_code"], r["subject"], r["comparison"], r["variance"], r["percent"])
        for r in report["rows"]]  # fmt: skip
    top = widget(body, "top_variances")["data"]["top"]
    assert [(t["line"], t["variance"]) for t in top] == [("REV.SALES", "-2000.00")]

    goals = widget(body, "goals")["data"]["goals"]
    assert [(x["name"], x["status"], x["projected"]) for x in goals] == [
        ("Revenue 12k", "OFF_TRACK", "10000")]  # fmt: skip
    alerts = widget(body, "alerts")["data"]
    assert (alerts["critical"], alerts["latest"][0]["title"]) == (
        1,
        "Goal Revenue 12k is off track",
    )

    # Refresh calculates the KPI set; the cards equal the KPI report.
    done = g["client"].post_json(f"{g['base']}/dashboard/refresh",
                                 {"preset": "YTD", "month": "2026-03-01"})  # fmt: skip
    assert done.json() == {"kpi_sets": 1, "alerts_raised": 1}, done.content  # sales YTD
    cards = {c["key"]: c for c in widget(board(g), "kpis")["data"]["cards"]}
    latest = g["client"].get(f"{g['base']}/kpi-sets/latest?date_from=2026-01-01&date_to=2026-03-31")
    report_values = {v["key"]: v["value"] for v in latest.json()["values"]}
    assert set(cards) == {"GROSS_MARGIN", "EBITDA_MARGIN", "CURRENT_RATIO", "DSO", "CASH_RUNWAY",
                          "REVENUE_GROWTH"}  # fmt: skip
    for key, card in cards.items():
        if card["value"] is None:
            assert report_values[key] is None
        else:
            assert Decimal(card["value"]) == Decimal(report_values[key]), key
    assert Decimal(cards["GROSS_MARGIN"]["value"]) == Decimal("0.4")
    assert cards["GROSS_MARGIN"]["nature"] == "ACTUAL"


def test_presets_and_prior_year_comparison(g: dict[str, Any]) -> None:
    budget(g)
    assert board(g, preset="QTD", month="2026-05-15")["period"]["date_from"] == "2026-04-01"
    assert board(g, preset="MONTH", month="2026-05-15")["period"]["date_from"] == "2026-05-01"
    q = {"preset": "QTD", "month": "2026-03-01", "comparison": "PRIOR_YEAR"}
    done = g["client"].post_json(f"{g['base']}/dashboard/refresh", q)
    assert done.json()["kpi_sets"] == 2
    body = board(g, **q)
    rows = {r["line"]: r for r in widget(body, "budget")["data"]["rows"]}
    assert (rows["REV.SALES"]["actual"], rows["REV.SALES"]["comparison"]) == ("1000.00", "800.00")
    assert rows["REV.SALES"]["comparison_nature"] == "ACTUAL"
    margin = next(c for c in widget(body, "kpis")["data"]["cards"] if c["key"] == "GROSS_MARGIN")
    assert Decimal(margin["comparison_value"]) == 1  # Q1 2025: revenue 800, no cost of sales


def test_layouts_per_user_with_a_workspace_default(
    g: dict[str, Any], make_user: Any, api_client: Any
) -> None:
    url = f"{g['base']}/dashboard-layout"
    other = join(g["client"], g["ws"]["slug"], make_user("acc@example.test"), api_client,
                 "accountant")  # fmt: skip
    assert g["client"].get(url).json()["source"] == "BUILT_IN"
    mine = [{"type": "goals"}, {"type": "kpis", "kpis": ["DSO", "CURRENT_RATIO"]}]
    saved = g["client"].put_json(url, {"widgets": mine})
    assert saved.json() == {"widgets": mine, "source": "USER"}, saved.content
    body = board(g)
    assert [(w["type"], w["options"]) for w in body["widgets"]] == [
        ("goals", {}), ("kpis", {"kpis": ["DSO", "CURRENT_RATIO"]})]  # fmt: skip
    default = [{"type": "alerts"}, {"type": "cash"}]
    assert other.put_json(f"{url}/default", {"widgets": default}).status_code == 403
    assert g["client"].put_json(f"{url}/default", {"widgets": default}).status_code == 200
    assert other.get(url).json() == {"widgets": default, "source": "WORKSPACE"}
    assert board(g, other)["layout_source"] == "WORKSPACE"
    for bad in (
        [],
        [{"type": "nope"}],
        [{"type": "cash"}, {"type": "cash"}],
        [{"type": "kpis", "kpis": ["x"] * 9}],
        [{"type": "kpis", "kpis": ["bad key"]}],
    ):
        assert g["client"].put_json(url, {"widgets": bad}).status_code == 422, bad
    reset = g["client"].delete_json(url)
    assert reset.status_code == 200, reset.content
    assert reset.json()["source"] == "WORKSPACE"


def test_a_widget_without_permission_or_data_says_why() -> None:
    def denied() -> dict[str, Any]:
        raise PermissionDeniedError("no")

    def missing() -> dict[str, Any]:
        raise NotFoundError("No cash forecast yet: run one first.")

    assert (_guard(denied, "").status, _guard(denied, "").reason) == (
        "denied", "You do not have permission to see this.")  # fmt: skip
    assert (_guard(missing, "").status, _guard(missing, "").reason) == (
        "empty", "No cash forecast yet: run one first.")  # fmt: skip


def test_response_time_on_a_three_year_fixture(g: dict[str, Any]) -> None:
    """AC-DB5: p95 below 1.5 s for the dashboard request on 3 years of monthly activity."""
    c, base = g["client"], g["base"]
    for year in (2024, 2025, 2026):
        if year != 2026:
            c.post_json(f"{base}/fiscal-years", {"start_date": f"{year}-01-01"})
    for year in (2024, 2025, 2026):
        for month in range(1, 13):
            day = f"{year}-{month:02d}-2"
            _post(g, day + "0", ("1200", "900", "0", "C1"), ("4000", "0", "900", None))
            _post(g, day + "1", ("5000", "500", "0", None), ("2100", "0", "500", "S1"))
            _post(g, day + "2", ("6100", "120", "0", None), ("1300", "0", "120", None))
            _post(g, day + "5", ("1300", "800", "0", None), ("1200", "0", "800", "C1"))
    budget(g)
    q = {"preset": "YTD", "month": "2026-12-01"}
    c.post_json(f"{base}/dashboard/refresh", q)
    timings = []
    for _ in range(10):
        started = time.perf_counter()
        body = board(g, **q)
        timings.append(time.perf_counter() - started)
        assert widget(body, "kpis")["status"] == "ok"
    p95 = sorted(timings)[int(len(timings) * 0.95) - 1]
    assert p95 < 1.5, timings
