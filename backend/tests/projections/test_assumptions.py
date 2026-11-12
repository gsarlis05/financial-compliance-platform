"""Assumption sets (M6-2, AC-PJ5): started from actuals, the budget or empty, edited as drafts,
approved once, revised as new versions, and protected by the database. Every expected figure is
worked out by hand from the entries below."""

from collections.abc import Callable
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.projections.models import AssumptionSet, AssumptionValue

from ..ledger.conftest import books, join
from ..ledger.test_dimensions import commit_point
from ..ledger.test_entries import act
from ..metrics.test_mapping import defaults, post

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def hist(books: dict[str, Any]) -> dict[str, Any]:
    """2026: sales 1,200 (Jan, cash), 800 (Feb, cash) and 300 (Feb, on credit: AR 300 at the year
    end); cost of sales 480 and 320; rent 600 and 500."""
    c, base = books["client"], books["base"]
    c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"})
    defaults(books)
    post(books, ("1300", "1200.00", "0"), ("4000", "0", "1200.00"), day="2026-01-15")
    post(books, ("5000", "480.00", "0"), ("1300", "0", "480.00"), day="2026-01-16")
    post(books, ("6100", "600.00", "0"), ("1300", "0", "600.00"), day="2026-01-20")
    post(books, ("1300", "800.00", "0"), ("4000", "0", "800.00"), day="2026-02-15")
    customer = c.post_json(f"{base}/counterparties", {"code": "C1", "name": "Customer (Demo)",
                                                     "kind": "CUSTOMER"}).json()  # fmt: skip
    acc = books["accounts"]
    credit_sale = c.post_json(f"{base}/journal-entries", {
        "accounting_date": "2026-02-16", "description": "Sale on credit", "lines": [
            {"account_id": acc["1200"]["id"], "debit": "300.00", "counterparty_id": customer["id"]},
            {"account_id": acc["4000"]["id"], "credit": "300.00"}]})  # fmt: skip
    assert act(books, credit_sale.json()["id"], "post").status_code == 200
    post(books, ("5000", "320.00", "0"), ("1300", "0", "320.00"), day="2026-02-17")
    post(books, ("6100", "500.00", "0"), ("1300", "0", "500.00"), day="2026-02-20")
    commit_point()
    return books


def make(h: dict[str, Any], **body: Any) -> Any:
    payload = {"name": "Plan 2027", "cutover": "2026-12-31", "months": 24,
               "start_from": "ACTUALS", **body}  # fmt: skip
    return h["client"].post_json(f"{h['base']}/assumption-sets", payload)


def rows(grid: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(r["driver"], r["line"]): r for r in grid["rows"]}


def test_start_from_actuals_by_hand(hist: dict[str, Any]) -> None:
    made = make(hist, revenue_growth="10")
    assert made.status_code == 201, made.content
    s = made.json()
    assert (s["status"], s["version"], s["months"]) == ("DRAFT", 1, 24)
    assert s["note"] == "Started from the 12 months to 31/12/2026, revenue 10% a year."
    grid = hist["client"].get(f"{hist['base']}/assumption-sets/{s['id']}").json()
    assert grid["nature"] == "FORECAST"
    assert (grid["months"][0], grid["months"][-1]) == ("2027-01-01", "2028-12-01")
    r = rows(grid)
    assert len(r) == 26  # 3 revenue lines, 8 cost lines and 15 single drivers
    sales = r[("revenue", "REV.SALES")]
    # Jan 2027 = Jan 2026 x 1.10; Feb 2027 = (800 + 300) x 1.10; Jan 2028 = 1,200 x 1.10^2.
    assert sales["values"][:3] == ["1320", "1210", "0"]
    assert sales["values"][12] == "1452"
    assert set(sales["sources"]) == {"ACTUALS"}
    assert r[("opex", "OPEX.RENT")]["values"][:2] == ["600", "500"]  # costs are not grown
    # Gross margin (2,300 - 800) / 2,300 = 65.2174%; DSO 300 / 2,300 x 365 = 47.6087 days;
    # DPO and DIO are 0 (no payables or stock); no tax, no debt.
    keys = ("gross_margin", "dso", "dio", "dpo", "tax_rate", "interest_rate", "capex_life")
    single = {k: r[(k, "")]["values"][0] for k in keys}
    assert single == {"gross_margin": "65.2174", "dso": "47.6087", "dio": "0", "dpo": "0",
                      "tax_rate": "0", "interest_rate": "0", "capex_life": "60"}  # fmt: skip
    assert r[("capex", "")]["sources"][0] == "DEFAULT"

    empty = make(hist, start_from="EMPTY", months=12).json()
    grid = hist["client"].get(f"{hist['base']}/assumption-sets/{empty['id']}").json()
    r = rows(grid)
    assert r[("revenue", "REV.SALES")]["values"] == ["0"] * 12
    assert r[("capex_life", "")]["values"][0] == "60"


