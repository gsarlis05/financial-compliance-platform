"""Goals against the published projection (M6F-7, #152; owner decision D7), on the books of
``test_outlook`` (a projection cut over at 30 June 2026 expecting July sales of 2,000,
published), with 1,500 of sales posted in July and the goal evaluated as of 30 September: the
projection covers July to September to date; forecast 2,000, actual 1,500, actual - forecast =
-500. Without an approved budget, the contribution analysis compares with the same months a year
earlier (never with the projection itself). New projections never change an approved goal.
"""

from decimal import Decimal
from typing import Any

import pytest

from ..metrics.test_mapping import post
from ..projections.test_assumptions import books, hist
from ..projections.test_outlook import published
from .test_benchmarks import amount, figure

pytestmark = pytest.mark.django_db
__all__ = ["books", "hist"]


def test_actual_against_the_published_projection_and_goals_never_change(
    hist: dict[str, Any],
) -> None:
    c, base = hist["client"], hist["base"]
    published(hist)
    post(hist, ("1300", "1500.00", "0"), ("4000", "0", "1500.00"), day="2026-07-10")
    body = {"name": "Revenue 5k", "metric": "REVENUE", "target_type": "ABSOLUTE",
            "target": "5000", "period_start": "2026-01-01", "period_end": "2026-12-31"}  # fmt: skip
    made = c.post_json(f"{base}/goals", body).json()
    before = c.get(f"{base}/goals/{made['id']}").json()
    ev = c.post_json(f"{base}/goals/{made['id']}/evaluations", {"as_of": "2026-09-30"}).json()
    assert ev["method"] == "PROJECTION"
    forecast = figure(ev, "goal.benchmark", "FORECAST", "TO_DATE")
    assert (forecast["period_start"], forecast["period_end"]) == ("2026-07-01", "2026-09-30")
    assert Decimal(forecast["value"]) == 2000
    assert amount(ev, "goal.benchmark", "ACTUAL", "FORECAST_MONTHS") == 1500
    assert amount(ev, "goal.variance", "ACTUAL_VS_FORECAST") == -500
    budget_period = figure(ev, "goal.benchmark", "BUDGET", "PERIOD")
    assert budget_period["nm_reason"] == (
        "No approved budget covers every month of the goal's period")  # fmt: skip
    assert figure(ev, "goal.comparison", "PRIOR_YEAR")["nature"] == "ACTUAL"

    # A newer projection is run and published, and the goal evaluated again: the approved goal
    # (its versions, target and baseline) is exactly as it was.
    again = published(hist)
    assert again["status"] == "VALID"
    c.post_json(f"{base}/goals/{made['id']}/evaluations", {"as_of": "2026-09-30"})
    after = c.get(f"{base}/goals/{made['id']}").json()
    assert after["versions"] == before["versions"]
    assert after["current"] == before["current"]
