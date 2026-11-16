"""The core KPI library on a hand-computed fixture (M4-4: AC-KP1 to AC-KP3).

Fixture, Q1 2026 (90 days), all entries posted:
- before 2026: share capital 1,000 in cash; inventory 200 bought for cash; 2025 sales 800 in
  cash in February 2025 (not closed, so it is equity);
- Q1 2026: sales 1,000 on credit (C1), 500 of it collected; cost of sales 600 on credit (S1);
  rent 100, depreciation 50, interest 10 and income tax 40; a 300 short-term bank loan.

Figures: revenue 1,000; EBIT 250; EBITDA 300; net income 200. Opening: cash 1,600, inventory
200, equity 1,800 (assets 1,800). Closing: cash 2,290, receivables 500, inventory 200,
accumulated depreciation -50 (assets 2,940); payables 600, loan 300, tax 40 (current liabilities
940); equity 2,000.
"""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from fcp.modules.kpi.api import reference_functions
from fcp.modules.kpi.engine import Data, KpiSetEngine
from fcp.modules.kpi.library import seed_libraries
from fcp.modules.kpi.models import KpiDefinition
from fcp.modules.metrics.api import RunInputs, compile_expression

from ..ledger.conftest import books
from ..ledger.test_entries import act
from ..metrics.test_mapping import defaults

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]
Q1 = {"date_from": "2026-01-01", "date_to": "2026-03-31"}


