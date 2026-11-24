"""The full-year outlook and goals that use it (M6-5, AC-OL1), on the books of
``test_assumptions.hist``: in 2026, sales 1,200 (January) and 1,100 (February); cost of sales 480
and 320; rent 600 and 500; cash 100 from February on.

A 12-month set cut over at 30/06/2026 (July 2026 to June 2027), with July's sales set to 2,000 by
hand (other months repeat July to December 2025: nothing), approved; its projection published.
By hand: July cost of sales = 2,000 x (100% - 65.2174%) = 695.65. Forecast cash is checked
against the projection's own balance sheet (tied by its invariants).
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from .test_assumptions import books, hist, make

pytestmark = pytest.mark.django_db
__all__ = ["books", "hist"]


def published(h: dict[str, Any]) -> dict[str, Any]:
    c, base = h["client"], h["base"]
    s = make(h, cutover="2026-06-30", months=12).json()
    url = f"{base}/assumption-sets/{s['id']}"
    july = {"driver": "revenue", "line": "REV.SALES", "month": "2026-07-01", "value": "2000"}
    changed = c.put_json(f"{url}/values", {"changes": [july]})
    assert changed.status_code == 200, changed.content
    assert c.post_json(f"{url}/approve", {}).status_code == 200
    run = c.post_json(f"{base}/projections", {"assumption_set_id": s["id"]}).json()
    assert run["status"] == "VALID", run
    assert c.post_json(f"{base}/calc-runs/{run['id']}/publish", {}).status_code == 200
    out: dict[str, Any] = run
    return out


def test_outlook_blends_actual_and_forecast_months(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    before = c.get(f"{base}/outlook?day=2026-05-01").json()
    assert before["projection_id"] is None
    assert before["note"] == "No published projection reaches this year: actual months only."
    run = published(hist)
    got = c.get(f"{base}/outlook?day=2026-05-01")
    assert got.status_code == 200, got.content
    o = got.json()
    assert (o["year_start"], o["cutover"], o["projection_id"]) == (
        "2026-01-01", "2026-06-30", run["id"])  # fmt: skip
    natures = [col["nature"] for col in o["columns"]]
    assert natures == ["ACTUAL"] * 6 + ["FORECAST"] * 6 + [
        "ACTUAL", "ACTUAL", "FORECAST", "FORECAST", "ACTUAL+FORECAST"]  # fmt: skip
    assert [col["granularity"] for col in o["columns"]][11:] == ["MONTH"] + ["QUARTER"] * 4 + [
        "YEAR"]  # fmt: skip
    revenue = o["rows"]["PL.REVENUE"]
    assert revenue[:3] == ["1200.00", "1100.00", "0.00"]
    assert revenue[6] == "2000.00"  # July, from the projection
    assert revenue[12:] == ["2300.00", "0.00", "2000.00", "0.00", "4300.00"]
    cogs = o["rows"]["PL.COGS"]
    assert (cogs[0], cogs[6]) == ("480.00", "695.65")
    assert o["rows"]["PL.OPEX.RENT"][:2] == ["600.00", "500.00"]
    # Quarters and the year are exact sums of their months; cash is the last month's.
    for key, values in o["rows"].items():
        months = [Decimal(v) for v in values[:12]]
        if key == "BS.CASH":
            assert values[15:17] == [values[11], values[11]]
            continue
        for q in range(4):
            assert Decimal(values[12 + q]) == sum(months[3 * q : 3 * q + 3], Decimal(0)), key
        assert Decimal(values[16]) == sum(months, Decimal(0)), key
    cash = o["rows"]["BS.CASH"]
    assert cash[1:6] == ["100.00"] * 5  # actual month ends
    statements = c.get(f"{base}/projections/{run['id']}").json()
    assert cash[6:12] == statements["rows"]["BS.CASH"][1:7]  # the projection's month ends


def test_goals_use_the_published_projection(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    published(hist)
    body = {"name": "Revenue 5k", "metric": "REVENUE", "target_type": "ABSOLUTE",
            "target": "5000", "period_start": "2026-01-01", "period_end": "2026-12-31"}  # fmt: skip
    made = c.post_json(f"{base}/goals", body)
    assert made.status_code == 201, made.content
    ev = c.post_json(f"{base}/goals/{made.json()['id']}/evaluations", {"as_of": "2026-06-30"})
    assert ev.status_code == 201, ev.content
    e = ev.json()
    assert e["method"] == "PROJECTION"
    assert e["method_note"] == "Actuals to 2026-06-30, then the published projection"
    projected = next(f for f in e["figures"] if f["key"] == "goal.projected")
    assert Decimal(projected["value"]) == Decimal(4300)  # 2,300 actual + 2,000 projected
    assert date.fromisoformat(e["cut_over"]) == date(2026, 6, 30)
