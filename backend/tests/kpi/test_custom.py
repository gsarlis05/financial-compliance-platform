"""Custom KPIs and operational metrics (M4-5: AC-KP4, AC-KP5), on the Q1 2026 KPI fixture
(revenue 1,000; cost of sales 600)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.kpi import custom
from fcp.modules.kpi.engine import Data, KpiSetEngine
from fcp.modules.kpi.models import CustomKpi, OperationalValue
from fcp.modules.metrics.api import RunInputs
from fcp.modules.tenancy.services import enter_workspace

from ..ledger.conftest import books, join
from .test_kpis import k, run, values

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "k"]

MARKUP = {
    "key": "MARKUP",
    "name": "Mark-up",
    "formula": 'flow("REVENUE") / flow("COST_OF_SALES")',
    "display": "ratio",
    "direction": "HIGHER_BETTER",
}
PER_HEAD = {
    "key": "REVENUE_PER_EMPLOYEE",
    "name": "Revenue per employee",
    "formula": 'flow("REVENUE") / count_metric("HEADCOUNT")',
    "display": "EUR",
    "direction": "HIGHER_BETTER",
    "convention": "Headcount at the end of the period.",
}


@pytest.fixture
def c(k: dict[str, Any], make_user: Make, api_client: Make) -> dict[str, Any]:
    slug = k["ws"]["slug"]
    k["accountant"] = join(
        k["client"], slug, make_user("acc@example.test", "Ann"), api_client, "accountant"
    )
    k["manager"] = join(
        k["client"], slug, make_user("fm@example.test", "Mo"), api_client, "finance_manager"
    )
    k["viewer"] = join(
        k["client"], slug, make_user("ro@example.test", "Ro"), api_client, "read_only"
    )
    return k


def post(c: dict[str, Any], path: str, body: dict[str, Any], client: Any = None) -> Any:
    return (client or c["client"]).post_json(f"{c['base']}/{path}", body)


def headcount(c: dict[str, Any], march: str = "5") -> str:
    made = post(
        c,
        "operational-metrics",
        {"key": "HEADCOUNT", "name": "Employees", "unit": "count", "aggregation": "LAST"},
        c["accountant"],
    )
    assert made.status_code == 201, made.content
    metric = made.json()["id"]
    for month, value in (("2026-01-01", "4"), ("2026-02-01", "5"), ("2026-03-01", march)):
        put = c["accountant"].put_json(
            f"{c['base']}/operational-metrics/{metric}/values", {"month": month, "value": value}
        )
        assert put.status_code == 200, put.content
    return str(metric)


def test_personal_kpis_are_private_and_never_stored(c: dict[str, Any]) -> None:
    made = post(c, "custom-kpis", {**MARKUP, "scope": "PERSONAL"}, c["viewer"])
    assert made.status_code == 201, made.content
    assert (made.json()["status"], made.json()["version"]) == ("ACTIVE", 1)
    assert [x["key"] for x in c["viewer"].get(f"{c['base']}/custom-kpis").json()] == ["MARKUP"]
    assert c["accountant"].get(f"{c['base']}/custom-kpis").json() == []
    body = run(c)
    assert "MARKUP" not in values(body)  # not part of the shared, stored set
    mine = c["viewer"].get(f"{c['base']}/kpi-sets/{body['run_id']}/personal").json()
    assert [(v["key"], v["definition_id"]) for v in mine] == [("MARKUP", "PERSONAL:MARKUP@1")]
    assert mine[0]["value"].startswith("1.6666666666")
    assert c["accountant"].get(f"{c['base']}/kpi-sets/{body['run_id']}/personal").json() == []
    # A revision is in use at once; the earlier version is kept, superseded.
    kpi = made.json()["id"]
    revised = post(
        c,
        f"custom-kpis/{kpi}/revise",
        {**MARKUP, "formula": 'flow("REVENUE") / flow("OPERATING_EXPENSES")'},
        c["viewer"],
    )
    assert revised.status_code == 201, revised.content
    listed = c["viewer"].get(f"{c['base']}/custom-kpis").json()
    assert [(x["version"], x["status"]) for x in listed] == [(1, "SUPERSEDED"), (2, "ACTIVE")]
    again = c["viewer"].get(f"{c['base']}/kpi-sets/{body['run_id']}/personal").json()
    assert again[0]["value"] == "10"  # 1,000 / 100
    assert post(c, f"custom-kpis/{kpi}/revise", MARKUP, c["accountant"]).status_code == 404
    assert (
        post(c, f"custom-kpis/{revised.json()['id']}/retire", {}, c["viewer"]).json()["status"]
        == "RETIRED"
    )
    c["client"].get(f"{c['base']}/custom-kpis")  # end under the owner's context


def test_workspace_kpis_need_approval_and_keep_their_version(c: dict[str, Any]) -> None:
    refused = post(c, "custom-kpis", {**PER_HEAD, "scope": "WORKSPACE"}, c["accountant"])
    assert refused.status_code == 422  # no HEADCOUNT metric yet
    assert "operational metric" in str(refused.json())
    headcount(c)
    assert (
        post(c, "custom-kpis", {**PER_HEAD, "scope": "WORKSPACE"}, c["viewer"]).status_code == 403
    )  # proposing needs kpi.definition.manage
    made = post(c, "custom-kpis", {**PER_HEAD, "scope": "WORKSPACE"}, c["manager"])
    assert made.status_code == 201, made.content
    kpi = made.json()
    assert (kpi["status"], kpi["unit"]) == ("SUBMITTED", "EUR")
    assert "REVENUE_PER_EMPLOYEE" not in values(run(c))  # not approved yet
    own = post(c, f"custom-kpis/{kpi['id']}/approve", {}, c["manager"])
    assert own.status_code == 409  # the author cannot approve
    assert post(c, f"custom-kpis/{kpi['id']}/approve", {}, c["accountant"]).status_code == 403
    assert post(c, f"custom-kpis/{kpi['id']}/reject", {"comment": ""}).status_code == 422
    approved = post(c, f"custom-kpis/{kpi['id']}/approve", {"comment": "OK"})
    assert approved.json()["status"] == "APPROVED"
    assert approved.json()["decided_by_name"]

    first = run(c)
    per_head = next(v for v in first["values"] if v["key"] == "REVENUE_PER_EMPLOYEE")
    assert (per_head["value"], per_head["definition_id"], per_head["category"]) == (
        "200",
        "WORKSPACE:REVENUE_PER_EMPLOYEE@1",
        "CUSTOM",
    )
    assert per_head["non_ledger"] is True  # AC-KP5: uses data entered by hand
    assert next(v for v in first["values"] if v["key"] == "DSO")["non_ledger"] is False

    # Version 2 waits for approval; version 1 stays in use until then (AC-KP4).
    v2 = post(
        c,
        f"custom-kpis/{kpi['id']}/revise",
        {**PER_HEAD, "formula": 'flow("COST_OF_SALES") / count_metric("HEADCOUNT")'},
        c["manager"],
    )
    assert v2.status_code == 201, v2.content
    assert post(c, f"custom-kpis/{kpi['id']}/revise", PER_HEAD, c["manager"]).status_code == 409
    second = run(c)
    assert (
        next(v for v in second["values"] if v["key"] == "REVENUE_PER_EMPLOYEE")["definition_id"]
        == "WORKSPACE:REVENUE_PER_EMPLOYEE@1"
    )
    post(c, f"custom-kpis/{v2.json()['id']}/approve", {})
    third = run(c)
    newest = next(v for v in third["values"] if v["key"] == "REVENUE_PER_EMPLOYEE")
    assert (newest["definition_id"], newest["value"]) == ("WORKSPACE:REVENUE_PER_EMPLOYEE@2", "120")
    statuses = [
        (x["version"], x["status"]) for x in c["client"].get(f"{c['base']}/custom-kpis").json()
    ]
    assert statuses == [(1, "SUPERSEDED"), (2, "APPROVED")]
    # The earlier set still names version 1 and still reproduces.
    kept = (
        c["client"]
        .get(f"{c['base']}/kpi-sets/latest?date_from=2026-01-01&date_to=2026-03-31")
        .json()
    )
    assert kept["run_id"] == third["run_id"]
    again = post(c, f"calc-runs/{first['run_id']}/reproduce", {})
    assert again.json()["reproduced"] is True
    c["client"].get(f"{c['base']}/custom-kpis")


def test_operational_values_are_versioned_and_pinned(c: dict[str, Any]) -> None:
    metric = headcount(c)
    post(c, "custom-kpis", {**PER_HEAD, "scope": "PERSONAL"}, c["accountant"])
    first = run(c)
    url = f"{c['base']}/operational-metrics/{metric}/values"
    fixed = c["accountant"].put_json(
        url, {"month": "2026-03-01", "value": "8", "note": "Two part-timers were missing"}
    )
    assert fixed.json()["version"] == 2
    history = (
        c["client"].get(f"{c['base']}/operational-metrics/{metric}/history?month=2026-03-01").json()
    )
    assert [(h["version"], h["value"]) for h in history] == [(1, "5"), (2, "8")]
    listed = c["viewer"].get(f"{c['base']}/operational-metrics").json()[0]
    assert (listed["source"], listed["nature"], listed["non_ledger"]) == ("MANUAL", "ACTUAL", True)
    assert listed["values"][-1]["value"] == "8"
    # The earlier set keeps the value it was computed with (snapshotted), the new one uses 8.
    old = c["accountant"].get(f"{c['base']}/kpi-sets/{first['run_id']}/personal").json()
    new = c["accountant"].get(f"{c['base']}/kpi-sets/{run(c)['run_id']}/personal").json()
    assert (old[0]["value"], new[0]["value"]) == ("200", "125")
    # A total metric with a month missing is not meaningful, with a reason.
    units = post(
        c,
        "operational-metrics",
        {"key": "UNITS", "name": "Units sold", "unit": "count", "aggregation": "SUM"},
        c["accountant"],
    ).json()
    c["accountant"].put_json(
        f"{c['base']}/operational-metrics/{units['id']}/values",
        {"month": "2026-01-01", "value": "10"},
    )
    post(
        c,
        "custom-kpis",
        {
            "key": "PRICE",
            "name": "Average price",
            "display": "EUR",
            "formula": 'flow("REVENUE") / count_metric("UNITS")',
            "direction": "HIGHER_BETTER",
            "scope": "PERSONAL",
        },
        c["accountant"],
    )
    priced = c["accountant"].get(f"{c['base']}/kpi-sets/{run(c)['run_id']}/personal").json()
    price = next(v for v in priced if v["key"] == "PRICE")
    assert price["value"] is None
    assert "no value for every month" in price["nm_reason"]
    # Checks on input.
    for body in ({"month": "2026-03-15", "value": "1"}, {"month": "2026-03-01", "value": "-1"}):
        assert c["accountant"].put_json(url, body).status_code == 422
    assert c["viewer"].put_json(url, {"month": "2026-03-01", "value": "1"}).status_code == 403
    dup = post(
        c,
        "operational-metrics",
        {"key": "HEADCOUNT", "name": "x", "unit": "count", "aggregation": "LAST"},
        c["accountant"],
    )
    assert dup.status_code == 409
    c["client"].get(f"{c['base']}/custom-kpis")


@pytest.mark.parametrize(
    ("formula", "display", "problem"),
    [
        ('flow("REVENUE" / 2', "ratio", "Expected"),
        ('flow("REVENUE") / flow("COST_OF_SALES")', "days", "needs days"),
        ('flow("NOT_A_LINE") / flow("REVENUE")', "ratio", "not a taxonomy line"),
        ('flow("REVENUE") / count_metric("NOBODY")', "EUR", "not a count operational metric"),
        ('flow("REVENUE") > 1', "ratio", "true or false"),
    ],
)
def test_check_reports_problems(
    c: dict[str, Any], formula: str, display: str, problem: str
) -> None:
    checked = post(c, "custom-kpis/check", {"formula": formula, "display": display})
    assert checked.status_code == 200, checked.content
    body = checked.json()
    assert body["ok"] is False
    assert any(problem in p for p in body["problems"]), body["problems"]


def test_check_dry_runs_and_create_validates(c: dict[str, Any]) -> None:
    checked = post(c, "custom-kpis/check", {"formula": MARKUP["formula"], "display": "ratio"})
    body = checked.json()
    assert (body["ok"], body["unit"]) == (True, "ratio")
    assert body["dry_run_month"]  # the last complete month
    assert body["dry_run_reason"] == "denominator zero"  # no postings in it
    bad: list[dict[str, Any]] = [
        {**MARKUP, "key": "lower"},
        {**MARKUP, "key": "DSO"},
        {**MARKUP, "name": " "},
        {**MARKUP, "formula": "flow("},
    ]
    for kpi in bad:
        assert post(c, "custom-kpis", {**kpi, "scope": "PERSONAL"}).status_code == 422, kpi
    assert post(c, "custom-kpis", {**MARKUP, "scope": "PERSONAL"}).status_code == 201
    assert post(c, "custom-kpis", {**MARKUP, "scope": "PERSONAL"}).status_code == 409


def test_database_keeps_versions_and_values(c: dict[str, Any]) -> None:
    headcount(c)
    kpi = post(c, "custom-kpis", {**PER_HEAD, "scope": "WORKSPACE"}, c["manager"]).json()
    with transaction.atomic():
        set_context(tenant_id=c["ws"]["id"])
        row = CustomKpi.objects.get(id=kpi["id"])
        changes: list[tuple[Callable[[], Any], str]] = [
            (lambda: CustomKpi.objects.filter(id=row.id).update(formula="1"), "cannot change"),
            (lambda: CustomKpi.objects.filter(id=row.id).update(status="RETIRED"), "cannot change"),
            (
                lambda: CustomKpi.objects.filter(id=row.id).update(
                    status="APPROVED", decided_by_id=row.owner_id
                ),
                "kpi_custom_sod",
            ),
            (
                lambda: OperationalValue.objects.filter(month="2026-01-01").update(value=9),
                "immutable",
            ),
        ]
        for change, message in changes:
            with pytest.raises(DatabaseError, match=message), transaction.atomic():
                change()
        for table in ("kpi_custom", "kpi_operational_value"):
            with (
                pytest.raises(DatabaseError, match="kept"),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(f"DELETE FROM {table}")  # noqa: S608 (fixed table names)


def test_service_checks(c: dict[str, Any]) -> None:
    metric = headcount(c)
    ws = post(c, "custom-kpis", {**PER_HEAD, "scope": "WORKSPACE"}, c["manager"]).json()
    with transaction.atomic():
        ctx = enter_workspace(c["owner"], c["ws"]["slug"])
        entity = c["entity"]["id"]
        good = custom.KpiInput("GOOD", "Good", MARKUP["formula"], "ratio", "HIGHER_BETTER")
        invalid: list[Callable[[], object]] = [
            lambda: custom.check(ctx, entity, "1", "weekly"),
            lambda: custom.create(ctx, entity, "TEAM", good),
            lambda: custom.create(
                ctx, entity, "PERSONAL", custom.KpiInput("GOOD", "Good", "1", "ratio", "SIDEWAYS")
            ),
            lambda: custom.create(
                ctx,
                entity,
                "PERSONAL",
                custom.KpiInput("GOOD", "Good", "1+" * 1001, "ratio", "HIGHER_BETTER"),
            ),
            lambda: custom.create_metric(ctx, entity, custom.MetricInput("x", "X", "count", "SUM")),
            lambda: custom.create_metric(
                ctx, entity, custom.MetricInput("XX", " ", "count", "SUM")
            ),
            lambda: custom.create_metric(ctx, entity, custom.MetricInput("XX", "X", "kg", "SUM")),
            lambda: custom.create_metric(
                ctx, entity, custom.MetricInput("XX", "X", "count", "AVG")
            ),
            lambda: custom.set_value(ctx, entity, uuid4(), date(2026, 1, 1), "1"),
            lambda: custom.set_value(ctx, entity, UUID(metric), date(2026, 1, 1), "abc"),
            lambda: custom.set_value(ctx, entity, UUID(metric), date(2026, 1, 1), "1.00001"),
        ]
        for call in invalid:
            with pytest.raises((ValidationFailedError, NotFoundError)), transaction.atomic():
                call()
        conflicts: list[Callable[[], object]] = [
            lambda: custom.revise(
                ctx,
                entity,
                ws["id"],
                custom.KpiInput("OTHER", "x", PER_HEAD["formula"], "EUR", "HIGHER_BETTER"),
            ),
            lambda: custom.retire(ctx, entity, ws["id"]),  # still waiting for approval
        ]
        for call in conflicts:
            with pytest.raises(ConflictError), transaction.atomic():
                call()
        custom.decide(ctx, entity, ws["id"], approve=False, comment="Use average headcount")
        with pytest.raises(ConflictError), transaction.atomic():
            custom.decide(ctx, entity, ws["id"], approve=True)
        forecast_run = uuid4()
        with pytest.raises(NotFoundError), transaction.atomic():
            custom.personal_values(ctx, entity, forecast_run)
        made = custom.create(ctx, entity, "WORKSPACE", good)
        assert made.status == "SUBMITTED"
    c["client"].get(f"{c['base']}/custom-kpis")


def test_missing_or_mismatched_metrics_are_not_meaningful_in_the_engine() -> None:
    inputs = RunInputs(
        "KPI_SET",
        "1",
        uuid4(),
        date(2026, 1, 31),
        1,
        {
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "library": "TEST",
            "accounts": {},
            "operational": {
                "HEADCOUNT": {"unit": "count", "aggregation": "LAST", "values": {"2026-01-01": "4"}}
            },
        },
    )
    defs = [
        {"id": f"T:{key}", "key": key, "formula": formula, "nm_reason": ""}
        for key, formula in (
            ("A", 'amount_metric("HEADCOUNT")'),
            ("B", 'count_metric("GONE")'),
            ("C", 'count_metric("HEADCOUNT")'),
        )
    ]
    out = {v.series_key: v for v in KpiSetEngine().compute(inputs, Data(defs, {}, {})).values}
    assert out["kpi.A"].nm_reason == "No EUR metric HEADCOUNT"
    assert out["kpi.B"].nm_reason == "No count metric GONE"
    assert out["kpi.C"].value == Decimal(4)
    assert out["kpi.C"].dimensions == ("NON_LEDGER",)
