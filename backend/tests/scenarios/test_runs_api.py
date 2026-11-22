"""Scenario runs through the API (M7-2): the comparison with the base, a saved run that is never
published, promotion to an assumption-set draft, and permissions."""

from collections.abc import Callable
from typing import Any

import pytest

from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def plan(books: dict[str, Any]) -> dict[str, Any]:
    """An approved 12-month set from 31/12/2026: sales 1,000 a month at a 40% margin, rent 300;
    loan TERM-1 of 30,000 drawn in February 2027 (5%, 36 months)."""
    c, base = books["client"], books["base"]
    made = c.post_json(
        f"{base}/assumption-sets",
        {"name": "Plan", "cutover": "2026-12-31", "months": 12, "start_from": "EMPTY"},
    ).json()
    url = f"{base}/assumption-sets/{made['id']}"
    months = [f"2027-{m:02d}-01" for m in range(1, 13)]
    changes = [
        {"driver": "revenue", "line": "REV.SALES", "month": m, "value": "1000"} for m in months
    ]
    changes += [{"driver": "gross_margin", "month": m, "value": "40"} for m in months]
    changes += [{"driver": "opex", "line": "OPEX.RENT", "month": m, "value": "300"} for m in months]
    assert c.put_json(f"{url}/values", {"changes": changes}).status_code == 200
    assert (
        c.post_json(
            f"{url}/loans",
            {
                "code": "TERM-1",
                "name": "Term loan",
                "kind": "NEW",
                "structure": "ANNUITY",
                "term_months": 36,
                "annual_rate": "5",
                "amount": "30000",
                "drawdown_month": "2027-02-01",
            },
        ).status_code
        == 201
    )
    assert c.post_json(f"{url}/approve", {}).status_code == 200
    books["set_id"] = made["id"]
    books["url"] = f"{base}/scenarios"
    return books


def scenario(p: dict[str, Any], *overrides: tuple[str, dict[str, Any]]) -> str:
    c = p["client"]
    s = c.post_json(p["url"], {"name": "Downside", "base_set_id": p["set_id"]}).json()
    for kind, params in overrides:
        added = c.post_json(f"{p['url']}/{s['id']}/overrides", {"type": kind, "params": params})
        assert added.status_code == 201, added.content
    return f"{p['url']}/{s['id']}"


