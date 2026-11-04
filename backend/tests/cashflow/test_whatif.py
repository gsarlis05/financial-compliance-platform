"""What-ifs on a cash forecast (M3-9, AC-CW7): HYPOTHETICAL, never saved, delta per week."""

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.modules.cashflow import engine as engine_module
from fcp.modules.cashflow.whatif import Override, apply_overrides, summarise

from ..ledger.conftest import join
from ..registers.test_open_items import ar, books
from .test_engine import ACCOUNT, flow, inputs
from .test_forecast import fc

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["ar", "books", "fc"]


def forecast(fc: dict[str, Any]) -> dict[str, Any]:
    made = fc["client"].post_json(f"{fc['base']}/cash-forecasts", {"as_of": "2026-11-04"})
    assert made.status_code == 201, made.content
    result: dict[str, Any] = made.json()
    return result


def what_if(fc: dict[str, Any], run_id: str, *overrides: dict[str, Any], client: Any = None) -> Any:
    return (client or fc["client"]).post_json(
        f"{fc['base']}/cash-forecasts/{run_id}/what-if", {"overrides": list(overrides)}
    )


def test_a_customer_paying_sixty_days_later(fc: dict[str, Any]) -> None:
    base = forecast(fc)
    response = what_if(fc, base["run_id"], {"type": "TIMING_SHIFT", "party": "C1", "days": 60})
    assert response.status_code == 200, response.content
    r = response.json()
    assert (r["nature"], r["saved"], r["matched"]) == ("HYPOTHETICAL", False, [1])
    # INV1 (1,190.00) moves from Sun 22 Nov (week 3) to Thu 21 Jan 2027 (week 12).
    deltas = [w["delta"] for w in r["weeks"]]
    assert deltas == ["0.00"] * 2 + ["-1190.00"] * 9 + ["0.00"] * 2
    assert [w["base_closing"] for w in r["weeks"]] == [w["closing"] for w in base["weeks"]]
    assert r["weeks"][2]["what_if_closing"] == "8500.00"
    assert r["hypothetical_total"] == "1190.00"
    # Nothing was saved: the base run and the history are unchanged.
    again = fc["client"].get(f"{fc['base']}/cash-forecasts/{base['run_id']}").json()
    assert again["weeks"] == base["weeks"]
    history = fc["client"].get(f"{fc['base']}/cash-forecasts/history").json()
    assert [h["run_id"] for h in history] == [base["run_id"]]


def test_percentages_one_offs_and_shortfalls(fc: dict[str, Any]) -> None:
    base = forecast(fc)
    r = what_if(
        fc,
        base["run_id"],
        {"type": "PCT_CHANGE", "category": "SUPPLIERS", "percent": "10"},
        {
            "type": "ONE_OFF",
            "day": "2026-11-11",
            "amount": "-5000.00",
            "category": "CAPEX",
            "reason": "New van",
        },
    ).json()
    assert r["matched"] == [1, 1]
    assert r["weeks"][1]["delta"] == "-5000.00"  # the van in week 2
    assert r["weeks"][2]["delta"] == "-5030.00"  # and 10% more to the supplier in week 3
    assert r["base_first_shortfall"] == {"date": "2026-11-04", "balance": "8000.00"}
    assert r["what_if_first_shortfall"] == {"date": "2026-11-04", "balance": "8000.00"}
    assert r["weeks"][3]["base_shortfall"] is False
    assert r["weeks"][3]["what_if_shortfall"] is True
    gone = what_if(
        fc, base["run_id"], {"type": "PCT_CHANGE", "category": "RENT", "percent": "-100"}
    ).json()
    assert gone["weeks"][-1]["delta"] == "3000.00"  # both rents removed


def test_overrides_are_checked(fc: dict[str, Any]) -> None:
    run_id = forecast(fc)["run_id"]
    for bad in (
        {"type": "TIMING_SHIFT", "days": 5},
        {"type": "TIMING_SHIFT", "party": "C1", "days": 0},
        {"type": "PCT_CHANGE", "category": "RENT", "percent": "0"},
        {"type": "PCT_CHANGE", "category": "RENT", "percent": "-150"},
        {"type": "ONE_OFF", "day": "2026-11-11", "amount": "10.00", "category": "X"},
        {"type": "ONE_OFF", "amount": "10.00", "category": "X", "reason": "y"},
        {"type": "GUESS"},
    ):
        assert what_if(fc, run_id, bad).status_code == 422, bad
    too_many = [{"type": "TIMING_SHIFT", "party": "C1", "days": 1}] * 21
    assert what_if(fc, run_id, *too_many).status_code == 422
    assert what_if(fc, run_id).status_code == 422


def test_viewers_may_explore_and_old_engines_are_refused(
    fc: dict[str, Any], make_user: Make, api_client: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = forecast(fc)["run_id"]
    viewer = join(
        fc["client"], fc["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    shift = {"type": "TIMING_SHIFT", "party": "C1", "days": 7}
    assert what_if(fc, run_id, shift, client=viewer).status_code == 200
    monkeypatch.setattr(engine_module.ENGINE, "version", "2")
    assert what_if(fc, run_id, shift).status_code == 409


# --- pure: overrides that change nothing give exactly the base ---


amounts = st.decimals(min_value=-50_000, max_value=50_000, places=2).filter(lambda a: a != 0)


@settings(max_examples=150, deadline=None)
@given(
    raw=st.lists(st.tuples(st.integers(min_value=-20, max_value=100), amounts), max_size=30),
    days=st.integers(min_value=-365, max_value=365).filter(lambda d: d != 0),
)
def test_an_override_matching_nothing_is_the_base(
    raw: list[tuple[int, Decimal]], days: int
) -> None:
    as_of = date(2026, 11, 4)
    flows = [flow(as_of + timedelta(days=d), f"{a:.2f}") for d, a in raw]
    base_inputs = inputs(as_of, flows)
    refs, matched = apply_overrides(
        dict(base_inputs.refs), [Override("TIMING_SHIFT", party="NOBODY", days=days)]
    )
    assert matched == [0]
    data = {ACCOUNT: Decimal("1000.00")}
    base = summarise(engine_module.ENGINE.compute(base_inputs, data))
    same = summarise(engine_module.ENGINE.compute(inputs(as_of, refs["flows"]), data))
    assert [w.closing for w in same.weeks] == [w.closing for w in base.weeks]
    assert same.first_shortfall == base.first_shortfall
    assert same.hypothetical == 0
