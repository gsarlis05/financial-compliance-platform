"""Scenario runs on a synthetic base (M7-2): every figure below is worked out by hand from the base;
properties hold for random scenarios (AC-SC2, AC-SC3, AC-SC4)."""

import re
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.core.errors import ValidationFailedError
from fcp.modules.metrics.api import Nature
from fcp.modules.projections.api import EngineInput, LoanTerms, Projection, project
from fcp.modules.scenarios.apply import Item, apply
from fcp.modules.scenarios.runs import _effects, hypothetical, steps

D = Decimal
MONTHS = [date(2027, m, 1) for m in range(1, 13)]


def base() -> EngineInput:
    """Cash 17,000; other payables 2,000; a term loan of 5,000 at 5% (60 months); share capital
    10,000. Sales 10,000 a month at a 40% margin; payroll 2,000 and rent 1,000; DSO 30, DPO 20;
    no tax rules (no income tax), no capex."""
    every = {m: D(0) for m in MONTHS}
    drivers = {
        ("revenue", "REV.SALES"): {m: D(10000) for m in MONTHS},
        ("gross_margin", ""): {m: D(40) for m in MONTHS},
        ("opex", "OPEX.PAYROLL"): {m: D(2000) for m in MONTHS},
        ("opex", "OPEX.RENT"): {m: D(1000) for m in MONTHS},
        ("dso", ""): {m: D(30) for m in MONTHS},
        ("dpo", ""): {m: D(20) for m in MONTHS},
        ("interest_rate", ""): dict(every),
        ("capex", ""): dict(every),
        ("capex_life", ""): {m: D(60) for m in MONTHS},
        ("loan_rate", "TERM-1"): {m: D(5) for m in MONTHS},
    }
    return EngineInput(
        set_id="base", cutover=date(2026, 12, 31), months=MONTHS,
        opening={"BS.CASH": D(17000), "BS.OTHER_PAY": D(2000), "BS.DEBT.NONCURRENT": D(5000),
                 "BS.EQUITY.SHARE_CAPITAL": D(10000)},
        drivers=drivers, register_depreciation={},
        loans=(LoanTerms("TERM-1", "ANNUITY", 60, D(5), opening=D(5000),
                         rate_path={m: D(5) for m in MONTHS}),),
    )  # fmt: skip


def item(seq: int, kind: str, **params: Any) -> Item:
    window = {"start_month": "2027-01-01", "end_month": "2027-12-01"}
    if kind in ("PCT_CHANGE", "ABS_CHANGE", "TIMING_SHIFT", "NEW_HIRE"):
        params = {**window, **params}
    return Item(f"o{seq}", seq, kind, params)


def month_value(p: Projection, month: int, key: str) -> Decimal:
    m = p.months[month - 1]
    return {**m.pl, **m.bs, **m.cf}[key]


def test_no_overrides_is_the_base_exactly() -> None:
    inp = base()
    assert apply(inp, []).inp is inp
    s = steps(inp, [])
    out = hypothetical(s)
    base_values = project(inp)[1].values
    assert [replace(v, nature=Nature.HYPOTHETICAL if v.nature == Nature.FORECAST else v.nature)
            for v in base_values] == list(out.values)  # fmt: skip
    assert {v.nature for v in out.values} == {Nature.ACTUAL, Nature.HYPOTHETICAL}
    assert all(out.invariants.values())


