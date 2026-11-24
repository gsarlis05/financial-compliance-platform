"""Goals and benchmarks (M6F-7, #152; owner decision D7): the published projection is the
forward reference, the approved budget a separate benchmark, and approved goals never change.

1. The golden fixture of ``test_goals`` (approved 2026 budget: sales 1,000 a month; Q1 actual
   revenue 1,000; likely outcome 10,000), as of 31 March 2026: budget for the year 12,000 and
   for Q1 3,000; actual - budget to date = 1,000 - 3,000 = -2,000; likely outcome - budget =
   10,000 - 12,000 = -2,000; no published projection covers a month to date.
2. Against the published projection, and approved goals never change:
   ``test_benchmarks_projection``.
"""

from decimal import Decimal
from typing import Any

import pytest

from ..kpi.test_kpis import k
from ..ledger.conftest import books
from .test_goals import budget, evaluate, g, goal

pytestmark = pytest.mark.django_db
__all__ = ["books", "g", "k"]


def figure(ev: dict[str, Any], key: str, *dims: str) -> dict[str, Any]:
    found: list[dict[str, Any]] = [
        f for f in ev["figures"] if f["key"] == key and tuple(f["dimensions"][: len(dims)]) == dims
    ]
    assert len(found) == 1, (key, dims, [f["dimensions"] for f in ev["figures"] if f["key"] == key])
    return found[0]


def amount(ev: dict[str, Any], key: str, *dims: str) -> Decimal | None:
    value = figure(ev, key, *dims)["value"]
    return None if value is None else Decimal(value)


def test_budget_benchmarks_on_the_golden_fixture(g: dict[str, Any]) -> None:
    budget(g)
    ev = evaluate(g, goal(g, "Revenue 12k", "REVENUE", "ABSOLUTE", "12000")["id"])
    assert amount(ev, "goal.benchmark", "BUDGET", "PERIOD") == 12000
    to_date = figure(ev, "goal.benchmark", "BUDGET", "TO_DATE")
    assert (Decimal(to_date["value"]), to_date["period_end"]) == (Decimal(3000), "2026-03-31")
    assert amount(ev, "goal.variance", "ACTUAL_VS_BUDGET") == -2000
    assert amount(ev, "goal.variance", "PROJECTED_VS_BUDGET") == -2000
    assert amount(ev, "goal.variance", "PROJECTED_VS_GOAL") == -2000  # 10,000 - 12,000
    forecast = figure(ev, "goal.benchmark", "FORECAST", "TO_DATE")
    assert forecast["value"] is None
    assert forecast["nm_reason"] == "No published projection covers a month of the period to date"
    assert figure(ev, "goal.variance", "ACTUAL_VS_FORECAST")["value"] is None
    assert amount(ev, "goal.comparison", "BUDGET") == 12000