def _post(k: dict[str, Any], day: str, *lines: tuple[str, str, str, str | None]) -> None:
    acc = k["accounts"]
    body = {
        "accounting_date": day,
        "description": "KPI fixture",
        "lines": [
            {
                "account_id": acc[code]["id"],
                "debit": dr,
                "credit": cr,
                **({"counterparty_id": k["parties"][party]} if party else {}),
            }
            for code, dr, cr, party in lines
        ],
    }
    draft = k["client"].post_json(f"{k['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    assert act(k, draft.json()["id"], "post").status_code == 200


@pytest.fixture
def k(books: dict[str, Any]) -> dict[str, Any]:
    c, base = books["client"], books["base"]
    c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"})
    c.post_json(f"{base}/fiscal-years", {"start_date": "2025-01-01"})
    defaults(books)
    books["parties"] = {}
    for code, kind in (("C1", "CUSTOMER"), ("S1", "SUPPLIER")):
        made = c.post_json(
            f"{base}/counterparties", {"code": code, "name": f"{code} (Demo)", "kind": kind}
        )
        books["parties"][code] = made.json()["id"]
    p = _post
    p(books, "2025-01-05", ("1300", "1000", "0", None), ("3000", "0", "1000", None))
    p(books, "2025-01-06", ("1100", "200", "0", None), ("1300", "0", "200", None))
    p(books, "2025-02-10", ("1300", "800", "0", None), ("4000", "0", "800", None))
    p(books, "2026-01-15", ("1200", "1000", "0", "C1"), ("4000", "0", "1000", None))
    p(books, "2026-02-10", ("5000", "600", "0", None), ("2100", "0", "600", "S1"))
    p(books, "2026-02-20", ("6100", "100", "0", None), ("1300", "0", "100", None))
    p(books, "2026-03-05", ("6600", "50", "0", None), ("1019", "0", "50", None))
    p(books, "2026-03-10", ("1300", "500", "0", None), ("1200", "0", "500", "C1"))
    p(books, "2026-03-15", ("7000", "10", "0", None), ("1300", "0", "10", None))
    p(books, "2026-03-20", ("1300", "300", "0", None), ("2150", "0", "300", None))
    p(books, "2026-03-25", ("7500", "40", "0", None), ("2130", "0", "40", None))
    return books


def run(k: dict[str, Any], period: dict[str, str] = Q1) -> dict[str, Any]:
    made = k["client"].post_json(f"{k['base']}/kpi-sets", period)
    assert made.status_code == 201, made.content
    body: dict[str, Any] = made.json()
    return body


def values(body: dict[str, Any]) -> dict[str, Decimal | str]:
    return {
        v["key"]: Decimal(v["value"]) if v["value"] is not None else v["nm_reason"]
        for v in body["values"]
    }


def close(a: Decimal | str, b: str) -> bool:
    return isinstance(a, Decimal) and abs(a - Decimal(b)) < Decimal("1e-15")


def test_every_core_kpi_matches_the_hand_computed_value(k: dict[str, Any]) -> None:
    body = run(k)
    assert body["status"] == "VALID"
    assert body["library"] == "CORE@1.0"
    assert body["unmapped_accounts"] == 0
    v = values(body)
    expected = {
        "GROSS_MARGIN": "0.4",
        "OPERATING_MARGIN": "0.25",
        "EBITDA_MARGIN": "0.3",
        "NET_MARGIN": "0.2",
        "ROA": str(Decimal(200) * Decimal(365) / Decimal(90) / Decimal(2370)),
        "ROE": str(Decimal(200) * Decimal(365) / Decimal(90) / Decimal(1900)),
        "CURRENT_RATIO": str(Decimal(2990) / Decimal(940)),
        "QUICK_RATIO": str(Decimal(2790) / Decimal(940)),
        "CASH_RATIO": str(Decimal(2290) / Decimal(940)),
        "DSO": "22.5",
        "DPO": "45",
        "DIO": "30",
        "CCC": "7.5",
        "REVENUE_GROWTH": "0.25",
        "EBITDA_GROWTH": "-0.625",
        "NET_PROFIT_GROWTH": "-0.75",
        "DEBT_TO_EQUITY": "0.15",
        "INTEREST_COVERAGE": "25",
    }
    for key, want in expected.items():
        assert close(v[key], want), (key, v[key], want)
    # Cash grew over the 3 months (1,600 to 2,290): not burning, so no runway.
    assert v["CASH_RUNWAY"] == "Not burning cash: it did not decrease over the last 3 months"
    first = body["values"][0]
    assert (first["nature"], first["definition_id"], first["display"]) == (
        "ACTUAL",
        "CORE@1.0:GROSS_MARGIN",
        "percent",
    )


def test_not_meaningful_values_have_a_reason_never_zero(k: dict[str, Any]) -> None:
    # April 2026 has no postings: no revenue, cost of sales or interest.
    april = values(run(k, {"date_from": "2026-04-01", "date_to": "2026-04-30"}))
    for key in (
        "GROSS_MARGIN",
        "NET_MARGIN",
        "DSO",
        "DPO",
        "DIO",
        "CCC",
        "INTEREST_COVERAGE",
        "REVENUE_GROWTH",
    ):
        assert isinstance(april[key], str), key
        assert "zero" in str(april[key]) or "no interest" in str(april[key]), (key, april[key])
    assert april["GROSS_MARGIN"] == "Revenue is zero"
    assert april["REVENUE_GROWTH"] == "The same period a year earlier is zero"
    assert april["INTEREST_COVERAGE"] == "There is no interest expense"
    assert close(april["CURRENT_RATIO"], str(Decimal(2990) / Decimal(940)))


def test_drill_down_reproducibility_and_latest(k: dict[str, Any]) -> None:
    body = run(k)
    dso = next(v for v in body["values"] if v["key"] == "DSO")
    explained = (
        k["client"]
        .get(f"{k['base']}/calc-runs/{body['run_id']}/results/{dso['result_id']}/explain")
        .json()
    )
    refs = {(ln["input_kind"], ln["input_ref"]) for ln in explained["lineage"]}
    assert ("FORMULA", "CORE@1.0:DSO") in refs
    ar = k["accounts"]["1200"]["id"]
    sales = k["accounts"]["4000"]["id"]
    amounts = {ln["input_ref"]: ln["amount"] for ln in explained["lineage"]}
    assert Decimal(amounts[f"account:{ar}:closing"]) == 500
    assert Decimal(amounts[f"account:{sales}:flow"]) == 1000
    again = k["client"].post_json(f"{k['base']}/calc-runs/{body['run_id']}/reproduce", {})
    assert again.status_code == 200, again.content
    assert again.json()["reproduced"] is True
    latest = k["client"].get(f"{k['base']}/kpi-sets/latest?date_from=2026-01-01&date_to=2026-03-31")
    assert latest.json()["run_id"] == body["run_id"]
    assert latest.json()["stale"] is False
    _post(k, "2026-03-30", ("6100", "5", "0", None), ("1300", "0", "5", None))
    later = k["client"].get(f"{k['base']}/kpi-sets/latest?date_from=2026-01-01&date_to=2026-03-31")
    assert later.json()["stale"] is True  # posted after the run: calculate again
    assert (
        k["client"]
        .get(f"{k['base']}/kpi-sets/latest?date_from=2026-02-01&date_to=2026-02-28")
        .status_code
        == 404
    )
    definitions = k["client"].get(f"{k['base']}/kpi-definitions").json()
    assert len(definitions) == 19
    assert all(d["convention"] and d["example"] for d in definitions)


@pytest.mark.parametrize(
    "period",
    [
        {"date_from": "2026-01-02", "date_to": "2026-03-31"},
        {"date_from": "2026-01-01", "date_to": "2026-03-30"},
        {"date_from": "2026-03-01", "date_to": "2026-01-31"},
        {"date_from": "2025-01-01", "date_to": "2026-01-31"},
    ],
)
def test_periods_are_whole_months_up_to_a_year(k: dict[str, Any], period: dict[str, str]) -> None:
    assert k["client"].post_json(f"{k['base']}/kpi-sets", period).status_code == 422


def test_negative_equity_and_cash_burn_in_the_pure_engine() -> None:
    """Without the database: equity below zero makes ROE and debt-to-equity not meaningful, and a
    falling cash balance gives a runway in months."""
    cash, debt, capital, sales = (str(uuid4()) for _ in range(4))
    inputs = RunInputs(
        "KPI_SET",
        "1",
        uuid4(),
        date(2026, 3, 31),
        1,
        {
            "date_from": "2026-01-01",
            "date_to": "2026-03-31",
            "library": "TEST",
            "accounts": {
                cash: ["BS.CASH", "CURRENT_ASSETS", False, False],
                debt: ["BS.DEBT.CURRENT", "CURRENT_LIABILITIES", True, False],
                capital: ["BS.EQUITY.SHARE_CAPITAL", "EQUITY", True, False],
                sales: ["REV.SALES", "REVENUE", True, True],
            },
        },
    )
    defs = [
        {"id": f"TEST:{key}", "key": key, "formula": formula, "nm_reason": reason}
        for key, formula, reason in (
            ("ROE", 'divide_positive(flow("REVENUE"), avg_balance("EQUITY"))', ""),
            ("DE", 'divide_positive(balance("BS.DEBT"), balance("EQUITY"))', ""),
            ("RUNWAY", 'divide_positive(balance("BS.CASH"), burn_3m())', "Not burning"),
        )
    ]
    d = Decimal
    data = Data(
        defs,
        {(sales, date(2026, 1, 1)): d(-100)},
        {
            date(2026, 1, 1): {cash: d(900), debt: d(-1000), capital: d(100)},
            date(2026, 4, 1): {cash: d(600), debt: d(-1000), capital: d(100), sales: d(-100)},
        },
    )
    out = {v.series_key: v for v in KpiSetEngine().compute(inputs, data).values}
    # Equity: capital -100 (a debit balance) + result 100 -> 0 at the end, -100 at the start.
    assert out["kpi.ROE"].value is None
    assert "positive" in out["kpi.ROE"].nm_reason
    assert out["kpi.DE"].value is None
    assert out["kpi.RUNWAY"].value == d(6)  # 600 cash, falling 300 in 3 months (100 a month)


def test_every_library_formula_compiles_with_the_documented_unit() -> None:
    assert seed_libraries() == 19  # idempotent at runtime too
    units = {
        "percent": "ratio",
        "ratio": "ratio",
        "times": "ratio",
        "months": "ratio",
        "days": "days",
        "EUR": "EUR",
    }
    functions = reference_functions()
    assert {f.name for f in functions} == {
        "flow",
        "prior_flow",
        "balance",
        "opening",
        "avg_balance",
        "days",
        "annual_factor",
        "burn_3m",
        "count_metric",
        "amount_metric",
    }
    for d in KpiDefinition.objects.all():
        compiled = compile_expression(d.formula, functions=functions)
        assert compiled.unit == units[d.display], (d.key, compiled.unit)