def test_each_type_by_hand() -> None:
    inp = base()
    items = [
        item(1, "PCT_CHANGE", driver="revenue", lines=[], percent="-10", start_month="2027-03-01"),
        item(2, "NEW_HIRE", role="Analyst", department="", headcount=1,
             gross_monthly_salary="3000.00", employer_cost_percent="10",
             employer_cost_source="Payroll adviser", start_month="2027-06-01"),
        item(3, "ONE_OFF", amount="500.00", month="2027-02-01",
             treatment="LIABILITY_SETTLEMENT", liability="BS.OTHER_PAY"),
        item(4, "RATE_CHANGE", target="LOANS", loans=["TERM-1"], points="2",
             from_month="2027-01-01"),
        item(5, "CAPEX", amount="12000.00", month="2027-04-01", useful_life_months=48,
             funding="CASH"),
    ]  # fmt: skip
    s = steps(inp, items)
    p = s.final
    # Revenue -10% from March: 9,000; cost of sales 60% = 5,400; costs 3,000 (+ 3,300 from June).
    assert month_value(p, 2, "PL.REVENUE") == D("10000.00")
    assert month_value(p, 3, "PL.REVENUE") == D("9000.00")
    assert month_value(p, 3, "PL.COGS") == D("5400.00")
    assert month_value(p, 5, "PL.OPEX.PAYROLL") == D("2000.00")
    assert month_value(p, 6, "PL.OPEX.PAYROLL") == D("5300.00")  # + 3,000 x 1.10
    # Settling 500 of other payables in February: the line falls, operating cash pays it.
    assert month_value(p, 1, "BS.OTHER_PAY") == D("2000.00")
    assert month_value(p, 2, "BS.OTHER_PAY") == D("1500.00")
    assert month_value(p, 2, "CF.SETTLEMENTS") == D("-500.00")
    # The loan at 7% instead of 5%: January interest 5,000 x 7% / 12 = 29.17 (base 20.83).
    assert month_value(s.base, 1, "PL.INTEREST") == D("20.83")
    assert month_value(p, 1, "PL.INTEREST") == D("29.17")
    # Capex 12,000 in April over 48 months, from May: 250 a month.
    assert month_value(p, 4, "PL.DA") == D("0.00")
    assert month_value(p, 5, "PL.DA") == D("250.00")
    assert month_value(p, 4, "CF.CAPEX") == D("-12000.00")
    assert all(hypothetical(s).invariants.values())
    # What changed and why: the effects add up to the total.
    effects = _effects(s)
    total = effects[-1]
    assert total.type == "TOTAL"
    for headline, change in total.changes.items():
        assert sum((e.changes[headline] for e in effects[:-1]), D(0)) == change
    # Revenue: 10 months x -1,000 = -10,000, all from override 1.
    assert effects[0].changes["PL.REVENUE"] == D("-10000.00")
    assert total.changes["PL.REVENUE"] == D("-10000.00")
    assert effects[1].changes["PL.REVENUE"] == D("0.00")
    # The settlement is not something an assumption set can hold.
    assert s.applied.inexpressible == [
        "Override 3 (ONE_OFF): an assumption set cannot settle a liability"
    ]


def test_lineage_names_each_override_and_its_effect() -> None:
    s = steps(
        base(),
        [
            item(1, "ABS_CHANGE", driver="opex", line="OPEX.RENT", amount="100.00"),
            item(2, "ABS_CHANGE", driver="opex", line="OPEX.RENT", amount="50.00"),
        ],
    )
    out = hypothetical(s)
    rent = next(v for v in out.values if v.series_key == "PL.OPEX.RENT"
                and v.granularity == "MONTH" and v.period_start == MONTHS[0])  # fmt: skip
    effects = [(x.ref, x.amount) for x in rent.lineage if x.ref.startswith("scenario_override:")]
    assert effects == [("scenario_override:o1", D("100.00")), ("scenario_override:o2", D("50.00"))]
    assert rent.value == D("1150.00")
    assert rent.nature == Nature.HYPOTHETICAL


def test_timing_capex_and_refusals() -> None:
    inp = base()
    moved = apply(inp, [item(1, "TIMING_SHIFT", mode="MONTHS", driver="revenue",
                             line="REV.SALES", months=1)])  # fmt: skip
    sales = moved.inp.drivers[("revenue", "REV.SALES")]
    assert (sales[MONTHS[0]], sales[MONTHS[1]]) == (D(0), D(10000))
    assert moved.notes == ["Override 1 (TIMING_SHIFT): 10000.00 of REV.SALES moved outside "
                           "the window."]  # fmt: skip
    days = apply(inp, [item(1, "TIMING_SHIFT", mode="DAYS", driver="dso", days=15)])
    assert days.inp.drivers[("dso", "")][MONTHS[0]] == D(45)

    # Capex in a month with capex of another life cannot be held by an assumption set.
    with_capex = replace(inp, drivers={**inp.drivers, ("capex", ""): {MONTHS[3]: D(1000)}})
    clash = apply(with_capex, [item(1, "CAPEX", amount="500.00", month="2027-04-01",
                                    useful_life_months=24, funding="LOAN", term_months=12,
                                    annual_rate="4", structure="ANNUITY")])  # fmt: skip
    assert len(clash.inp.extra_capex) == 1
    assert clash.inexpressible
    assert [x.code for x in clash.new_loans] == ["CAPEX-1"]
    assert all(project(clash.inp)[1].invariants.values())

    for refused, message in (
        (item(1, "ABS_CHANGE", driver="opex", line="OPEX.RENT", amount="-1500.00"),
         "OPEX.RENT would be negative in 01/2027"),
        (item(1, "ONE_OFF", amount="2500.00", month="2027-01-01",
              treatment="LIABILITY_SETTLEMENT", liability="BS.OTHER_PAY"),
         "more than its balance at the cut-over (2000.00)"),
        (item(1, "TIMING_SHIFT", mode="DAYS", driver="dpo", days=-30), "DPO would be negative"),
        (item(1, "NEW_DEBT", code="TERM-1", name="", amount="1.00", drawdown_month="2027-01-01",
              term_months=12, annual_rate="1", structure="BULLET", interest_only_months=0),
         "a loan TERM-1 already exists"),
        (item(1, "RATE_CHANGE", target="ALL", points="-6", from_month="2027-01-01"),
         "would be negative"),
    ):  # fmt: skip
        with pytest.raises(ValidationFailedError, match=re.escape(message)):
            apply(inp, [refused])


