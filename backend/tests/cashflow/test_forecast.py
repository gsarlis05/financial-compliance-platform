"""The 13-week cash forecast end to end (M3-7, AC-CW1-CW4)."""

from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest

from ..ledger.conftest import join
from ..registers.test_open_items import ar, books, invoice, items, post

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["ar", "books"]


@pytest.fixture
def fc(ar: dict[str, Any]) -> dict[str, Any]:
    c, base = ar["client"], ar["base"]
    assert c.post_json(f"{base}/account-mapping/apply-defaults", {}).status_code == 200
    post(
        ar,
        "2026-10-01",
        [{"account_id": "1300", "debit": "10000.00"}, {"account_id": "4000", "credit": "10000.00"}],
    )
    bank = c.post_json(
        f"{base}/bank-accounts",
        {"ledger_account_id": ar["accounts"]["1300"]["id"], "name": "Current account"},
    )
    assert bank.status_code == 201, bank.content
    # Customer C1 pays 3 days late (override); C2's invoice is disputed.
    c.patch_json(f"{base}/counterparties/{ar['parties']['C1']}", {"days_late_override": 3})
    invoice(ar, "C1", "2026-10-20", "1190.00", "INV1", due="2026-11-19")
    invoice(ar, "C2", "2026-10-25", "595.00", "INV2")
    inv2 = next(i for i in items(ar, "2026-11-04") if i["reference"] == "INV2")
    c.put_json(f"{base}/open-items/{inv2['line_id']}/flag", {"disputed": True, "note": "Damaged"})
    # Supplier S1: due 24 Nov (45 days), paid on Fridays -> 20 Nov.
    post(
        ar,
        "2026-10-10",
        [
            {"account_id": "5000", "debit": "300.00"},
            {
                "account_id": "2100",
                "credit": "300.00",
                "counterparty_id": ar["parties"]["S1"],
                "reference": "PI-1",
            },
        ],
    )
    for path, body in (
        (
            "obligations",
            {
                "name": "Office rent",
                "category": "RENT",
                "direction": "OUTFLOW",
                "amount": "1500.00",
                "frequency": "MONTHLY",
                "day_of_month": 1,
                "start_date": "2026-01-01",
                "adjust": "FOLLOWING",
                "contractual": True,
            },
        ),
        (
            "tax-payments",
            {
                "kind": "VAT",
                "period_label": "2026-Q3",
                "due_date": "2026-10-30",
                "amount": "2000.00",
                "nature": "EXPECTED",
            },
        ),
        (
            "cash-items",
            {
                "day": "2026-11-10",
                "amount": "800.00",
                "category": "GRANT",
                "reason": "Synthetic grant",
            },
        ),
        (
            "debt-instruments",
            {
                "name": "Overdraft",
                "kind": "OVERDRAFT",
                "facility_limit": "5000.00",
                "start_date": "2026-01-01",
                "rate_type": "FIXED",
                "fixed_rate": "0.08",
            },
        ),
    ):
        made = c.post_json(f"{base}/{path}", body)
        assert made.status_code == 201, made.content
    saved = c.put_json(
        f"{base}/cash-forecast-settings",
        {
            "minimum_cash": "9000.00",
            "unreconciled_warning_days": 7,
            "payables_policy": "WEEKDAY",
            "payables_weekday": 4,
        },
    )
    assert saved.status_code == 200, saved.content
    return ar


def forecast(fc: dict[str, Any], as_of: str = "2026-11-04") -> dict[str, Any]:
    made = fc["client"].post_json(f"{fc['base']}/cash-forecasts", {"as_of": as_of})
    assert made.status_code == 201, made.content
    result: dict[str, Any] = made.json()
    return result


