"""KPIs on projected and scenario figures (M7-6, AC-KP6): the library's definitions, unchanged, on
the synthetic base of ``test_runs`` (2027: revenue 120,000, cost of sales 72,000, costs 36,000,
EBITDA 12,000; no tax rules, so no tax)."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from fcp.modules.projections.api import project
from fcp.modules.scenarios import projected_kpis as pk

from ..ledger.conftest import books, join
from .test_runs import base
from .test_runs_api import plan, scenario

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
D = Decimal
__all__ = ["books", "plan"]


def test_library_on_a_projected_year() -> None:
    p, _ = project(base())
    start, end = p.months[0].month, p.months[-1].month.replace(day=31)
    values = {k.key: k for k in pk.evaluate(pk.books(p), start, end)}
    assert len(values) == 23  # CORE@1.1
    assert values["GROSS_MARGIN"].value == D("0.4")
    assert values["EBITDA_MARGIN"].value == D("0.1")
    dec = p.months[-1].bs
    interest = sum((m.pl["PL.INTEREST"] for m in p.months), D(0))
    debt = dec["BS.DEBT.CURRENT"] + dec["BS.DEBT.NONCURRENT"]
    # Net debt / EBITDA: (debt - cash) at the end of 2027 over the year's EBITDA of 12,000.
    assert values["NET_DEBT_TO_EBITDA"].value == (debt - dec["BS.CASH"]) / D(12000)
    # DSCR: (EBITDA - tax 0) / (the year's interest + the debt due within 12 months).
    assert values["DSCR"].value == D(12000) / (interest + dec["BS.DEBT.CURRENT"])
    # Receivables turnover: 120,000 x 365/365 over the mean of 0 and 9,677.42 at the year end.
    assert values["RECEIVABLES_TURNOVER"].value == D(120000) / ((D(0) + dec["BS.AR"]) / 2)
    assert dec["BS.AR"] == D("9677.42")
    # No stock: inventory turnover is not meaningful, with the library's reason.
    assert values["INVENTORY_TURNOVER"].value is None
    assert values["INVENTORY_TURNOVER"].nm_reason == "Average inventory is zero"
    # The projection holds no 2026: growth is not meaningful, and says why.
    assert values["REVENUE_GROWTH"].nm_reason == (
        "The projection does not hold the same period a year earlier"
    )


def test_missing_months_are_not_computed() -> None:
    p, _ = project(base())
    b = pk.books(p)
    first = p.months[0].month
    june = p.months[5].month.replace(day=30)
    values = {k.key: k for k in pk.evaluate(b, first, june)}
    assert values["NET_DEBT_TO_EBITDA"].nm_reason == (
        "The projection does not hold the 12 months to the end of the period"
    )
    q1 = {k.key: k for k in pk.evaluate(b, first, p.months[1].month.replace(day=28))}
    assert q1["CASH_RUNWAY"].nm_reason == (
        "The projection does not hold three months of cash before the end of the period"
    )


def test_api(plan: dict[str, Any], make_user: Make, api_client: Make) -> None:
    """The plan: sales 1,000 a month at 40%, rent 300: EBITDA 1,200 in 2027 (margin 10%). A
    scenario with sales +50%: 18,000 x 40% - 3,600 = 3,600 (margin 20%)."""
    c, url = plan["client"], f"{plan['base']}/projected-kpis"
    got = c.get(f"{url}?year=2027&base_set_id={plan['set_id']}")
    assert got.status_code == 200, got.content
    body = got.json()
    assert (body["nature"], body["library"], body["start"], body["end"]) == (
        "FORECAST",
        "CORE@1.1",
        "2027-01-01",
        "2027-12-31",
    )
    k = {x["key"]: x for x in body["kpis"]}
    assert k["EBITDA_MARGIN"]["value"] == "0.1"
    s = scenario(plan, ("PCT_CHANGE", {"driver": "revenue", "percent": "50"}))
    c.post_json(f"{s}/share", {})
    sid = s.rsplit("/", 1)[1]
    hyp = c.get(f"{url}?year=2027&scenario_id={sid}").json()
    k = {x["key"]: x for x in hyp["kpis"]}
    assert hyp["nature"] == "HYPOTHETICAL"
    assert (k["EBITDA_MARGIN"]["value"], k["EBITDA_MARGIN"]["base_value"]) == ("0.2", "0.1")
    assert c.get(f"{url}?year=2030&base_set_id={plan['set_id']}").status_code == 422
    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{url}?year=2027&base_set_id={plan['set_id']}").status_code == 403