def test_comparison_save_and_promote(plan: dict[str, Any]) -> None:
    c = plan["client"]
    surl = scenario(plan,
                    ("PCT_CHANGE", {"driver": "revenue", "percent": "-25",
                                    "start_month": "2027-07"}),
                    ("RATE_CHANGE", {"target": "LOANS", "loans": ["TERM-1"], "points": "2"}),
                    ("NEW_DEBT", {"code": "NEW-1", "amount": "10000", "drawdown_month": "2027-03",
                                  "term_months": 24, "annual_rate": "6",
                                  "structure": "EQUAL_PRINCIPAL"}))  # fmt: skip
    got = c.get(f"{surl}/comparison")
    assert got.status_code == 200, got.content
    cmp = got.json()
    assert (cmp["nature"], cmp["valid"], cmp["failures"]) == ("HYPOTHETICAL", True, [])
    assert cmp["engine_status"] == "PENDING_PROFESSIONAL_REVIEW"
    assert cmp["columns"][0] == {"start": "2026-12-01", "end": "2026-12-31", "nature": "ACTUAL"}
    assert {x["nature"] for x in cmp["columns"][1:]} == {"HYPOTHETICAL"}
    rows = {r["key"]: r for r in cmp["rows"]}
    revenue = rows["PL.REVENUE"]
    # July: 1,000 - 25% = 750; changed by the first override only.
    july = 7  # the opening column comes first
    assert (revenue["base"][july], revenue["scenario"][july],
            revenue["difference"][july]) == ("1000.00", "750.00", "-250.00")  # fmt: skip
    first = cmp["effects"][0]["override_id"]
    assert revenue["overrides"][july] == [first]
    assert revenue["overrides"][6] == []  # June: unchanged
    # What changed and why: revenue -250 x 6 months, all from override 1; the total adds up.
    effects = cmp["effects"]
    assert [e["type"] for e in effects] == ["PCT_CHANGE", "RATE_CHANGE", "NEW_DEBT", "TOTAL"]
    assert effects[0]["changes"]["PL.REVENUE"] == "-1500.00"
    assert effects[-1]["changes"]["PL.REVENUE"] == "-1500.00"
    debt = [e["changes"]["BS.DEBT"] for e in effects]
    assert sum(float(x) for x in debt[:-1]) == pytest.approx(float(debt[-1]))
    assert float(effects[2]["changes"]["BS.DEBT"]) > 0  # the new loan is still owed
    assert set(cmp["liquidity"]) == {"base", "scenario"}
    yearly = c.get(f"{surl}/comparison?granularity=YEAR").json()
    assert len(yearly["columns"]) == 2  # the opening and 2027
    assert {r["key"]: r for r in yearly["rows"]}["PL.REVENUE"]["difference"][1] == "-1500.00"

    saved = c.post_json(f"{surl}/runs", {})
    assert saved.status_code == 201, saved.content
    run = saved.json()
    assert (run["status"], run["stale"]) == ("VALID", False)
    assert [r["id"] for r in c.get(f"{surl}/runs").json()] == [run["id"]]
    published = c.post_json(f"{plan['base']}/calc-runs/{run['id']}/publish", {})
    assert published.status_code == 409
    assert "never published" in published.json()["detail"]
    again = c.post_json(f"{surl}/runs", {}).json()
    assert again["output_hash"] == run["output_hash"]  # same inputs, same result

    promoted = c.post_json(f"{surl}/promote", {"name": "Plan (downside)"})
    assert promoted.status_code == 201, promoted.content
    made = promoted.json()
    assert (made["name"], made["status"]) == ("Plan (downside)", "DRAFT")
    grid = c.get(f"{plan['base']}/assumption-sets/{made['assumption_set_id']}").json()
    r = {(x["driver"], x["line"]): x for x in grid["rows"]}
    sales = r[("revenue", "REV.SALES")]
    assert sales["values"][5:7] == ["1000", "750"]
    assert sales["sources"][6] == "MANUAL"
    assert r[("loan_rate", "TERM-1")]["values"][0] == "7"
    loans = c.get(f"{plan['base']}/assumption-sets/{made['assumption_set_id']}/loans").json()
    assert sorted(x["code"] for x in loans) == ["NEW-1", "TERM-1"]


def test_refusals_and_permissions(plan: dict[str, Any], make_user: Make,
                                  api_client: Make) -> None:  # fmt: skip
    c = plan["client"]
    settle = scenario(plan, ("ONE_OFF", {"amount": "100", "month": "2027-01",
                                         "treatment": "LIABILITY_SETTLEMENT",
                                         "liability": "BS.TAX_PAY"}))  # fmt: skip
    refused = c.get(f"{settle}/comparison")
    assert refused.status_code == 422  # no tax payable in the books to settle
    assert "more than its balance at the cut-over (0.00)" in refused.json()["detail"]
    empty = scenario(plan)
    assert c.post_json(f"{empty}/promote", {}).status_code == 409
    nothing = c.get(f"{empty}/comparison").json()
    assert all(e["changes"][k] == "0.00" for e in nothing["effects"] for k in e["changes"])
    assert all(r["base"] == r["scenario"] for r in nothing["rows"])

    c.post_json(f"{empty}/share", {})
    viewer = join(c, plan["ws"]["slug"], make_user("viewer@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{empty}/comparison").status_code == 403
    assert viewer.post_json(f"{empty}/runs", {}).status_code == 403
    assert viewer.get(f"{empty}/runs").status_code == 200
