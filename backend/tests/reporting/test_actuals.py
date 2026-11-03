"""reporting.actuals read model (M2-7, AC-M2-7)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from django.core.management import CommandError, call_command
from django.db import transaction
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fcp.core.db.rls import set_context
from fcp.modules.reporting.api import cash_daily, opening_net
from fcp.modules.reporting.models import FactMonthly
from fcp.modules.tenancy import services as tenancy

from ..ledger.conftest import books, join
from ..ledger.test_entries import act

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]


@pytest.fixture
def rb(books: dict[str, Any]) -> dict[str, Any]:
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    return books


def post(rb: dict[str, Any], day: str, debit: str, credit: str, amount: str) -> dict[str, Any]:
    acc = rb["accounts"]
    draft = rb["client"].post_json(f"{rb['base']}/journal-entries", {
        "accounting_date": day, "description": "Entry",
        "lines": [{"account_id": acc[debit]["id"], "debit": amount},
                  {"account_id": acc[credit]["id"], "credit": amount}]})  # fmt: skip
    assert draft.status_code == 201, draft.content
    posted = act(rb, draft.json()["id"], "post")
    assert posted.status_code == 200, posted.content
    result: dict[str, Any] = posted.json()
    return result


def monthly(rb: dict[str, Any], date_from: str = "2026-01-01",
            date_to: str = "2026-12-31") -> dict[str, Any]:  # fmt: skip
    response = rb["client"].get(
        f"{rb['base']}/actuals/monthly?date_from={date_from}&date_to={date_to}"
    )
    assert response.status_code == 200, response.content
    result: dict[str, Any] = response.json()
    return result


def by_key(result: dict[str, Any]) -> dict[tuple[str, str], tuple[str, str]]:
    return {(f["account_code"], f["month"]): (f["debit"], f["credit"]) for f in result["facts"]}


def verify(rb: dict[str, Any]) -> dict[str, Any]:
    response = rb["client"].get(f"/api/w/{rb['ws']['slug']}/actuals/verify")
    assert response.status_code == 200, response.content
    result: dict[str, Any] = response.json()
    return result


def test_monthly_facts_follow_postings_incrementally(rb: dict[str, Any]) -> None:
    assert monthly(rb) == {"watermark": 0, "facts": []}
    first = post(rb, "2026-01-10", "6100", "1300", "100.00")
    post(rb, "2026-01-20", "6100", "1300", "50.00")
    post(rb, "2026-03-05", "1300", "4000", "300.00")
    result = monthly(rb)
    assert result["watermark"] == first["posting_seq"] + 2
    assert by_key(result) == {
        ("6100", "2026-01-01"): ("150.00", "0.00"),
        ("1300", "2026-01-01"): ("0.00", "150.00"),
        ("1300", "2026-03-01"): ("300.00", "0.00"),
        ("4000", "2026-03-01"): ("0.00", "300.00"),
    }
    # Reading again does not count anything twice; new postings are added on the next read.
    assert by_key(monthly(rb)) == by_key(result)
    post(rb, "2026-01-31", "6100", "1300", "1.00")
    assert by_key(monthly(rb))[("6100", "2026-01-01")] == ("151.00", "0.00")
    assert by_key(monthly(rb, "2026-03-01", "2026-03-31")) == {
        ("1300", "2026-03-01"): ("300.00", "0.00"),
        ("4000", "2026-03-01"): ("0.00", "300.00"),
    }


def test_reversal_lands_in_its_own_month(rb: dict[str, Any]) -> None:
    original = post(rb, "2026-01-10", "6100", "1300", "100.00")
    reversal = (
        rb["client"]
        .post_json(
            f"{rb['base']}/journal-entries/{original['id']}/reverse",
            {"reason": "Wrong month", "reversal_date": "2026-03-01"},
        )
        .json()
    )
    assert act(rb, reversal["id"], "post").status_code == 200
    facts = by_key(monthly(rb))
    assert facts[("6100", "2026-01-01")] == ("100.00", "0.00")
    assert facts[("6100", "2026-03-01")] == ("0.00", "100.00")


def test_verify_reports_drift_and_rebuild_repairs_it(rb: dict[str, Any]) -> None:
    post(rb, "2026-01-10", "6100", "1300", "100.00")
    assert verify(rb)["ok"] is True
    with transaction.atomic():
        set_context(tenant_id=rb["ws"]["id"])
        FactMonthly.objects.filter(account_id=rb["accounts"]["6100"]["id"]).update(
            debit_total=Decimal("99.00")
        )
    drifted = verify(rb)
    assert drifted["ok"] is False
    assert [(d["grain"], d["ledger_debit"], d["facts_debit"]) for d in drifted["drifts"]] == [
        ("monthly", "100.00", "99.00")
    ]
    with pytest.raises(CommandError, match="differ from the ledger"):
        call_command("actuals_verify", verbosity=0)
    rebuilt = rb["client"].post_json(f"/api/w/{rb['ws']['slug']}/actuals/rebuild", None)
    assert rebuilt.status_code == 200
    assert rebuilt.json()["ok"] is True
    call_command("actuals_verify", verbosity=0)  # clean again


def test_rebuild_is_deterministic(rb: dict[str, Any]) -> None:
    for i, day in enumerate(("2026-01-03", "2026-02-14", "2026-02-28", "2026-05-01")):
        post(rb, day, "6100", "1300", f"{10 + i}.25")
    before = by_key(monthly(rb))
    rb["client"].post_json(f"/api/w/{rb['ws']['slug']}/actuals/rebuild", None)
    assert by_key(monthly(rb)) == before


def test_daily_cash_and_opening_balances(rb: dict[str, Any]) -> None:
    post(rb, "2026-01-10", "1300", "3000", "1000.00")
    post(rb, "2026-02-01", "6100", "1300", "200.00")
    post(rb, "2026-02-01", "6100", "1300", "50.00")
    with transaction.atomic():
        ctx = tenancy.enter_workspace(rb["owner"], rb["ws"]["slug"])
        entity = rb["entity"]["id"]
        cash = UUID(rb["accounts"]["1300"]["id"])
        days = cash_daily(ctx, entity, account_ids=[cash], date_from=date(2026, 1, 1),
                          date_to=date(2026, 12, 31))  # fmt: skip
        assert [(f.period.isoformat(), f.net_debit) for f in days.facts] == [
            ("2026-01-10", Decimal("1000.0000")),
            ("2026-02-01", Decimal("-250.0000")),
        ]
        _, opening = opening_net(ctx, entity, before=date(2026, 2, 1))
        assert opening[cash] == Decimal("1000.0000")


def test_only_integrity_readers_verify_or_rebuild(
    rb: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(rb["client"], rb["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{rb['base']}/actuals/monthly?date_from=2026-01-01&date_to=2026-12-31"
                      ).status_code == 200  # fmt: skip
    assert viewer.get(f"/api/w/{rb['ws']['slug']}/actuals/verify").status_code == 403
    assert viewer.post_json(f"/api/w/{rb['ws']['slug']}/actuals/rebuild", None).status_code == 403


# Property: whatever is posted, the read model equals the ledger for every month (AC-M2-7).
postings = st.lists(
    st.tuples(
        st.dates(min_value=date(2026, 1, 1), max_value=date(2026, 12, 31)),
        # Pairs without control accounts (those need a counterparty; tested in registers).
        st.sampled_from([("6100", "1300"), ("1300", "4000"), ("6900", "1300"), ("1310", "1300")]),
        st.decimals(min_value=Decimal("0.01"), max_value=Decimal("99999.99"), places=2),
    ),
    min_size=1,
    max_size=8,
)


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(entries=postings)
def test_facts_always_equal_the_ledger(rb: dict[str, Any], entries: list[Any]) -> None:
    for day, (debit, credit), amount in entries:
        post(rb, day.isoformat(), debit, credit, f"{amount:.2f}")
    assert verify(rb)["ok"] is True
    tb = rb["client"].get(f"{rb['base']}/reports/trial-balance?as_of=2026-12-31").json()
    totals: dict[str, Decimal] = {}
    for (code, _month), (debit_total, credit_total) in by_key(monthly(rb)).items():
        totals[code] = totals.get(code, Decimal(0)) + Decimal(debit_total) - Decimal(credit_total)
    for row in tb["rows"]:
        assert totals.get(row["code"], Decimal(0)) == Decimal(row["debit"]) - Decimal(row["credit"])
