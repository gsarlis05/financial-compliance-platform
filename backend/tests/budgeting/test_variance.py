"""Variance: posted actuals only, direction-aware signs, views, thresholds, explanations and the
period review (M4-3: AC-BU4, AC-BU5, AC-BU6). Every expected figure is worked out by hand from
the entries and budget below."""

from collections.abc import Callable
from datetime import date
from typing import Any
from uuid import uuid4

import pytest
from django.db import transaction

from fcp.core.errors import ValidationFailedError
from fcp.modules.budgeting import variance
from fcp.modules.tenancy.services import enter_workspace

from ..ledger.conftest import books, join
from ..metrics.test_mapping import defaults, post
from .test_budgets import MONTHS

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]
JAN, FEB = MONTHS[0], MONTHS[1]


def _tagged(v: dict[str, Any], day: str, account: str, amount: str, value: str) -> None:
    acc = v["accounts"]
    body = {
        "accounting_date": day,
        "description": "Travel",
        "lines": [
            {
                "account_id": acc[account]["id"],
                "debit": amount,
                "credit": "0",
                "dimension_value_ids": [value],
            },
            {"account_id": acc["1300"]["id"], "debit": "0", "credit": amount},
        ],
    }
    draft = v["client"].post_json(f"{v['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    posted = v["client"].post_json(f"{v['base']}/journal-entries/{draft.json()['id']}/post", {})
    assert posted.status_code == 200, posted.content


@pytest.fixture
def v(books: dict[str, Any], make_user: Make, api_client: Make) -> dict[str, Any]:
    base, c = books["base"], books["client"]
    c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"})
    c.post_json(f"{base}/fiscal-years", {"start_date": "2025-01-01"})
    defaults(books)
    dim = c.post_json(
        f"{base}/dimensions", {"code": "DEPT", "name": "Department", "kind": "DEPARTMENT"}
    ).json()
    sales_dept = c.post_json(
        f"{base}/dimensions/{dim['id']}/values", {"code": "SALES", "name": "Sales"}
    ).json()["id"]
    books["dept"] = sales_dept
    # Actuals: sales 1,200 (Jan) and 800 (Feb); rent 600 and 500; travel 250 for Sales in
    # January plus 40 untagged; prior-year sales 900 in January 2025.
    post(books, ("1300", "1200.00", "0"), ("4000", "0", "1200.00"), day="2026-01-15")
    post(books, ("1300", "800.00", "0"), ("4000", "0", "800.00"), day="2026-02-15")
    post(books, ("6100", "600.00", "0"), ("1300", "0", "600.00"), day="2026-01-20")
    post(books, ("6100", "500.00", "0"), ("1300", "0", "500.00"), day="2026-02-20")
    post(books, ("6400", "40.00", "0"), ("1300", "0", "40.00"), day="2026-01-21")
    _tagged(books, "2026-01-22", "6400", "250.00", sales_dept)
    post(books, ("1300", "900.00", "0"), ("4000", "0", "900.00"), day="2025-01-15")
    draft = c.post_json(
        f"{base}/journal-entries",
        {
            "accounting_date": "2026-02-25",
            "description": "Not posted",
            "lines": [
                {"account_id": books["accounts"]["6100"]["id"], "debit": "999.00"},
                {"account_id": books["accounts"]["1300"]["id"], "credit": "999.00"},
            ],
        },
    )
    assert draft.status_code == 201, draft.content
    c.put_json(
        f"{base}/budget-settings", {"explain_above_amount": "100", "explain_above_percent": "10"}
    )
    budget = c.post_json(f"{base}/budgets", {"name": "B", "fiscal_year_id": books["fy"]["id"]})
    version = budget.json()["open_version_id"]
    saved = c.put_json(
        f"{base}/budget-versions/{version}/lines",
        {
            "lines": [
                {"taxonomy_code": "REV.SALES", "method": "EVEN", "params": {"annual": "12000"}},
                {"taxonomy_code": "OPEX.RENT", "method": "EVEN", "params": {"annual": "6000"}},
                {
                    "taxonomy_code": "OPEX.TRAVEL",
                    "dimension_value_id": sales_dept,
                    "method": "EVEN",
                    "params": {"annual": "1200"},
                },
            ]
        },
    )
    assert saved.status_code == 200, saved.content
    books["lines"] = {ln["taxonomy_code"]: ln["id"] for ln in saved.json()["lines"]}
    books["manager"] = join(
        c, books["ws"]["slug"], make_user("fm@example.test", "Mo"), api_client, "finance_manager"
    )
    c.post_json(f"{base}/budget-versions/{version}/submit", {})
    assert (
        books["manager"].post_json(f"{base}/budget-versions/{version}/approve", {}).status_code
        == 200
    )
    books["budget"], books["version"] = budget.json(), version
    return books


def get(
    v: dict[str, Any], client: Any = None, version: str | None = None, **query: str
) -> dict[str, Any]:
    params = "&".join(f"{k}={val}" for k, val in query.items())
    response = (client or v["client"]).get(
        f"{v['base']}/budget-versions/{version or v['version']}/variance?{params}"
    )
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    return body


def rows(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["taxonomy_code"]: r for r in body["rows"]}


def test_month_ytd_and_full_year_against_budget(v: dict[str, Any]) -> None:
    jan = get(v, month=JAN)
    assert jan["window"] == [JAN]
    assert jan["unposted_entries"] == 0
    r = rows(jan)
    sales, rent, travel = r["REV.SALES"], r["OPEX.RENT"], r["OPEX.TRAVEL"]
    assert (sales["subject"], sales["comparison"], sales["variance"]) == (
        "1200.00",
        "1000.00",
        "200.00",
    )
    assert (sales["subject_nature"], sales["comparison_nature"]) == ("ACTUAL", "BUDGET")
    assert sales["percent"] == "20.00"
    assert sales["favourable"] is True  # more revenue than planned
    assert (rent["variance"], rent["percent"], rent["favourable"]) == ("100.00", "20.00", False)
    # Only the Sales department's travel (250), not the untagged 40.
    assert (travel["subject"], travel["variance"]) == ("250.00", "150.00")
    assert all(row["requires_explanation"] for row in (sales, rent, travel))

    ytd = rows(get(v, month=FEB, view="YTD"))
    assert ytd["REV.SALES"]["variance"] == "0.00"
    assert ytd["REV.SALES"]["favourable"] is None
    assert ytd["REV.SALES"]["requires_explanation"] is False
    assert (ytd["OPEX.RENT"]["variance"], ytd["OPEX.RENT"]["percent"]) == ("100.00", "10.00")
    assert ytd["OPEX.RENT"]["requires_explanation"] is True  # 100 and 10% both reached
    assert ytd["OPEX.TRAVEL"]["requires_explanation"] is False  # 50 is below 100
    assert get(v, month=FEB, view="YTD")["unposted_entries"] == 1  # the draft is not counted

    qtd = get(v, month=FEB, view="QTD")
    assert qtd["window"] == [JAN, FEB]
    outlook = get(v, month=FEB, view="FULL_YEAR")
    assert (outlook["cutover"], len(outlook["window"])) == (FEB, 12)
    full = rows(outlook)["REV.SALES"]
    assert (full["subject"], full["subject_nature"], full["comparison"]) == (
        "12000.00",
        "BLENDED",
        "12000.00",
    )


def test_prior_year_and_original_budget(v: dict[str, Any]) -> None:
    py = rows(get(v, month=JAN, comparison="ACTUAL_VS_PRIOR_YEAR"))
    assert (py["REV.SALES"]["comparison"], py["REV.SALES"]["comparison_nature"]) == (
        "900.00",
        "ACTUAL",
    )
    assert py["REV.SALES"]["percent"] == "33.33"
    assert py["OPEX.RENT"]["percent"] is None  # nothing last year: not meaningful, never 0 or ∞
    assert py["OPEX.RENT"]["requires_explanation"] is True

    base = v["base"]
    revised = (
        v["client"]
        .post_json(f"{base}/budget-versions/{v['version']}/revise", {"reason": "Price rise"})
        .json()["id"]
    )
    v["client"].put_json(
        f"{base}/budget-versions/{revised}/lines",
        {
            "lines": [
                {"taxonomy_code": "REV.SALES", "method": "EVEN", "params": {"annual": "13200"}},
                {"taxonomy_code": "OPEX.MARKETING", "amounts": {JAN: "50.00"}},
            ]
        },
    )
    v["client"].post_json(f"{base}/budget-versions/{revised}/submit", {})
    v["manager"].post_json(f"{base}/budget-versions/{revised}/approve", {})
    vs = get(v, version=revised, month=JAN, comparison="CURRENT_VS_ORIGINAL")
    r = rows(vs)
    assert (r["REV.SALES"]["subject"], r["REV.SALES"]["comparison"]) == ("1100.00", "1000.00")
    assert r["OPEX.MARKETING"]["comparison"] == "0.00"
    assert r["OPEX.RENT"]["line_id"] is None  # only in the original
    assert r["OPEX.RENT"]["subject"] == "0.00"


def test_explanations_and_review(v: dict[str, Any], make_user: Make, api_client: Make) -> None:
    base, version, lines = v["base"], v["version"], v["lines"]

    def explain(line: str, comment: str, view: str = "MONTH", client: Any = None) -> Any:
        return (client or v["client"]).post_json(
            f"{base}/budget-versions/{version}/explanations",
            {
                "line_id": lines[line],
                "month": FEB if view == "YTD" else JAN,
                "view": view,
                "comment": comment,
            },
        )

    review = f"{base}/budget-versions/{version}/reviews"
    refused = v["manager"].post_json(review, {"month": JAN})
    assert refused.status_code == 409
    assert refused.json()["code"] == "budgeting.review_incomplete"
    assert len(refused.json()["errors"]["lines"]) == 3  # sales, rent and travel for January
    assert explain("REV.SALES", " ").status_code == 422
    assert explain("REV.SALES", "Big order from a new customer").status_code == 201
    assert explain("OPEX.RENT", "Service charge").status_code == 201
    changed = explain("OPEX.RENT", "Annual service charge, billed in January")
    assert changed.json()["seq"] == 2
    # The Sales department's owner explains their own line, and only theirs.
    holder_user = make_user("holder@example.test", "Hana")
    holder = join(v["client"], v["ws"]["slug"], holder_user, api_client, "budget_holder")
    v["client"].put_json(
        f"{base}/budgets/{v['budget']['id']}/owners",
        {"owners": [{"dimension_value_id": v["dept"], "user_id": str(holder_user.id)}]},
    )
    seen = get(v, client=holder, month=JAN)
    assert [r["taxonomy_code"] for r in seen["rows"]] == ["OPEX.TRAVEL"]
    assert seen["unposted_entries"] is None
    assert explain("OPEX.RENT", "not mine", client=holder).status_code == 422
    assert explain("OPEX.TRAVEL", "Trade fair", client=holder).status_code == 201
    assert holder.post_json(review, {"month": JAN}).status_code == 403

    after = rows(get(v, month=JAN))
    assert after["OPEX.RENT"]["explanation"]["comment"].startswith("Annual service charge")
    assert after["OPEX.TRAVEL"]["explanation"]["author_name"] == "Hana"
    history = (
        v["client"]
        .get(f"{base}/budget-versions/{version}/lines/{lines['OPEX.RENT']}/explanations")
        .json()
    )
    assert [h["seq"] for h in history] == [1, 2]
    done = v["manager"].post_json(review, {"month": JAN})
    assert done.status_code == 201, done.content
    assert get(v, month=JAN)["review"]["completed_by_name"] == "Mo"
    assert v["manager"].post_json(review, {"month": JAN}).status_code == 409
    # February: its own sales (-200, 20%) and travel (-100, 100%) variances, and the
    # year-to-date rent (+100, 10%); year-to-date sales (0) and travel (+50) are below.
    february = v["manager"].post_json(review, {"month": FEB})
    assert february.status_code == 409
    assert sorted(february.json()["errors"]["lines"]) == [
        "OPEX.RENT (ytd)",
        "OPEX.TRAVEL (month)",
        "REV.SALES (month)",
    ]

    def explain_feb(line: str, view: str) -> int:
        return int(
            v["client"]
            .post_json(
                f"{base}/budget-versions/{version}/explanations",
                {"line_id": lines[line], "month": FEB, "view": view, "comment": "Explained"},
            )
            .status_code
        )

    assert explain_feb("REV.SALES", "MONTH") == 201
    assert explain_feb("OPEX.TRAVEL", "MONTH") == 201
    assert explain_feb("OPEX.RENT", "YTD") == 201
    assert v["manager"].post_json(review, {"month": FEB}).status_code == 201
    v["client"].get(f"{base}/budgets")  # end under the owner's context


def test_variance_checks_its_inputs(v: dict[str, Any]) -> None:
    base, version = v["base"], v["version"]
    url = f"{base}/budget-versions/{version}/variance"
    assert v["client"].get(f"{url}?month=2027-01-01").status_code == 422
    assert v["client"].get(f"{url}?month={JAN}&view=WEEK").status_code == 422
    draft = (
        v["client"]
        .post_json(f"{base}/budget-versions/{version}/revise", {"reason": "x"})
        .json()["id"]
    )
    preview = get(v, version=draft, month=JAN)  # a draft can be compared, not explained
    assert rows(preview)["REV.SALES"]["variance"] == "200.00"
    explained = v["client"].post_json(
        f"{base}/budget-versions/{draft}/explanations",
        {"line_id": rows(preview)["REV.SALES"]["line_id"], "month": JAN, "comment": "x"},
    )
    assert explained.status_code == 409
    wrong = v["client"].post_json(
        f"{base}/budget-versions/{version}/explanations",
        {"line_id": v["lines"]["REV.SALES"], "month": "2027-01-01", "comment": "x"},
    )
    assert wrong.status_code == 422
    assert (
        v["manager"]
        .post_json(f"{base}/budget-versions/{draft}/reviews", {"month": JAN})
        .status_code
        == 409
    )


def test_account_lines_follow_the_account_type(
    v: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    base, acc = v["base"], v["accounts"]
    draft = (
        v["client"]
        .post_json(f"{base}/budget-versions/{v['version']}/revise", {"reason": "accounts"})
        .json()["id"]
    )
    v["client"].put_json(
        f"{base}/budget-versions/{draft}/lines",
        {
            "lines": [
                {"account_id": acc["4000"]["id"], "amounts": {JAN: "1000.00"}},
                {"account_id": acc["6100"]["id"], "amounts": {JAN: "700.00"}},
                {"account_id": acc["1300"]["id"], "amounts": {JAN: "0.00"}},
            ]
        },
    )
    by_account = {r["account_id"]: r for r in get(v, version=draft, month=JAN)["rows"]}
    income, rent, cash = (by_account[acc[c]["id"]] for c in ("4000", "6100", "1300"))
    assert (income["direction"], income["subject"], income["favourable"]) == (
        "HIGHER_BETTER",
        "1200.00",
        True,
    )
    assert (rent["direction"], rent["variance"], rent["favourable"]) == (
        "LOWER_BETTER",
        "-100.00",
        True,
    )  # less cost than planned
    assert cash["direction"] == "HIGHER_BETTER"  # from its taxonomy line (BS.CASH)
    assert variance.thresholds(uuid4()) == variance.Thresholds(1000, 10)  # type: ignore[arg-type]

    # A department owner's explanation history shows only their department's lines.
    holder_user = make_user("h2@example.test", "H2")
    holder = join(v["client"], v["ws"]["slug"], holder_user, api_client, "budget_holder")
    v["client"].put_json(
        f"{base}/budgets/{v['budget']['id']}/owners",
        {"owners": [{"dimension_value_id": v["dept"], "user_id": str(holder_user.id)}]},
    )
    url = f"{base}/budget-versions/{v['version']}/lines/{v['lines']['OPEX.RENT']}/explanations"
    v["client"].post_json(
        f"{base}/budget-versions/{v['version']}/explanations",
        {"line_id": v["lines"]["OPEX.RENT"], "month": JAN, "comment": "Rent"},
    )
    assert len(v["client"].get(url).json()) == 1
    assert holder.get(url).json() == []

    with transaction.atomic():
        ctx = enter_workspace(v["owner"], v["ws"]["slug"])
        entity = v["entity"]["id"]
        for kwargs in ({"view": "WEEK"}, {"comparison": "BUDGET_VS_HOPE"}):
            with pytest.raises(ValidationFailedError):
                variance.compute(ctx, entity, v["version"], month=date(2026, 1, 1), **kwargs)
        with pytest.raises(ValidationFailedError):
            variance.explain(
                ctx,
                entity,
                v["version"],
                v["lines"]["OPEX.RENT"],
                month=date(2026, 1, 1),
                view="WEEK",
                comparison="ACTUAL_VS_BUDGET",
                comment="x",
            )
        with pytest.raises(ValidationFailedError):
            variance.complete_review(ctx, entity, v["version"], date(2027, 1, 1))
    v["client"].get(f"{base}/budgets")  # end under the owner's context
