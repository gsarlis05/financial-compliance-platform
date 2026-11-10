"""Goals on an independently computed reference fixture (M4-6: AC-GO1 to AC-GO3, AC-GO5).

Golden fixture (AC-GO2; professional sign-off pending, see docs/goals-golden.md). The KPI fixture
(tests/kpi/test_kpis.py) plus, in 2025, rent 1,200 (June) and sales 2,000 (September), both in
cash. The approved 2026 budget, per month: sales 1,000, cost of sales 600, rent 100,
depreciation 50. Evaluated as of 31 March 2026 (cut-over 31 March; 9 months remain).

By hand:
- 2025 (baselines): revenue 800 + 2,000 = 2,800; opex 1,200; EBITDA 1,600; net profit 1,600;
  cash on 1 January 2026: 1,000 - 200 + 800 - 1,200 + 2,000 = 2,400.
- Q1 2026 actuals: revenue 1,000; cost of sales 600; rent 100; depreciation 50; interest 10;
  tax 40. Cash at month ends: January 2,400; February 2,300; March 3,090.
- Likely outcome (Q1 actuals, then the budget for April to December): revenue 10,000; cost of
  sales 6,000; opex 1,000; depreciation 500; EBITDA 3,000 (margin 30%); net profit 2,450.
  Receivables are held at 500 (opening 0): DSO = 250 / 10,000 x 365 = 9.125 days.

The six goals:
1. Revenue 12,000: gap 2,000 > 5% of 12,000, off track. Remaining 11,000 = 1,222.22 a month,
   against 1,000 projected and 333.33 historical. Against the budget (12,000) the whole -2,000 is
   sales; residual 0.
2. EBITDA margin 35%: 30% projected, off track. Numerator needed 3,500 (revenue 10,000 held);
   revenue needed 3,000 / 0.35 = 8,571.43 (EBITDA held). Remaining revenue must rise by x with
   (10,000 + 9,000x - 7,000) / (10,000 + 9,000x) = 0.35: x = 0.0854700... Budget margin is also
   30%, so the total is 0, made of sales -0.14, cost of sales +0.10 and rent +0.016667, with
   residual +0.023333 shown explicitly (AC-GO5).
3. Cash at least 2,350 throughout: worst month end 2,300 (February, an actual breach); short by
   50, within 5% of 2,350: at risk; additional inflow 50.
4. DSO at most 30 days: 9.125, on track.
5. Net profit +15%: target 1,600 x 1.15 = 1,840; 2,450 projected, on track.
6. Opex -10%: target 1,080 (at most); 1,000 projected, on track.
"""

from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.goals.models import GoalVersion

from ..kpi.test_kpis import _post, k
from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
__all__ = ["books", "k"]
FY = {"period_start": "2026-01-01", "period_end": "2026-12-31"}
MONTHS = [f"2026-{m:02d}-01" for m in range(1, 13)]


@pytest.fixture
def g(k: dict[str, Any]) -> dict[str, Any]:
    _post(k, "2025-06-15", ("6100", "1200", "0", None), ("1300", "0", "1200", None))
    _post(k, "2025-09-10", ("1300", "2000", "0", None), ("4000", "0", "2000", None))
    return k


def budget(g: dict[str, Any]) -> None:
    c, base = g["client"], g["base"]
    assert c.put_json(f"{base}/budget-settings", {"sod_required": False}).status_code == 200
    made = c.post_json(f"{base}/budgets", {"name": "Plan 2026", "fiscal_year_id": g["fy"]["id"]})
    assert made.status_code == 201, made.content
    version = made.json()["open_version_id"]
    lines = [
        {"taxonomy_code": code, "amounts": dict.fromkeys(MONTHS, amount)}
        for code, amount in (("REV.SALES", "1000.00"), ("COGS", "600.00"),
                             ("OPEX.RENT", "100.00"), ("DA.DEPRECIATION", "50.00"))
    ]  # fmt: skip
    put = c.put_json(f"{base}/budget-versions/{version}/lines", {"lines": lines})
    assert put.status_code == 200, put.content
    for action in ("submit", "approve"):
        done = c.post_json(f"{base}/budget-versions/{version}/{action}", {})
        assert done.status_code == 200, done.content


def goal(g: dict[str, Any], name: str, metric: str, target_type: str, target: str,
         **extra: Any) -> dict[str, Any]:  # fmt: skip
    body = {"name": name, "metric": metric, "target_type": target_type, "target": target,
            **FY, **extra}  # fmt: skip
    made = g["client"].post_json(f"{g['base']}/goals", body)
    assert made.status_code == 201, made.content
    out: dict[str, Any] = made.json()
    return out


