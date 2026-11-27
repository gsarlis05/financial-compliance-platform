"""Correcting the rules on a screen (brief 27, T-2, #255; AC-T2, AC-T3). Synthetic figures; the
corrected rates below are invented for the test, not real Cyprus rates."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.taxrules.models import RuleCorrection
from fcp.modules.taxrules.rules import rules_for

from ..ledger.conftest import books, join
from ..tax.test_vat_reports import S19, act, generate, post, scheme, v

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "v"]
SOURCE = "Synthetic source for the test (Demo)"


def correct(v: dict[str, Any], path: str, client: Any = None, **body: Any) -> Any:
    return (client or v["client"]).post_json(f"{v['base']}/{path}", {"source": SOURCE, **body})


def codes(v: dict[str, Any], on: str) -> dict[str, dict[str, Any]]:
    got = v["client"].get(f"{v['base']}/vat-codes", {"on": on}).json()
    return {c["code"]: c for c in got}


def test_a_vat_code_correction_applies_from_its_date_and_earlier_returns_keep_theirs(
    v: dict[str, Any],
) -> None:
    assert scheme(v, 3, "2026-01-01").status_code == 201
    q1 = generate(v).json()
    assert {c["code"]: c["rate"] for c in q1["snapshot"]["codes"]}["S19"] == "0.1900"
    made = correct(v, "vat-codes/s19/corrections", effective_from="2026-04-01", rate="0.2")
    assert made.status_code == 201, made.content
    assert made.json()["values"] == {"rate": "0.2000"}
    # The code as the entry form sees it, before and after the correction's start.
    assert codes(v, "2026-03-31")["S19"]["rate"] == "0.1900"
    after = codes(v, "2026-05-01")["S19"]
    assert (after["rate"], after["corrected_from"], after["correction_source"]) == (
        "0.2000", "2026-04-01", SOURCE)  # fmt: skip
    # The second quarter's return reads the corrected rate for the April sale (100 at 20%; 19 was
    # booked, so the difference shows) and pins the correction it used.
    q2 = generate(v, "2026-04-01").json()
    s19 = {c["code"]: c for c in q2["snapshot"]["codes"]}["S19"]
    assert (s19["rate"], s19["sales_expected_vat"], s19["sales_vat"]) == ("0.2000", "20.00",
                                                                          "19.00")  # fmt: skip
    assert [c["target"] for c in q2["snapshot"]["code_corrections"]] == ["S19"]
    # The first quarter's return is unchanged, and so is its regenerated version: its lines are
    # dated before the correction.
    again = act(v, q1["id"], "regenerate").json()
    assert {c["code"]: c["rate"] for c in again["snapshot"]["codes"]}["S19"] == "0.1900"
    assert again["snapshot"]["code_corrections"] == []
    event = AuditEvent.objects.get(action="taxrules.corrected")
    assert (event.changes["target"], event.changes["source"]) == ("S19", SOURCE)


def test_a_box_rule_correction_maps_what_was_unsupported(v: dict[str, Any]) -> None:
    assert scheme(v, 3, "2026-01-01").status_code == 201
    q1 = generate(v).json()
    assert [e["kind"] for e in q1["snapshot"]["exceptions"]] == ["UNSUPPORTED"]  # exempt purchase
    made = correct(
        v,
        "vat-box-rules/corrections",
        effective_from="2026-01-01",
        category="EXEMPT",
        line="NET_PURCHASE",
        status="MAPPED",
        boxes=["7"],
    )
    assert made.status_code == 201, made.content
    rules = v["client"].get(f"{v['base']}/vat-box-rules", {"on": "2026-01-01"}).json()
    found = next(r for r in rules if (r["category"], r["line"]) == ("EXEMPT", "NET_PURCHASE"))
    assert (found["status"], found["boxes"], found["corrected_from"]) == (
        "MAPPED", ["7"], "2026-01-01")  # fmt: skip
    again = act(v, q1["id"], "regenerate").json()
    snap = again["snapshot"]
    assert snap["exceptions"] == []
    assert list(snap["return"]["corrections"]) == ["EXEMPT|NET_PURCHASE"]
    boxes = {b["box"]: b["amount"] for b in snap["return"]["boxes"]}
    assert boxes["7"] == "600.00"  # 400 at S19 and 200 exempt
    line = next(ln for ln in snap["lines"] if ln["code"] == "EX")
    assert line["rule"].startswith("Corrected from 2026-01-01: ")


def test_a_corporate_tax_correction_replaces_the_rule_set_from_its_year(
    books: dict[str, Any],
) -> None:
    body = {
        "effective_from": "2027-01-01",
        "rate": "0.2",
        "loss_carryforward_years": 5,
        "tax_year_start_month": 1,
        "provisional_instalments": [
            {"month": 7, "day": 31, "share": "0.5"},
            {"month": 12, "day": 31, "share": "0.5"},
        ],
        "final_payment_years_after": 1,
        "final_payment_month": 8,
        "final_payment_day": 1,
    }
    made = correct(books, "tax-rules/corrections", **body)
    assert made.status_code == 201, made.content
    rules = books["client"].get(f"{books['base']}/tax-rules").json()
    assert [(r["effective_from"], r["effective_to"], r["rate"]) for r in rules] == [
        ("2020-01-01", "2025-12-31", "0.125"), ("2026-01-01", "2026-12-31", "0.15"),
        ("2027-01-01", None, "0.2")]  # fmt: skip
    assert rules[-1]["id"].startswith("CORRECTION:")
    # What a projection run reads for each tax year (the run pins it in its inputs).
    with transaction.atomic():
        set_context(tenant_id=books["ws"]["id"])
        entity = books["entity"]["id"]
        assert rules_for("CY", date(2026, 6, 30), entity_id=entity).id == "CY:CIT:2026"
        corrected = rules_for("CY", date(2028, 6, 30), entity_id=entity)
        assert (corrected.rate, corrected.as_refs()["rate"]) == (Decimal("0.2"), "0.2")
        assert rules_for("CY", date(2028, 6, 30)).id == "CY:CIT:2026"  # other entities: global
    # Refusals name the reason (AC-T3).
    late = correct(books, "tax-rules/corrections", **{**body, "effective_from": "2027-03-01"})
    assert late.status_code == 422
    assert "first day of a tax year" in late.json()["detail"]
    shares = correct(books, "tax-rules/corrections",
                     **{**body, "provisional_instalments": [{"month": 7, "day": 31,
                                                             "share": "0.4"}]})  # fmt: skip
    assert "add up to 1" in shares.json()["detail"]
    earlier = correct(books, "tax-rules/corrections", **{**body, "effective_from": "2026-01-01"})
    assert earlier.status_code == 422
    assert "already applies from 01/01/2027" in earlier.json()["detail"]
    nosource = books["client"].post_json(f"{books['base']}/tax-rules/corrections",
                                         {**body, "source": ""})  # fmt: skip
    assert nosource.status_code == 422


def test_refusals_permissions_and_corrections_are_never_changed(
    books: dict[str, Any],
    make_user: Make,
    api_client: Make,
) -> None:
    unknown = correct(books, "vat-codes/NOPE/corrections", effective_from="2026-01-01",
                      rate="0.1")  # fmt: skip
    assert unknown.status_code == 404
    bad_rate = correct(books, "vat-codes/S19/corrections", effective_from="2026-01-01",
                       rate="1.5")  # fmt: skip
    assert "fraction" in bad_rate.json()["detail"]
    nothing = correct(books, "vat-codes/S19/corrections", effective_from="2026-01-01")
    assert "changes nothing" in nothing.json()["detail"]
    formula = correct(
        books,
        "vat-box-rules/corrections",
        effective_from="2026-01-01",
        category="EXEMPT",
        line="NET_PURCHASE",
        status="MAPPED",
        boxes=["3"],
    )
    assert "Boxes 3 and 5 are worked out" in formula.json()["detail"]
    empty = correct(
        books,
        "vat-box-rules/corrections",
        effective_from="2026-01-01",
        category="EXEMPT",
        line="NET_PURCHASE",
        status="MAPPED",
        boxes=[],
    )
    assert "at least one box" in empty.json()["detail"]
    # An accountant prepares figures but does not correct the rules.
    accountant = join(books["client"], books["ws"]["slug"], make_user("acc@example.test"),
                      api_client, "accountant")  # fmt: skip
    denied = correct(books, "vat-codes/S19/corrections", accountant,
                     effective_from="2026-01-01", rate="0.2")  # fmt: skip
    assert denied.status_code == 403
    made = correct(books, "vat-codes/S19/corrections", effective_from="2026-01-01", rate="0.2")
    assert made.status_code == 201
    listed = books["client"].get(f"{books['base']}/rule-corrections").json()
    assert [(c["kind"], c["target"]) for c in listed] == [("VAT_CODE", "S19")]
    with transaction.atomic():
        set_context(tenant_id=books["ws"]["id"])
        found = RuleCorrection.objects.filter(target="S19")
        with pytest.raises(DatabaseError, match="never changed or deleted"):
            found.update(source="edited")
    # The same day again supersedes it (a mistake is corrected by a later entry).
    fixed = correct(books, "vat-codes/S19/corrections", effective_from="2026-01-01", rate="0.21")
    assert fixed.status_code == 201
    on = books["client"].get(f"{books['base']}/vat-codes", {"on": "2026-06-01"}).json()
    assert next(c for c in on if c["code"] == "S19")["rate"] == "0.2100"


def test_lines_without_a_correction_are_unchanged(v: dict[str, Any]) -> None:
    post(v, "2026-05-02", ("1300", "119", "0", None), ("4000", "0", "100", S19),
         ("2120", "0", "19", S19))  # fmt: skip
    assert scheme(v, 3, "2026-01-01").status_code == 201
    q2 = generate(v, "2026-04-01").json()
    assert q2["snapshot"]["code_corrections"] == []
    assert q2["snapshot"]["return"]["corrections"] == {}