OVERRIDES = st.one_of(
    st.builds(lambda pct: ("PCT_CHANGE", {"driver": "revenue", "lines": [], "percent": pct}),
              st.integers(-50, 50).filter(bool).map(str)),
    st.builds(lambda amt: ("ABS_CHANGE", {"driver": "opex", "line": "OPEX.RENT", "amount": amt}),
              st.integers(1, 5000).map(lambda x: f"{x}.25")),
    st.builds(lambda d: ("TIMING_SHIFT", {"mode": "DAYS", "driver": "dso", "days": d}),
              st.integers(1, 90)),
    st.builds(lambda hc: ("NEW_HIRE", {"role": "R", "department": "", "headcount": hc,
                                       "gross_monthly_salary": "2500.00",
                                       "employer_cost_percent": "12.5",
                                       "employer_cost_source": "test"}), st.integers(1, 4)),
    st.builds(lambda m, life: ("CAPEX", {"amount": "9000.00", "month": f"2027-{m:02d}-01",
                                         "useful_life_months": life, "funding": "CASH"}),
              st.integers(1, 12), st.integers(1, 120)),
    st.builds(lambda m, rate: ("NEW_DEBT", {
        "code": f"N{m}", "name": "", "amount": "20000.00", "drawdown_month": f"2027-{m:02d}-01",
        "term_months": 36, "annual_rate": rate, "structure": "EQUAL_PRINCIPAL",
        "interest_only_months": 3}), st.integers(1, 12), st.sampled_from(["0", "4.5", "9"])),
    st.builds(lambda pts, m: ("RATE_CHANGE", {"target": "ALL", "points": pts,
                                              "from_month": f"2027-{m:02d}-01"}),
              st.sampled_from(["0.5", "1", "3.25"]), st.integers(1, 12)),
    st.builds(lambda m: ("ONE_OFF", {"amount": "750.00", "month": f"2027-{m:02d}-01",
                                     "treatment": "EXPENSE", "line": "OPEX.OTHER"}),
              st.integers(1, 12)),
)  # fmt: skip


@settings(max_examples=40, deadline=None)
@given(st.lists(OVERRIDES, max_size=6, unique_by=lambda x: (x[0], x[1].get("code"))))
def test_any_scenario_keeps_the_invariants_and_its_effects_add_up(
        drawn: list[tuple[str, dict[str, Any]]]) -> None:  # fmt: skip
    items = [item(n, kind, **params) for n, (kind, params) in enumerate(drawn, start=1)]
    s = steps(base(), items)
    out = hypothetical(s)
    assert all(out.invariants.values()), {k: v for k, v in out.invariants.items() if not v}
    effects = _effects(s)
    for headline, change in effects[-1].changes.items():
        assert sum((e.changes[headline] for e in effects[:-1]), D(0)) == change
    base_values = {(v.series_key, v.period_start, v.granularity): v.value
                   for v in s.outputs[0].values}  # fmt: skip
    for v in out.values:
        if v.granularity != "MONTH" or v.nature == Nature.ACTUAL:
            continue
        shift = sum((x.amount or D(0) for x in v.lineage
                     if x.ref.startswith("scenario_override:")), D(0))  # fmt: skip
        before = base_values.get((v.series_key, v.period_start, v.granularity)) or D(0)
        assert (v.value or D(0)) - before == shift, v.series_key
