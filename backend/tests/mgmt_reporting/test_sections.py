"""Pack sections, comparison columns, commentary and risks (M8-2, AC-MR4).

The golden budget variance pack, worked by hand on the goals fixture (a 2026 budget of sales 1,000,
cost of sales 600, rent 100 and depreciation 50 a month; 2026 actuals: sales 1,000 in January, cost
of sales 600 and rent 100 in February, depreciation 50 in March; 2025: sales 800 in February):

| March 2026        | Actual | Budget | Original | Prior year | Variance | %       | Assessment   |
|-------------------|--------|--------|----------|------------|----------|---------|--------------|
| Sales             | 0      | 1,000  | 1,000    | 0          | -1,000   | -100.00 | Unfavourable |
| Cost of sales     | 0      | 600    | 600      | 0          | -600     | -100.00 | Favourable   |
| Rent              | 0      | 100    | 100      | 0          | -100     | -100.00 | Favourable   |
| Depreciation      | 50     | 50     | 50       | 0          | 0        | 0.00    | (none)       |

| Year to date      | Actual | Budget | Prior year | Variance | %      |
|-------------------|--------|--------|------------|----------|--------|
| Sales             | 1,000  | 3,000  | 800        | -2,000   | -66.67 |
| Cost of sales     | 600    | 1,800  | 0          | -1,200   | -66.67 |

A variance is actual minus budget; for a cost, below budget is favourable.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.mgmt_reporting.models import PackComment, ReportPack

from ..goals.test_goals import budget, g
from ..kpi.test_kpis import k
from ..ledger.conftest import books
from ..projections.test_assumptions import hist
from ..projections.test_projections import approved
from .test_packs import act, explain_all, generate, reviewer

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "g", "hist", "k"]


def sections(g: dict[str, Any], pack_id: str, lang: str = "en") -> list[dict[str, Any]]:
    got = g["client"].get(f"{g['base']}/report-packs/{pack_id}/sections?lang={lang}")
    assert got.status_code == 200, got.content
    out: list[dict[str, Any]] = got.json()["sections"]
    return out


def section(found: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return next(s for s in found if s["key"] == key)


def row(table: dict[str, Any], key: str) -> dict[str, Any]:
    cells = next(r for r in table["rows"] if r["key"] == key)["cells"]
    return {c["key"]: cell for c, cell in zip(table["columns"][1:], cells, strict=True)}


def test_golden_budget_variance_pack(g: dict[str, Any]) -> None:
    """AC-MR4: the budget performance section matches the hand-worked tables to the cent."""
    budget(g)
    pack = generate(g)
    found = sections(g, pack["id"])
    assert [s["key"] for s in found] == [
        "overview", "profitability", "cash", "working_capital", "budget", "kpis", "forecast",
        "risks", "goals", "commentary"]  # fmt: skip
    perf = section(found, "budget")
    assert [t["caption"] for t in perf["tables"]] == [
        "Month", "Quarter to date", "Year to date", "Full-year outlook"]  # fmt: skip
    month, ytd = perf["tables"][0], perf["tables"][2]
    assert [c["key"] for c in month["columns"]] == [
        "line", "actual", "budget", "original_budget", "prior_year", "variance", "variance_pct",
        "assessment", "explanation"]  # fmt: skip
    golden = {
        "REV.SALES": ("0.00", "1000.00", "1000.00", "0.00", "-1000.00", "-100.00", "Unfavourable"),
        "COGS": ("0.00", "600.00", "600.00", "0.00", "-600.00", "-100.00", "Favourable"),
        "OPEX.RENT": ("0.00", "100.00", "100.00", "0.00", "-100.00", "-100.00", "Favourable"),
        "DA.DEPRECIATION": ("50.00", "50.00", "50.00", "0.00", "0.00", "0.00", None),
    }
    for code, expected in golden.items():
        r = row(month, code)
        got = tuple(r[k]["value"] for k in ("actual", "budget", "original_budget", "prior_year",
                                             "variance", "variance_pct", "assessment"))  # fmt: skip
        assert got == expected, code
    sales = row(month, "REV.SALES")
    assert (sales["actual"]["nature"], sales["budget"]["nature"]) == ("ACTUAL", "BUDGET")
    assert next(r for r in month["rows"] if r["key"] == "REV.SALES")["requires_explanation"]
    for code, want in {
        "REV.SALES": ("1000.00", "3000.00", "800.00", "-2000.00", "-66.67"),
        "COGS": ("600.00", "1800.00", "0.00", "-1200.00", "-66.67"),
    }.items():
        r = row(ytd, code)
        to_date = tuple(r[k]["value"] for k in ("actual", "budget", "prior_year", "variance",
                                                 "variance_pct"))  # fmt: skip
        assert to_date == want, code
    # The full-year outlook blends actual months with the budget for the rest of the year.
    outlook = row(perf["tables"][3], "REV.SALES")
    assert outlook["actual"]["nature"] == "BLENDED"
    # Greek labels come from the same snapshot.
    greek = section(sections(g, pack["id"], "el"), "budget")["tables"][0]
    assert row(greek, "REV.SALES")["assessment"]["value"] == "Δυσμενής"
    # The statements: every amount is actual and comes with the prior year.
    profit = section(found, "profitability")["tables"][0]
    assert {c["key"] for c in profit["columns"]} == {"line", "actual", "prior_year", "change"}
    assert all(cell["nature"] == "ACTUAL" for r in profit["rows"] for cell in r["cells"])
    assert section(found, "forecast")["status"] == "empty"
    assert section(found, "kpis")["status"] == "ok"  # calculated for the pack (V1-4)


def test_columns_commentary_and_risks(g: dict[str, Any], make_user: Make,
                                      api_client: Make) -> None:  # fmt: skip
    budget(g)
    c, base = g["client"], g["base"]
    pack = generate(g)
    url = f"{base}/report-packs/{pack['id']}"
    arranged = c.put_json(f"{url}/arrangement", {"sections": ["budget", "risks", "commentary"],
                                                 "columns": ["variance", "actual"]})  # fmt: skip
    assert arranged.status_code == 200, arranged.content
    assert arranged.json()["columns"] == ["actual", "variance"]
    for bad in ({"sections": ["budget", "budget"], "columns": ["actual"]},
                {"sections": ["budget"], "columns": ["variance"]},
                {"sections": ["magic"], "columns": ["actual"]}):  # fmt: skip
        assert c.put_json(f"{url}/arrangement", bad).status_code == 422, bad
    found = sections(g, pack["id"])
    assert [s["key"] for s in found] == ["budget", "risks", "commentary"]
    perf = section(found, "budget")
    assert [t["caption"] for t in perf["tables"]] == ["Month", "Quarter to date", "Year to date"]
    assert [x["key"] for x in perf["tables"][0]["columns"]] == [
        "line", "actual", "variance", "variance_pct", "assessment", "explanation"]  # fmt: skip

    assert c.post_json(f"{url}/comments", {"section": "budget",
                                           "text": "Sales slipped"}).status_code == 200  # fmt: skip
    written = c.post_json(f"{url}/comments", {"section": "budget",
                                              "text": "Orders moved to April"}).json()  # fmt: skip
    assert written == {"budget": "Orders moved to April"}
    c.post_json(f"{url}/comments", {"section": "commentary", "text": "A quiet quarter."})
    assert c.post_json(f"{url}/comments", {"section": "magic", "text": "x"}).status_code == 422
    made = c.post_json(f"{url}/risks", {"title": "Customer C1 pays late", "owner": "CFO"})
    assert made.status_code == 201, made.content
    c.post_json(f"{url}/risks", {"title": "Rent review in June"})
    changed = c.put_json(f"{url}/risks/1", {"title": "Customer C1 pays late", "owner": "CFO",
                                            "status": "MONITORING",
                                            "mitigation": "Weekly calls"}).json()  # fmt: skip
    assert [(r["ref"], r["status"]) for r in changed] == [(1, "MONITORING"), (2, "OPEN")]
    assert [r["ref"] for r in c.post_json(f"{url}/risks/2/remove", {}).json()] == [1]
    assert c.put_json(f"{url}/risks/9", {"title": "x"}).status_code == 404
    found = sections(g, pack["id"])
    assert section(found, "budget")["comment"] == "Orders moved to April"
    assert section(found, "commentary")["comment"] == "A quiet quarter."
    assert section(found, "risks")["risks"] == [{"ref": 1, "title": "Customer C1 pays late",
                                                 "owner": "CFO", "status": "MONITORING",
                                                 "mitigation": "Weekly calls"}]  # fmt: skip

    # In review, commentary and risks are frozen, also in the database.
    act(c, g, pack["id"], "submit")
    assert c.post_json(f"{url}/comments", {"section": "budget", "text": "Later"}).status_code == 409
    set_context(tenant_id=UUID(g["ws"]["id"]))
    p = ReportPack.objects.get(id=pack["id"])
    with pytest.raises(DatabaseError, match="only while the pack is a draft"), \
            transaction.atomic():  # fmt: skip
        PackComment.objects.create(tenant_id=p.tenant_id, pack=p, section="budget", seq=9,
                                   text="Sneaked in", author_id=p.created_by_id)  # fmt: skip
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        PackComment.objects.filter(pack=p).update(text="Rewritten")

    # A new version of the final pack starts with the same commentary and risks.
    boss = reviewer(g, make_user, api_client)
    act(boss, g, pack["id"], "return", note="Explain")
    explain_all(g, c.get(url).json())
    act(c, g, pack["id"], "regenerate")
    act(c, g, pack["id"], "submit")
    assert act(boss, g, pack["id"], "finalise").status_code == 200
    second = act(c, g, pack["id"], "new-version").json()
    again = sections(g, second["id"])
    assert section(again, "budget")["comment"] == "Orders moved to April"
    assert [r["title"] for r in section(again, "risks")["risks"]] == ["Customer C1 pays late"]


def test_forecast_cash_kpi_and_goal_sections(hist: dict[str, Any]) -> None:
    """Sections built from runs: the 13-week forecast and the projection are forecast figures,
    and the projection's section carries the pending-review notice."""
    c, base = hist["client"], hist["base"]
    run = c.post_json(f"{base}/projections", {"assumption_set_id": approved(hist)}).json()
    c.post_json(f"{base}/calc-runs/{run['id']}/publish", {})
    c.post_json(f"{base}/kpi-sets", {"date_from": "2026-12-01", "date_to": "2026-12-31"})
    c.post_json(f"{base}/cash-forecasts", {"as_of": "2026-12-31"})
    pack = generate(hist, {"period_kind": "MONTH", "month": "2026-12-01"})
    found = sections(hist, pack["id"])
    forecast = section(found, "forecast")
    assert forecast["notice"].startswith("Pending professional review")
    table = forecast["tables"][0]
    assert [r["key"] for r in table["rows"]] == [
        "PL.REVENUE", "PL.EBITDA", "PL.NET_INCOME", "CF.NET_CHANGE", "BS.CASH"]  # fmt: skip
    assert {cell["nature"] for r in table["rows"] for cell in r["cells"]} == {"FORECAST"}
    assert table["columns"][1]["label"] == "2027-01"
    cash = section(found, "cash")["tables"]
    assert [t["caption"] for t in cash][1] == "13-week cash forecast"
    assert len(cash[1]["columns"]) == 14  # the line and 13 weeks
    assert {cell["nature"] for r in cash[1]["rows"] for cell in r["cells"]} == {"FORECAST"}
    wc = section(found, "working_capital")["tables"]
    assert wc[1]["caption"] == "Working-capital KPIs"
    assert {r["key"] for r in wc[1]["rows"]} <= {"DSO", "DIO", "DPO", "CASH_CONVERSION_CYCLE",
                                                 "CURRENT_RATIO", "QUICK_RATIO"}  # fmt: skip
    assert section(found, "kpis")["tables"][0]["rows"]
    assert section(found, "goals")["tables"][0]["rows"] == []
    assert section(found, "budget")["status"] == "empty"
    assert section(found, "budget")["tables"] == []