def test_the_forecast_week_by_week(fc: dict[str, Any]) -> None:
    f = forecast(fc)
    assert f["status"] == "VALID"
    assert f["opening_cash"] == "10000.00"
    weeks = f["weeks"]
    assert len(weeks) == 13
    assert (weeks[0]["label"], weeks[0]["start"], weeks[0]["end"]) == (
        "2026-W45",
        "2026-11-04",
        "2026-11-08",
    )
    closing = [w["closing"] for w in weeks]
    assert closing[:5] == ["8000.00", "8800.00", "9690.00", "9690.00", "8190.00"]
    assert closing[-1] == "6690.00"  # rent on 1 Dec and 1 Jan; 1 Feb is past the horizon
    assert [w["shortfall"] for w in weeks[:4]] == [True, True, False, False]
    assert weeks[0]["liquidity"] == "13000.00"
    assert weeks[0]["headroom"] == "-1000.00"
    assert weeks[0]["opening_nature"] == "ACTUAL"
    assert weeks[1]["opening"] == weeks[0]["closing"]
    assert f["first_shortfall"] == {"date": "2026-11-04", "balance": "8000.00"}
    assert f["overdue"] == "-2000.00"
    week3 = {(x["direction"], x["category"]): x for x in weeks[2]["flows"]}
    assert week3[("IN", "CUSTOMERS")] == {
        "direction": "IN",
        "category": "CUSTOMERS",
        "nature": "COMMITTED",
        "amount": "1190.00",
    }
    assert week3[("OUT", "SUPPLIERS")]["amount"] == "300.00"
    assert weeks[0]["flows"] == [
        {"direction": "OUT", "category": "TAX", "nature": "EXPECTED", "amount": "2000.00"}
    ]
    assert weeks[1]["flows"][0]["category"] == "GRANT"
    assert weeks[1]["flows"][0]["nature"] == "EXPECTED"
    codes = {w["code"] for w in f["warnings"]}
    assert codes == {"unreconciled", "disputed_excluded"}
    disputed = next(w for w in f["warnings"] if w["code"] == "disputed_excluded")
    assert (disputed["count"], disputed["amount"]) == (1, "595.00")
    latest = fc["client"].get(f"{fc['base']}/cash-forecasts/latest").json()
    assert latest["run_id"] == f["run_id"]
    by_id = fc["client"].get(f"{fc['base']}/cash-forecasts/{f['run_id']}").json()
    assert by_id["weeks"] == weeks


def test_runs_pin_their_inputs_and_reproduce(fc: dict[str, Any]) -> None:
    first = forecast(fc)
    # Later changes: a new posting, a new manual item, another override.
    post(
        fc,
        "2026-11-03",
        [{"account_id": "1300", "debit": "50.00"}, {"account_id": "4000", "credit": "50.00"}],
    )
    fc["client"].post_json(
        f"{fc['base']}/cash-items",
        {"day": "2026-11-11", "amount": "-100.00", "category": "OTHER", "reason": "Later"},
    )
    reproduced = fc["client"].post_json(f"{fc['base']}/calc-runs/{first['run_id']}/reproduce", {})
    assert reproduced.json()["reproduced"] is True, reproduced.json()
    again = fc["client"].get(f"{fc['base']}/cash-forecasts/{first['run_id']}").json()
    assert again["weeks"] == first["weeks"]
    second = forecast(fc)
    assert second["opening_cash"] == "10050.00"
    assert second["weeks"][1]["closing"] == "8750.00"
    explain = fc["client"].get(f"{fc['base']}/calc-runs/{second['run_id']}").json()
    flow = next(
        r
        for r in explain["results"]
        if r["series_key"] == "cash.flow" and r["dimensions"] == ["IN", "CUSTOMERS"]
    )
    lineage = (
        fc["client"]
        .get(f"{fc['base']}/calc-runs/{second['run_id']}/results/{flow['id']}/explain")
        .json()
    )
    assert [x["input_kind"] for x in lineage["lineage"]] == ["OPEN_ITEM"]
    assert lineage["lineage"][0]["amount"] == "1190"


