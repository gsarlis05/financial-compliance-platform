"""Sensitivity and tornado (M7-3, AC-SE1 and AC-SE2): figures worked out by hand on the synthetic
base of ``test_runs``; results equal single engine runs; the cache, quotas and time limit hold."""

import re
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.core.cache import cache
from django.test import override_settings

from fcp.core.errors import ValidationFailedError
from fcp.modules.scenarios import sensitivity as sens
from fcp.modules.scenarios.runs import steps

from ..ledger.conftest import books, join
from .test_runs import base, item
from .test_runs_api import plan

Make = Callable[..., Any]
D = Decimal
__all__ = ["books", "plan"]


def test_tornado_by_hand_and_ties_by_name() -> None:
    """EBITDA 2027 of the base: revenue 120,000; cost of sales 60% = 72,000; costs 36,000;
    EBITDA 12,000. Revenue +-10%: 132,000 x 40% - 36,000 = 16,800 and 108,000 x 40% - 36,000 =
    7,200 (swing 9,600). Gross margin +-10% (44% and 36%): 16,800 and 7,200, the same swing; ties
    go by name. Payroll +-10%: +-2,400 (swing 4,800). DSO does not move EBITDA."""
    bars = sens.tornado(base(), ["dso", "revenue", "opex:OPEX.PAYROLL", "gross_margin"],
                        percent=D(10), output="EBITDA", year=2027)  # fmt: skip
    got = [(b.driver, b.low.value, b.high.value, b.swing) for b in bars]
    assert got == [
        ("gross_margin", D("7200.00"), D("16800.00"), D("9600.00")),
        ("revenue", D("7200.00"), D("16800.00"), D("9600.00")),
        ("opex:OPEX.PAYROLL", D("14400.00"), D("9600.00"), D("4800.00")),
        ("dso", D("12000.00"), D("12000.00"), D("0.00")),
    ]
    assert sens.run(base(), "EBITDA", 2027).value == D("12000.00")


def test_results_equal_single_engine_runs() -> None:
    """AC-SE1: a shock gives what the same single change gives as a scenario."""
    inp = base()
    bar = sens.tornado(inp, ["revenue"], percent=D(10), output="MIN_CASH", year=None)[0]
    as_scenario = steps(inp, [item(1, "PCT_CHANGE", driver="revenue", lines=[], percent="10")])
    assert bar.high.value == sens.measure(as_scenario.final, "MIN_CASH").value
    days = sens.one_variable(inp, "dso", [D(0), D(30), D(60)], unit="DAYS", output="MIN_CASH",
                             year=None)  # fmt: skip
    shifted = steps(inp, [item(1, "TIMING_SHIFT", mode="DAYS", driver="dso", days=30)])
    assert days[1].result.value == sens.measure(shifted.final, "MIN_CASH").value
    # Later customer payments lower the lowest cash.
    assert days[0].result.value > days[1].result.value > days[2].result.value


def test_outputs_and_refusals() -> None:
    inp = base()
    assert sens.steps_of(D(-20), D(20), 5) == [D(-20), D(-10), D(0), D(10), D(20)]
    closing = sens.run(inp, "CLOSING_CASH", None)
    assert closing.month is not None and closing.month.month == 12  # noqa: PT018
    assert sens.run(inp, "FIRST_SHORTFALL", None).value == D(12)  # never short: the horizon
    short = sens.run(sens.shock(inp, "revenue", percent=D(-100)), "FIRST_SHORTFALL", None)
    assert short.value < D(12)
    for call, message in (
        (lambda: sens.steps_of(D(1), D(1), 3), "must be above low"),
        (lambda: sens.steps_of(D(0), D(1), 12), "from 2 to 11"),
        (lambda: sens.shock(inp, "magic"), "choose one of"),
        (lambda: sens.run(inp, "MAGIC", None), "output: choose one of"),
        (lambda: sens.run(inp, "EBITDA", 2030), "a year of the horizon (2027)"),
        (lambda: sens.one_variable(inp, "revenue", [D(1)], unit="DAYS", output="MIN_CASH",
                                   year=None), "days apply to DSO, DIO and DPO only"),
        (lambda: sens.tornado(inp, [], percent=D(10), output="MIN_CASH", year=None),
         "from 1 to 25"),
    ):  # fmt: skip
        with pytest.raises(ValidationFailedError, match=re.escape(message)):
            call()
    with pytest.raises(sens.TimeLimitError):
        sens.tornado(inp, ["revenue"], percent=D(10), output="MIN_CASH", year=None, deadline=0)
    rates = sens.shock(inp, "interest_rate", percent=D(50))
    assert rates.loans[0].annual_rate == D("7.5")


@pytest.fixture
def clean_cache() -> Iterator[None]:
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
@pytest.mark.usefixtures("clean_cache")
def test_api_cache_quota_and_bases(plan: dict[str, Any], make_user: Make,
                                   api_client: Make) -> None:  # fmt: skip
    """EBITDA 2027 of the plan: sales 12,000 x 40% - rent 3,600 = 1,200. Sales +-10%: 1,680 and
    720 (swing 960); margin the same; rent +-10%: +-360 (swing 720); rates do not move EBITDA."""
    c, url = plan["client"], f"{plan['base']}/sensitivity"
    body = {"base_set_id": plan["set_id"], "output": "EBITDA", "year": 2027}
    got = c.post_json(f"{url}/tornado", body)
    assert got.status_code == 200, got.content
    t = got.json()
    assert (t["nature"], t["cached"], t["base"]["value"]) == ("HYPOTHETICAL", False, "1200.00")
    assert t["engine_status"] == "OWNER_CHECKED"
    assert [(b["driver"], b["swing"]) for b in t["bars"]] == [
        ("gross_margin", "960.00"), ("revenue:REV.SALES", "960.00"),
        ("opex:OPEX.RENT", "720.00"), ("interest_rate", "0.00")]  # fmt: skip
    again = c.post_json(f"{url}/tornado", body).json()
    assert (again["cached"], again["input_hash"]) == (True, t["input_hash"])

    one = c.post_json(f"{url}/one-variable", {**body, "driver": "revenue", "low": "-20",
                                              "high": "20", "steps": 3}).json()  # fmt: skip
    assert [(p["shock"], p["result"]["value"], p["change"]) for p in one["points"]] == [
        ("-20", "240.00", "-960.00"),
        ("0", "1200.00", "0.00"),
        ("20", "2160.00", "960.00"),
    ]

    both = c.post_json(f"{url}/tornado", {**body, "scenario_id": plan["set_id"]})
    assert both.status_code == 422
    s = c.post_json(plan["url"], {"name": "S", "base_set_id": plan["set_id"]}).json()
    by_scenario = {"scenario_id": s["id"], "output": "MIN_CASH"}
    assert c.post_json(f"{url}/tornado", by_scenario).status_code == 409  # a draft
    c.post_json(f"{plan['url']}/{s['id']}/share", {})
    assert c.post_json(f"{url}/tornado", by_scenario).status_code == 200

    with override_settings(SENSITIVITY_RUNS_PER_MINUTE_USER=3):
        refused = c.post_json(f"{url}/tornado", {**body, "percent": "5"})
        assert refused.status_code == 429
        assert "at most 3 projection runs" in refused.json()["detail"]
        assert c.post_json(f"{url}/tornado", body).json()["cached"] is True  # costs nothing

    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.post_json(f"{url}/tornado", body).status_code == 403
