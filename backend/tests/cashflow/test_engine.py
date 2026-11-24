"""The CASH_13W engine against an independent reference calculation (M3-7, AC-CW3, AC-CW4).

``reference`` is written separately and plainly: its own week boundaries, a day-by-day running
balance, no shared code with the engine. Both must agree to the cent for any inputs.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.modules.cashflow.engine import ENGINE, KIND
from fcp.modules.metrics.api import Nature, RunInputs

D = Decimal
ACCOUNT = str(uuid4())


def inputs(
    as_of: date, flows: list[dict[str, str]], minimum: str = "0.00", limits: str = "0.00"
) -> RunInputs:
    return RunInputs(
        KIND,
        "1",
        uuid4(),
        as_of,
        1,
        {
            "weeks": 13,
            "cash_accounts": [ACCOUNT],
            "minimum_cash": minimum,
            "facility_limits": limits,
            "flows": flows,
            "warnings": [],
        },
    )


def flow(
    day: date,
    amount: str,
    nature: str = "COMMITTED",
    category: str = "CUSTOMERS",
    source: str = "RECEIVABLE",
) -> dict[str, str]:
    return {
        "day": day.isoformat(),
        "amount": amount,
        "nature": nature,
        "category": category,
        "source": source,
        "ref": f"x:{uuid4()}",
    }


def reference(
    opening: Decimal, flows: list[dict[str, str]], as_of: date, minimum: Decimal
) -> tuple[list[Decimal], tuple[date, Decimal] | None]:
    first_end = as_of + timedelta(days=6 - as_of.weekday())
    ends = [first_end + timedelta(weeks=i) for i in range(13)]
    by_day: dict[date, Decimal] = {}
    for f in flows:
        day = max(date.fromisoformat(f["day"]), as_of)
        if day <= ends[-1]:
            by_day[day] = by_day.get(day, D(0)) + D(f["amount"])
    closings, balance, shortfall = [], opening, None
    if opening < minimum:
        shortfall = (as_of, opening)
    day = as_of
    while day <= ends[-1]:
        balance += by_day.get(day, D(0))
        if shortfall is None and balance < minimum:
            shortfall = (day, balance)
        if day in ends:
            closings.append(balance)
        day += timedelta(days=1)
    return closings, shortfall


def run(
    as_of: date,
    opening: str,
    flows: list[dict[str, str]],
    minimum: str = "0.00",
    limits: str = "0.00",
) -> dict[str, Any]:
    out = ENGINE.compute(inputs(as_of, flows, minimum, limits), {ACCOUNT: D(opening)})
    weekly: dict[str, list[Any]] = {}
    for v in out.values:
        if v.granularity == "WEEK" and v.series_key != "cash.flow":
            weekly.setdefault(v.series_key, []).append(v)
    singles = {v.series_key: v for v in out.values if v.granularity == "POINT"}
    return {"out": out, "weekly": weekly, "singles": singles}


def test_a_small_forecast_by_hand() -> None:
    as_of = date(2026, 11, 4)  # a Wednesday: week 1 is 4-8 Nov
    flows = [
        flow(date(2026, 10, 20), "500.00"),  # overdue receivable: first week, flagged
        flow(date(2026, 11, 6), "-1500.00", category="RENT", source="OBLIGATION"),
        flow(date(2026, 11, 10), "-200.00", "EXPECTED", "UTILITIES", "OBLIGATION"),
        flow(date(2026, 11, 12), "-300.00", category="SUPPLIERS", source="PAYABLE"),
        flow(date(2027, 3, 1), "999.00"),  # beyond the 13 weeks
    ]
    r = run(as_of, "1000.00", flows, minimum="100.00", limits="2000.00")
    closing = [v.value for v in r["weekly"]["cash.closing"]]
    assert closing[:3] == [D("0.00"), D("-500.00"), D("-500.00")]
    assert [v.value for v in r["weekly"]["cash.opening"][:2]] == [D("1000.00"), D("0.00")]
    assert r["weekly"]["cash.opening"][0].nature is Nature.ACTUAL
    assert r["weekly"]["cash.opening"][1].nature is Nature.FORECAST
    assert [v.value for v in r["weekly"]["cash.inflows"][:2]] == [D("500.00"), D(0)]
    assert [v.value for v in r["weekly"]["cash.outflows"][:2]] == [D("1500.00"), D("500.00")]
    assert [v.value for v in r["weekly"]["cash.shortfall"][:2]] == [D(1), D(1)]
    assert [v.value for v in r["weekly"]["cash.headroom"][:2]] == [D("-100.00"), D("-600.00")]
    assert r["weekly"]["cash.liquidity"][1].value == D("1500.00")  # -500 + 2,000 of facilities
    assert r["weekly"]["cash.undrawn_facilities"][1].value == D("1500.00")
    assert r["weekly"]["cash.undrawn_facilities"][0].value == D("2000.00")
    assert r["weekly"]["cash.minimum"][0].nature is Nature.TARGET
    assert (
        r["singles"]["cash.first_shortfall"].period_start,
        r["singles"]["cash.first_shortfall"].value,
    ) == (date(2026, 11, 6), D("0.00"))
    assert r["singles"]["cash.overdue"].value == D("500.00")
    assert r["singles"]["cash.beyond_horizon"].value == D("999.00")
    assert all(r["out"].invariants.values()), r["out"].invariants
    week1 = [v for v in r["out"].values if v.series_key == "cash.flow" and v.period_start == as_of]
    assert sorted((v.dimensions, v.nature, v.value) for v in week1) == [
        (("IN", "CUSTOMERS"), Nature.COMMITTED, D("500.00")),
        (("OUT", "RENT"), Nature.COMMITTED, D("1500.00")),
    ]
    overdue = next(v for v in week1 if v.dimensions == ("IN", "CUSTOMERS"))
    assert overdue.lineage[0].kind == "OPEN_ITEM"
    assert overdue.lineage[0].note == "overdue"
    week2 = [
        v
        for v in r["out"].values
        if v.series_key == "cash.flow" and v.period_start == date(2026, 11, 9)
    ]
    assert {(v.dimensions[1], v.nature) for v in week2} == {
        ("UTILITIES", Nature.EXPECTED),
        ("SUPPLIERS", Nature.COMMITTED),
    }


def test_opening_below_minimum_is_a_shortfall_at_once() -> None:
    r = run(date(2026, 11, 4), "50.00", [], minimum="100.00")
    assert r["singles"]["cash.first_shortfall"].period_start == date(2026, 11, 4)
    assert "cash.first_shortfall" not in run(date(2026, 11, 4), "50.00", [])["singles"]


def test_no_cash_accounts() -> None:
    out = ENGINE.compute(RunInputs(KIND, "1", uuid4(), date(2026, 11, 4), 0, {"flows": []}), {})
    closing = [v.value for v in out.values if v.series_key == "cash.closing"]
    assert closing == [D(0)] * 13
    assert all(out.invariants.values())


amounts = st.decimals(min_value=-50_000, max_value=50_000, places=2).filter(lambda a: a != 0)


@settings(max_examples=300, deadline=None)
@given(
    as_of=st.dates(min_value=date(2024, 1, 1), max_value=date(2030, 12, 31)),
    opening=st.decimals(min_value=-10_000, max_value=100_000, places=2),
    minimum=st.decimals(min_value=0, max_value=20_000, places=2),
    raw=st.lists(
        st.tuples(
            st.integers(min_value=-40, max_value=110),
            amounts,
            st.sampled_from(["COMMITTED", "EXPECTED"]),
        ),
        max_size=40,
    ),
)
def test_matches_the_reference_for_any_flows(
    as_of: date, opening: Decimal, minimum: Decimal, raw: list[tuple[int, Decimal, str]]
) -> None:
    flows = [flow(as_of + timedelta(days=d), f"{a:.2f}", n) for d, a, n in raw]
    r = run(as_of, f"{opening:.2f}", flows, minimum=f"{minimum:.2f}")
    closings, shortfall = reference(opening, flows, as_of, minimum)
    assert [v.value for v in r["weekly"]["cash.closing"]] == closings
    got = r["singles"].get("cash.first_shortfall")
    assert (None if got is None else (got.period_start, got.value)) == shortfall
    opens = [v.value for v in r["weekly"]["cash.opening"]]
    assert opens == [opening, *closings[:-1]]  # opening(t+1) = closing(t)
    assert all(r["out"].invariants.values())
    beyond = sum(
        (
            D(f["amount"])
            for f in flows
            if date.fromisoformat(f["day"]) > as_of + timedelta(days=6 - as_of.weekday(), weeks=12)
        ),
        D(0),
    )
    assert r["singles"]["cash.beyond_horizon"].value == beyond