def test_edit_approve_revise_and_the_database_keeps_approved_sets(hist: dict[str, Any]) -> None:
    c, base = hist["client"], hist["base"]
    s = make(hist, months=12).json()
    url = f"{base}/assumption-sets/{s['id']}"
    changed = c.put_json(f"{url}/values", {"changes": [
        {"driver": "capex", "month": "2027-03-01", "value": "15000"},
        {"driver": "revenue", "line": "REV.SALES", "month": "2027-01-01", "value": "2000.50"},
    ]})  # fmt: skip
    assert changed.status_code == 200, changed.content
    r = rows(changed.json())
    assert (r[("capex", "")]["values"][2], r[("capex", "")]["sources"][2]) == ("15000", "MANUAL")
    assert r[("revenue", "REV.SALES")]["values"][0] == "2000.5"
    for bad in (
        {"driver": "capex", "month": "2028-01-01", "value": "1"},  # outside the horizon
        {"driver": "magic", "month": "2027-01-01", "value": "1"},
        {"driver": "revenue", "line": "OPEX.RENT", "month": "2027-01-01", "value": "1"},
        {"driver": "capex", "month": "2027-01-01", "value": "-5"},
        {"driver": "dso", "month": "2027-01-01", "value": "9999"},
    ):
        refused = c.put_json(f"{url}/values", {"changes": [bad]})
        assert refused.status_code == 422, (bad, refused.content)
    assert c.patch_json(url, {"name": "Plan 2027 (base)"}).json()["name"] == "Plan 2027 (base)"

    approved = c.post_json(f"{url}/approve", {})
    assert approved.status_code == 200, approved.content
    assert approved.json()["status"] == "APPROVED"
    late = c.put_json(f"{url}/values", {"changes": [
        {"driver": "capex", "month": "2027-03-01", "value": "1"}]})  # fmt: skip
    assert late.status_code == 409, late.content
    assert c.post_json(f"{url}/approve", {}).status_code == 409

    revision = c.post_json(f"{url}/revise", {})
    assert revision.status_code == 201, revision.content
    v2 = revision.json()
    assert (v2["version"], v2["status"], v2["supersedes_id"]) == (2, "DRAFT", s["id"])
    assert c.post_json(f"{url}/revise", {}).status_code == 409  # one draft at a time
    v2_grid = c.get(f"{base}/assumption-sets/{v2['id']}").json()
    assert rows(v2_grid)[("capex", "")]["values"][2] == "15000"
    c.post_json(f"{base}/assumption-sets/{v2['id']}/approve", {})
    listed = {x["version"]: x["status"] for x in c.get(f"{base}/assumption-sets").json()
              if x["family_id"] == s["family_id"]}  # fmt: skip
    assert listed == {1: "SUPERSEDED", 2: "APPROVED"}

    set_context(tenant_id=UUID(hist["ws"]["id"]))
    with pytest.raises(DatabaseError, match="draft"), transaction.atomic():
        AssumptionValue.objects.filter(assumption_set_id=v2["id"]).update(value=Decimal(1))
    with pytest.raises(DatabaseError, match="draft"), transaction.atomic():
        AssumptionValue.objects.filter(assumption_set_id=v2["id"]).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        AssumptionSet.objects.filter(id=v2["id"]).update(name="Changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        AssumptionSet.objects.filter(id=v2["id"]).delete()
    draft = make(hist, months=12).json()
    with pytest.raises(DatabaseError, match="horizon"), transaction.atomic():
        AssumptionSet.objects.filter(id=draft["id"]).update(months=24)


def test_start_from_the_approved_budget(hist: dict[str, Any], make_user: Make,
                                        api_client: Make) -> None:  # fmt: skip
    c, base = hist["client"], hist["base"]
    assert make(hist, cutover="2025-12-31", start_from="BUDGET").status_code == 422  # none yet
    budget = c.post_json(f"{base}/budgets", {"name": "B", "fiscal_year_id": hist["fy"]["id"]})
    version = budget.json()["open_version_id"]
    c.put_json(f"{base}/budget-versions/{version}/lines", {"lines": [
        {"taxonomy_code": "REV.SALES", "method": "EVEN", "params": {"annual": "12000"}},
        {"taxonomy_code": "COGS", "method": "EVEN", "params": {"annual": "4800"}},
        {"taxonomy_code": "OPEX.RENT", "method": "EVEN", "params": {"annual": "6000"}},
    ]})  # fmt: skip
    c.post_json(f"{base}/budget-versions/{version}/submit", {})
    manager = join(c, hist["ws"]["slug"], make_user("fm@example.test"), api_client,
                   "finance_manager")  # fmt: skip
    assert manager.post_json(f"{base}/budget-versions/{version}/approve", {}).status_code == 200

    made = make(hist, cutover="2025-12-31", start_from="BUDGET", months=12)
    assert made.status_code == 201, made.content
    assert made.json()["note"].endswith("and the approved budget for the months it covers.")
    r = rows(c.get(f"{base}/assumption-sets/{made.json()['id']}").json())
    sales = r[("revenue", "REV.SALES")]
    assert (sales["values"][0], set(sales["sources"])) == ("1000", {"BUDGET"})
    assert r[("opex", "OPEX.RENT")]["values"][0] == "500"
    # Margin from the budget: (1,000 - 400) / 1,000 = 60%.
    gm = r[("gross_margin", "")]
    assert (gm["values"][0], gm["sources"][0]) == ("60", "BUDGET")
    # Lines without a budget come from the year before the cut-over (2025: nothing).
    assert r[("opex", "OPEX.TRAVEL")]["values"][0] == "0"


def test_permissions(hist: dict[str, Any], make_user: Make, api_client: Make) -> None:
    c, base, slug = hist["client"], hist["base"], hist["ws"]["slug"]
    s = make(hist, months=12).json()
    viewer = join(c, slug, make_user("viewer@example.test"), api_client, "read_only")
    assert viewer.get(f"{base}/assumption-sets/{s['id']}").status_code == 200
    assert make({**hist, "client": viewer}).status_code == 403
    accountant = join(c, slug, make_user("acc@example.test"), api_client, "accountant")
    assert make({**hist, "client": accountant}, months=12).status_code == 201
    assert accountant.post_json(f"{base}/assumption-sets/{s['id']}/approve", {}).status_code == 403
    drivers = c.get(f"{base}/assumption-drivers").json()
    assert {d["key"] for d in drivers} >= {"revenue", "gross_margin", "dso", "revolver_limit"}