def test_settings_and_manual_item_validation(fc: dict[str, Any]) -> None:
    c, base = fc["client"], fc["base"]
    assert c.get(f"{base}/cash-forecast-settings").json()["minimum_cash"] == "9000.00"
    assert c.put_json(f"{base}/cash-forecast-settings", {"minimum_cash": "-1"}).status_code == 422
    assert c.put_json(f"{base}/cash-forecast-settings", {"payables_weekday": 7}).status_code == 422
    for bad in ({"amount": "0.00"}, {"amount": "1.234"}, {"reason": ""}, {"category": "X"}):
        body = {"day": "2026-11-12", "amount": "5.00", "category": "OTHER", "reason": "x", **bad}
        assert c.post_json(f"{base}/cash-items", body).status_code == 422, bad
    listed = c.get(f"{base}/cash-items").json()
    assert [(m["amount"], m["nature"]) for m in listed] == [("800.00", "EXPECTED")]
    assert c.delete_json(f"{base}/cash-items/{listed[0]['id']}").status_code == 204
    assert c.delete_json(f"{base}/cash-items/{listed[0]['id']}").status_code == 404
    old = c.post_json(
        f"{base}/cash-items",
        {"day": "2026-01-05", "amount": "5.00", "category": "OTHER", "reason": "Stale"},
    )
    assert old.status_code == 201
    f = forecast(fc)
    assert "manual_items_past" in {w["code"] for w in f["warnings"]}


def test_no_forecast_yet_and_other_runs(fc: dict[str, Any]) -> None:
    c, base = fc["client"], fc["base"]
    assert c.get(f"{base}/cash-forecasts/latest").status_code == 404
    assert c.get(f"{base}/cash-forecasts/{uuid4()}").status_code == 404


def test_permissions_and_isolation(
    fc: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    f = forecast(fc)
    viewer = join(
        fc["client"], fc["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    assert viewer.get(f"{fc['base']}/cash-forecasts/latest").status_code == 200
    assert viewer.post_json(f"{fc['base']}/cash-forecasts", {}).status_code == 403
    assert (
        viewer.post_json(
            f"{fc['base']}/cash-items",
            {"day": "2026-11-12", "amount": "5.00", "category": "OTHER", "reason": "x"},
        ).status_code
        == 403
    )
    stranger = make_user("stranger@example.test")
    make_workspace(stranger, name="Other Ltd")
    other = api_client(stranger)
    assert other.get(f"{fc['base']}/cash-forecasts/{f['run_id']}").status_code == 404
    # Django checks deferred constraints when the test ends, under the row-level security context
    # of the last request: end in the owner's workspace (each real request commits on its own).
    final = fc["client"].get(f"{fc['base']}/cash-forecasts/latest")
    assert final.status_code == 200, final.content


def test_without_cash_accounts_and_service_checks(ar: dict[str, Any]) -> None:
    """No taxonomy mapping yet: opening cash 0, with a warning. Service-level checks repeat the
    HTTP schema for other callers."""
    from decimal import Decimal  # noqa: PLC0415

    from django.db import transaction  # noqa: PLC0415

    from fcp.core.errors import NotFoundError, ValidationFailedError  # noqa: PLC0415
    from fcp.modules.cashflow import services  # noqa: PLC0415
    from fcp.modules.metrics.models import CalcRun  # noqa: PLC0415
    from fcp.modules.tenancy import services as tenancy  # noqa: PLC0415

    made = ar["client"].post_json(f"{ar['base']}/cash-forecasts", {"as_of": "2026-11-04"})
    assert made.status_code == 201, made.content
    assert made.json()["opening_cash"] == "0.00"
    assert [w["code"] for w in made.json()["warnings"]] == ["no_cash_accounts"]
    with transaction.atomic():
        ctx = tenancy.enter_workspace(ar["owner"], ar["ws"]["slug"])
        entity = ar["entity"]["id"]
        for bad in (
            services.SettingsView(minimum_cash=Decimal("-1")),
            services.SettingsView(minimum_cash=Decimal("0.001")),
            services.SettingsView(payables_policy="MONTHLY"),
        ):
            with pytest.raises(ValidationFailedError):
                services.save_settings(ctx, entity, bad)
        with pytest.raises(NotFoundError):
            services.forecast_of(CalcRun(kind="KPI"))