def evaluate(g: dict[str, Any], goal_id: str, **extra: Any) -> dict[str, Any]:
    made = g["client"].post_json(
        f"{g['base']}/goals/{goal_id}/evaluations", {"as_of": "2026-03-31", **extra}
    )
    assert made.status_code == 201, made.content
    out: dict[str, Any] = made.json()
    assert out["run_status"] == "VALID"
    return out


def fig(ev: dict[str, Any], key: str, dim: str | None = None) -> Decimal | str:
    for f in ev["figures"]:
        if f["key"] == key and (dim is None or (f["dimensions"] and f["dimensions"][0] == dim)):
            return Decimal(f["value"]) if f["value"] is not None else f["nm_reason"]
    raise AssertionError(f"no {key} {dim}")


def near(value: Decimal | str, expected: str, tolerance: str = "1e-12") -> bool:
    return isinstance(value, Decimal) and abs(value - Decimal(expected)) < Decimal(tolerance)


def test_golden_six_sample_goals(g: dict[str, Any]) -> None:  # noqa: PLR0915 (one fixture, six goals)
    budget(g)
    revenue = goal(g, "Revenue 12k", "REVENUE", "ABSOLUTE", "12000")
    assert revenue["current"]["baseline_value"] == "2800"
    assert (revenue["current"]["baseline_from"], revenue["current"]["baseline_to"]) == (
        "2025-01-01", "2025-12-31")  # fmt: skip
    ev = evaluate(g, revenue["id"])
    assert (ev["status"], ev["method"], ev["cut_over"]) == ("OFF_TRACK", "BUDGET", "2026-03-31")
    assert ev["method_note"] == "Actuals to 2026-03-31, then the approved budget"
    assert fig(ev, "goal.actual") == 1000
    assert fig(ev, "goal.projected") == 10000
    assert fig(ev, "goal.gap", "PROJECTED") == 2000
    assert fig(ev, "goal.gap", "ACTUAL") == 11000
    assert near(fig(ev, "goal.time_elapsed"), str(Decimal(90) / Decimal(365)))
    assert near(fig(ev, "goal.achieved"), str(Decimal(1000) / Decimal(12000)))
    assert fig(ev, "goal.required.remaining") == 11000
    assert near(fig(ev, "goal.required.run_rate"), str(Decimal(11000) / 9))
    assert fig(ev, "goal.projected_run_rate") == 1000
    assert near(fig(ev, "goal.historical_run_rate"), str(Decimal(1000) / 3))
    assert fig(ev, "goal.comparison", "BUDGET") == 12000
    assert fig(ev, "goal.contribution", "REV.SALES") == -2000
    assert fig(ev, "goal.contribution.residual") == 0
    assert fig(ev, "goal.contribution.total") == -2000
    natures = {f["period_start"]: f["nature"] for f in ev["figures"] if f["key"] == "goal.trend"}
    assert natures["2026-03-01"] == "ACTUAL"
    assert natures["2026-04-01"] == "BUDGET"
    projected = next(f for f in ev["figures"] if f["key"] == "goal.projected")
    assert (projected["nature"], projected["dimensions"]) == ("BUDGET", ["BLENDED", "BUDGET"])

    margin = goal(g, "EBITDA margin 35%", "kpi:EBITDA_MARGIN", "ABSOLUTE", "0.35")
    assert margin["metric_ref"] == "CORE@1.0:EBITDA_MARGIN"
    assert near(Decimal(margin["current"]["baseline_value"]), str(Decimal(1600) / 2800))
    ev = evaluate(g, margin["id"])
    assert ev["status"] == "OFF_TRACK"
    assert fig(ev, "goal.projected") == Decimal("0.3")
    assert fig(ev, "goal.required.numerator") == 3500
    assert near(fig(ev, "goal.required.denominator"), str(Decimal(3000) / Decimal("0.35")))
    change = fig(ev, "goal.required.driver_change", "REVENUE")
    exact = (Decimal(7000) / Decimal("0.65") - 10000) / 9000
    assert isinstance(change, Decimal)
    assert exact <= change < exact + Decimal("0.0001")
    assert fig(ev, "goal.comparison", "BUDGET") == Decimal("0.3")
    assert near(fig(ev, "goal.contribution", "REV.SALES"), "-0.14")
    assert near(fig(ev, "goal.contribution", "COGS"), "0.1")
    assert near(fig(ev, "goal.contribution", "OPEX.RENT"), str(Decimal(200) / 12000))
    assert near(fig(ev, "goal.contribution.residual"), str(Decimal("0.04") - Decimal(200) / 12000))
    assert fig(ev, "goal.contribution.total") == 0

    cash = goal(g, "Cash at least 2,350", "CASH", "MAINTAIN_MIN", "2350")
    assert cash["current"]["baseline_value"] == "2400"
    ev = evaluate(g, cash["id"])
    assert (ev["status"], ev["method"]) == ("AT_RISK", "HELD")
    assert fig(ev, "goal.actual") == 3090
    assert fig(ev, "goal.projected") == 2300
    assert fig(ev, "goal.required.inflow") == 50
    breach = next(f for f in ev["figures"] if f["key"] == "goal.required.breach")
    assert (breach["period_start"], breach["nature"], breach["value"]) == (
        "2026-02-28", "ACTUAL", "2300")  # fmt: skip

    dso = goal(g, "DSO 30 days", "kpi:DSO", "ABSOLUTE", "30")
    assert dso["current"]["direction"] == "AT_MOST"
    ev = evaluate(g, dso["id"])
    assert ev["status"] == "ON_TRACK"
    assert fig(ev, "goal.projected") == Decimal("9.125")
    assert fig(ev, "goal.required.driver_change", "REVENUE") == 0

    profit = goal(g, "Net profit +15%", "NET_PROFIT", "CHANGE_PCT", "0.15")
    assert (profit["current"]["baseline_value"], profit["current"]["target_value"]) == (
        "1600", "1840")  # fmt: skip
    ev = evaluate(g, profit["id"])
    assert ev["status"] == "ON_TRACK"
    assert fig(ev, "goal.projected") == 2450

    opex = goal(g, "Opex -10%", "OPEX", "CHANGE_PCT", "-0.10")
    assert (opex["current"]["target_value"], opex["current"]["direction"]) == ("1080", "AT_MOST")
    ev = evaluate(g, opex["id"])
    assert ev["status"] == "ON_TRACK"
    assert fig(ev, "goal.projected") == 1000

    # Every evaluation is a reproducible calculation run.
    again = g["client"].post_json(f"{g['base']}/calc-runs/{ev['run_id']}/reproduce", {})
    assert again.json()["reproduced"] is True, again.json()


def test_baseline_is_frozen_and_a_new_target_is_a_new_version(g: dict[str, Any]) -> None:
    made = goal(g, "Revenue", "REVENUE", "ABSOLUTE", "12000")
    base = f"{g['base']}/goals/{made['id']}"
    c = g["client"]
    body = {"target_type": "CHANGE_PCT", "target": "0.5", "reason": ""}
    assert c.post_json(f"{base}/versions", body).status_code == 422
    body["reason"] = "Board asked for +50%"
    revised = c.post_json(f"{base}/versions", body)
    assert revised.status_code == 201, revised.content
    out = revised.json()
    assert [v["number"] for v in out["versions"]] == [1, 2]
    assert out["current"]["number"] == 2
    assert out["current"]["target_value"] == "4200"  # 2,800 x 1.5
    first, second = out["versions"]
    assert first["superseded_at"] is not None
    for field in ("baseline_value", "baseline_from", "baseline_to", "baseline_run_id"):
        assert first[field] == second[field]
    ev = evaluate(g, made["id"])
    assert ev["version"] == 2
    # Without a budget, the remaining months use the 3-month run rate: 1,000 + 9 x 333.33.
    assert ev["method"] == "RUN_RATE"
    assert near(fig(ev, "goal.projected"), "4000", "1e-15")
    assert fig(ev, "goal.comparison", "PRIOR_YEAR") == 2800

    with transaction.atomic():  # the database keeps versions and goals as they are
        set_context(tenant_id=g["ws"]["id"])
        with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
            GoalVersion.objects.filter(id=second["id"]).update(baseline_value=Decimal(1))
        with pytest.raises(DatabaseError, match="kept"), transaction.atomic():
            GoalVersion.objects.filter(id=first["id"]).delete()

    retired = c.post_json(f"{base}/retire", {})
    assert retired.json()["status"] == "RETIRED"
    assert c.post_json(f"{base}/versions", body).status_code == 409
    assert c.post_json(f"{base}/evaluations", {}).status_code == 409
    assert c.get(f"{g['base']}/goals").json() == []
    assert len(c.get(f"{g['base']}/goals?include_retired=true").json()) == 1


def test_goal_seek_reports_not_achievable_within_bounds(g: dict[str, Any]) -> None:
    budget(g)
    made = goal(g, "DSO 1 day", "kpi:DSO", "ABSOLUTE", "1")
    ev = evaluate(g, made["id"])
    assert ev["status"] == "OFF_TRACK"
    assert fig(ev, "goal.required.driver_change", "REVENUE") == (
        "Not achievable within ±100% of REVENUE"
    )
    seek = next(f for f in ev["figures"] if f["key"] == "goal.required.driver_change")
    explained = (
        g["client"]
        .get(f"{g['base']}/calc-runs/{ev['run_id']}/results/{seek['result_id']}/explain")
        .json()
    )
    assert "every other line as projected" in explained["lineage"][0]["note"]
    # Another driver can be chosen per evaluation.
    other = evaluate(g, made["id"], driver="COGS")
    assert fig(other, "goal.required.driver_change", "COGS") == (
        "Not achievable within ±100% of COGS"
    )
    latest = g["client"].get(f"{g['base']}/goals/{made['id']}/evaluations/latest").json()
    assert latest["run_id"] == other["run_id"]
    assert [h["status"] for h in latest["history"]] == ["OFF_TRACK", "OFF_TRACK"]


def test_validation(g: dict[str, Any]) -> None:
    c, base = g["client"], f"{g['base']}/goals"
    ok = {"name": "x", "metric": "REVENUE", "target_type": "ABSOLUTE", "target": "1", **FY}
    for change, field in (
        ({"metric": "NOPE"}, "metric"),
        ({"period_start": "2026-01-02"}, "period_start"),
        ({"period_end": "2028-01-31"}, "period_end"),
        ({"target_type": "MAINTAIN_MIN"}, "target_type"),
        ({"target_type": "CHANGE_PCT", "target": "0"}, "target"),
        ({"materiality": "2"}, "materiality"),
        ({"driver": "NOT.A.LINE"}, "driver"),
    ):
        refused = c.post_json(base, {**ok, **change})
        assert refused.status_code == 422, (change, refused.content)
        assert field in refused.json()["errors"], refused.json()
    # A change from a baseline that is not meaningful (no revenue from April to June 2025).
    q2 = {"period_start": "2026-04-01", "period_end": "2026-06-30"}
    nm = c.post_json(base, {**ok, **q2, "metric": "kpi:GROSS_MARGIN", "target_type": "CHANGE_PCT",
                            "target": "0.1"})  # fmt: skip
    assert nm.status_code == 409, nm.content
    assert c.post_json(f"{base}/{ok['name']}/evaluations", {}).status_code == 404


def test_permissions(g: dict[str, Any], make_user: Any, api_client: Any) -> None:
    viewer = join(g["client"], g["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    body = {"name": "x", "metric": "REVENUE", "target_type": "ABSOLUTE", "target": "1", **FY}
    assert viewer.post_json(f"{g['base']}/goals", body).status_code == 403
    made = goal(g, "Revenue", "REVENUE", "ABSOLUTE", "12000")
    assert viewer.get(f"{g['base']}/goals/{made['id']}").status_code == 200
    assert viewer.post_json(f"{g['base']}/goals/{made['id']}/evaluations", {}).status_code == 403
    metrics = viewer.get(f"{g['base']}/goal-metrics").json()
    assert [m["key"] for m in metrics][:5] == ["REVENUE", "OPEX", "EBITDA", "NET_PROFIT", "CASH"]
    assert "kpi:DSO" in {m["key"] for m in metrics}


def test_prior_year_comparison_covers_the_whole_prior_window(g: dict[str, Any]) -> None:
    """A goal for 2027 evaluated on 31 March 2026: the comparison is all of 2026 as posted (as
    the baseline), while the projection uses actuals to the cut-over only."""
    _post(g, "2026-06-10", ("1300", "500", "0", None), ("4000", "0", "500", None))
    made = g["client"].post_json(f"{g['base']}/goals", {
        "name": "Revenue 2027", "metric": "REVENUE", "target_type": "ABSOLUTE",
        "target": "5000", "period_start": "2027-01-01", "period_end": "2027-12-31",
    })  # fmt: skip
    assert made.status_code == 201, made.content
    assert made.json()["current"]["baseline_value"] == "1500"
    ev = evaluate(g, made.json()["id"])
    assert fig(ev, "goal.comparison", "PRIOR_YEAR") == 1500
    # Run rate from January to March 2026 only (1,000 / 3 a month), 12 months.
    assert near(fig(ev, "goal.projected"), "4000", "1e-15")
