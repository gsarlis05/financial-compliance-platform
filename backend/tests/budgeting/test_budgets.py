"""Budgets: lifecycle, segregation of duties, revisions and database immutability (M4-1, AC-BU1)."""

from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import ValidationFailedError
from fcp.modules.budgeting import services
from fcp.modules.budgeting.models import Budget, BudgetAmount, BudgetLine, BudgetVersion
from fcp.modules.tenancy.services import enter_workspace

from ..ledger.conftest import books, join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]

MONTHS = [f"2026-{m:02d}-01" for m in range(1, 13)]


def sales(amount: str = "1000.00") -> dict[str, Any]:
    return {"taxonomy_code": "REV.SALES", "amounts": dict.fromkeys(MONTHS, amount)}


@pytest.fixture
def bu(books: dict[str, Any], make_user: Make, api_client: Make) -> dict[str, Any]:
    slug = books["ws"]["slug"]
    books["preparer"] = join(
        books["client"],
        slug,
        make_user("prep@example.test", "Pat Preparer"),
        api_client,
        "accountant",
    )
    books["manager"] = join(
        books["client"],
        slug,
        make_user("fm@example.test", "Mo Manager"),
        api_client,
        "finance_manager",
    )
    books["viewer"] = join(
        books["client"], slug, make_user("ro@example.test"), api_client, "read_only"
    )
    return books


def create(bu: dict[str, Any], client: Any = None, **extra: Any) -> Any:
    body = {"name": "Budget 2026", "fiscal_year_id": bu["fy"]["id"], **extra}
    return (client or bu["preparer"]).post_json(f"{bu['base']}/budgets", body)


def act(
    bu: dict[str, Any],
    client: Any,
    version_id: str,
    action: str,
    body: dict[str, Any] | None = None,
) -> Any:
    return client.post_json(f"{bu['base']}/budget-versions/{version_id}/{action}", body or {})


def save(
    bu: dict[str, Any], version_id: str, lines: list[dict[str, Any]], client: Any = None
) -> Any:
    return (client or bu["preparer"]).put_json(
        f"{bu['base']}/budget-versions/{version_id}/lines", {"lines": lines}
    )


def test_lifecycle_with_revision_keeps_original_and_current(bu: dict[str, Any]) -> None:
    created = create(bu)
    assert created.status_code == 201, created.content
    budget = created.json()
    v1 = budget["open_version_id"]
    assert (budget["kind"], budget["original_version_id"], budget["current_version_id"]) == (
        "ANNUAL",
        None,
        None,
    )
    saved = save(
        bu,
        v1,
        [
            sales(),
            {
                "taxonomy_code": "OPEX.RENT",
                "amounts": {"2026-01-01": "500.00", "2026-12-01": "500.50"},
            },
        ],
    )
    assert saved.status_code == 200, saved.content
    detail = saved.json()
    assert detail["months"] == MONTHS
    rent = detail["lines"][1]
    assert rent["nature"] == "BUDGET"
    assert rent["direction"] == "LOWER_BETTER"
    assert rent["amounts"][0] == "500.00"
    assert rent["amounts"][1] == "0.00"
    assert rent["quarters"] == ["500.00", "0.00", "0.00", "500.50"]
    assert rent["total"] == "1000.50"
    assert detail["lines"][0]["quarters"] == ["3000.00"] * 4
    assert detail["total"] == "13000.50"

    # The preparer cannot approve; the manager approves what was submitted.
    assert act(bu, bu["preparer"], v1, "submit").json()["status"] == "SUBMITTED"
    assert act(bu, bu["preparer"], v1, "approve").status_code == 403
    assert save(bu, v1, [sales("1.00")]).status_code == 409
    approved = act(bu, bu["manager"], v1, "approve", {"comment": "Fine"})
    assert approved.status_code == 200, approved.content
    assert (approved.json()["status"], approved.json()["sod_applied"]) == ("APPROVED", True)
    assert act(bu, bu["manager"], v1, "lock").json()["status"] == "LOCKED"

    # A revision is a new draft with the same lines and a reason.
    assert act(bu, bu["preparer"], v1, "revise", {"reason": " "}).status_code == 422
    revised = act(bu, bu["preparer"], v1, "revise", {"reason": "New customer won"})
    assert revised.status_code == 201, revised.content
    v2 = revised.json()
    assert (v2["number"], v2["status"], v2["supersedes_id"], v2["total"]) == (
        2,
        "DRAFT",
        v1,
        "13000.50",
    )
    assert act(bu, bu["preparer"], v1, "revise", {"reason": "again"}).status_code == 409
    assert save(bu, v2["id"], [sales("1500.00")]).status_code == 200
    act(bu, bu["preparer"], v2["id"], "submit")
    assert act(bu, bu["manager"], v2["id"], "approve").status_code == 200

    final = bu["viewer"].get(f"{bu['base']}/budgets/{budget['id']}").json()
    assert final["original_version_id"] == v1
    assert final["current_version_id"] == v2["id"]
    assert final["open_version_id"] is None
    assert [v["status"] for v in final["versions"]] == ["SUPERSEDED", "APPROVED"]
    original = bu["viewer"].get(f"{bu['base']}/budget-versions/{v1}").json()
    assert original["total"] == "13000.50"  # the original stays reportable

    trail = bu["viewer"].get(f"{bu['base']}/budgets/{budget['id']}/events").json()
    assert [(e["version_number"], e["action"]) for e in trail] == [
        (1, "CREATED"),
        (1, "LINES_SAVED"),
        (1, "SUBMITTED"),
        (1, "APPROVED"),
        (1, "LOCKED"),
        (1, "SUPERSEDED"),
        (2, "REVISION_STARTED"),
        (2, "LINES_SAVED"),
        (2, "SUBMITTED"),
        (2, "APPROVED"),
    ]
    assert trail[3]["actor_name"] == "Mo Manager"
    assert trail[3]["comment"] == "Fine"
    assert trail[6]["comment"] == "New customer won"


def test_segregation_of_duties_is_configurable(bu: dict[str, Any]) -> None:
    budget = create(bu, bu["manager"]).json()
    v1 = budget["open_version_id"]
    save(bu, v1, [sales()], bu["manager"])
    act(bu, bu["manager"], v1, "submit")
    refused = act(bu, bu["manager"], v1, "approve")
    assert refused.status_code == 409
    assert refused.json()["code"] == "budgeting.segregation_of_duties"
    settings = f"{bu['base']}/budget-settings"
    assert bu["viewer"].get(settings).json() == {
        "sod_required": True,
        "explain_above_amount": "1000.00",
        "explain_above_percent": "10.00",
    }
    assert bu["preparer"].put_json(settings, {"sod_required": False}).status_code == 403
    with transaction.atomic():  # the database refuses it too
        set_context(tenant_id=bu["ws"]["id"])
        with pytest.raises(DatabaseError, match="budgeting_version_sod"), transaction.atomic():
            BudgetVersion.objects.filter(id=v1).update(
                status="APPROVED",
                approved_by=bu["manager"].user,
                approved_at=timezone.now(),
                sod_applied=True,
            )
    assert bu["manager"].put_json(settings, {"sod_required": False}).status_code == 200
    approved = act(bu, bu["manager"], v1, "approve")
    assert approved.status_code == 200, approved.content
    assert approved.json()["sod_applied"] is False


def test_return_to_draft_needs_a_comment(bu: dict[str, Any]) -> None:
    v1 = create(bu).json()["open_version_id"]
    assert act(bu, bu["preparer"], v1, "submit").status_code == 409  # no lines yet
    save(bu, v1, [sales()])
    act(bu, bu["preparer"], v1, "submit")
    assert act(bu, bu["manager"], v1, "return", {"comment": ""}).status_code == 422
    returned = act(bu, bu["manager"], v1, "return", {"comment": "Rent is missing"})
    assert returned.json()["status"] == "DRAFT"
    assert returned.json()["submitted_by_id"] is None
    assert act(bu, bu["manager"], v1, "lock").status_code == 409
    assert act(bu, bu["preparer"], v1, "revise", {"reason": "x"}).status_code == 409
    assert save(bu, v1, [sales("2.00")]).status_code == 200


def test_permissions_and_isolation(
    bu: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    assert create(bu, bu["viewer"]).status_code == 403
    budget = create(bu).json()
    v1 = budget["open_version_id"]
    assert save(bu, v1, [sales()], bu["viewer"]).status_code == 403
    assert bu["viewer"].get(f"{bu['base']}/budget-versions/{v1}").status_code == 200
    assert bu["viewer"].get(f"{bu['base']}/budgets").json()[0]["id"] == budget["id"]
    stranger = make_user("x@example.test")
    make_workspace(stranger, name="Other")
    other = api_client(stranger)
    assert other.get(f"{bu['base']}/budget-versions/{v1}").status_code == 404
    assert other.get(f"{bu['base']}/budgets").status_code == 404
    assert bu["viewer"].get(f"{bu['base']}/budget-versions/{uuid4()}").status_code == 404
    assert bu["viewer"].get(f"{bu['base']}/budgets/{uuid4()}").status_code == 404
    assert create(bu).status_code == 409  # same name, same year
    bu["client"].get(f"{bu['base']}/budgets")  # end under the owner's context


def _dimension(bu: dict[str, Any], kind: str, code: str) -> str:
    dim = (
        bu["client"]
        .post_json(f"{bu['base']}/dimensions", {"code": code, "name": code.title(), "kind": kind})
        .json()
    )
    value = bu["client"].post_json(
        f"{bu['base']}/dimensions/{dim['id']}/values", {"code": f"{code}1", "name": "One"}
    )
    assert value.status_code == 201, value.content
    return str(value.json()["id"])


def test_departmental_budget_and_line_validation(bu: dict[str, Any]) -> None:
    dept = _dimension(bu, "DEPARTMENT", "DEPT")
    project = _dimension(bu, "PROJECT", "PRJ")
    assert create(bu, kind="DEPARTMENTAL").status_code == 422
    assert create(bu, kind="DEPARTMENTAL", dimension_value_id=project).status_code == 422
    assert create(bu, kind="ANNUAL", dimension_value_id=dept).status_code == 422
    assert create(bu, name=" ").status_code == 422
    assert create(bu, fiscal_year_id=str(uuid4())).status_code == 422
    made = create(bu, name="Sales dept", kind="DEPARTMENTAL", dimension_value_id=dept)
    assert made.status_code == 201, made.content
    v1 = made.json()["open_version_id"]
    saved = save(bu, v1, [sales()])
    assert saved.json()["lines"][0]["dimension_value_id"] == dept  # takes the budget's value
    assert save(bu, v1, [{**sales(), "dimension_value_id": project}]).status_code == 422

    annual = create(bu).json()["open_version_id"]
    postable = next(a for a in bu["accounts"].values() if a["is_postable"])
    header = next(a for a in bu["accounts"].values() if not a["is_postable"])
    bad: list[dict[str, Any]] = [
        {"taxonomy_code": "NOPE"},
        {},
        {"taxonomy_code": "REV.SALES", "account_id": postable["id"]},
        {"account_id": header["id"]},
        {"account_id": str(uuid4())},
        {"taxonomy_code": "REV.SALES", "amounts": {"2027-01-01": "1.00"}},
        {"taxonomy_code": "REV.SALES", "dimension_value_id": str(uuid4())},
        {"taxonomy_code": "REV.SALES", "note": "x" * 301},
    ]
    for line in bad:
        assert save(bu, annual, [line]).status_code == 422, line
    assert save(bu, annual, [sales(), sales()]).status_code == 422  # duplicate
    assert save(bu, annual, [sales("1.001")]).status_code == 422  # 3 decimals
    ok = save(
        bu,
        annual,
        [
            {"account_id": postable["id"], "amounts": {"2026-03-01": "-5.00"}},
            {**sales(), "dimension_value_id": dept},
        ],
    )
    assert ok.status_code == 200, ok.content
    assert ok.json()["lines"][0]["taxonomy_code"] is None
    assert ok.json()["lines"][0]["quarters"][0] == "-5.00"


def _sql(statement: str, *params: Any) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params)


def test_database_refuses_changes_to_submitted_and_approved_versions(bu: dict[str, Any]) -> None:
    v1 = create(bu).json()["open_version_id"]
    save(bu, v1, [sales()])
    act(bu, bu["preparer"], v1, "submit")
    act(bu, bu["manager"], v1, "approve")
    with transaction.atomic():
        set_context(tenant_id=bu["ws"]["id"])
        line = BudgetLine.objects.get(version_id=v1)
        version = BudgetVersion.objects.get(id=v1)
        refusals: list[tuple[Callable[[], Any], str]] = [
            (lambda: BudgetAmount.objects.filter(line=line).update(amount=1), "only change"),
            (lambda: BudgetAmount.objects.filter(line=line).delete(), "only change"),
            (lambda: BudgetLine.objects.filter(id=line.id).update(note="x"), "only change"),
            (
                lambda: BudgetLine.objects.create(
                    tenant_id=line.tenant_id,
                    legal_entity_id=line.legal_entity_id,
                    version=version,
                    seq=9,
                    taxonomy_line_id=line.taxonomy_line_id,
                    dimension_value_id=uuid4(),
                ),
                "only change",
            ),
            (lambda: BudgetVersion.objects.filter(id=v1).update(reason="edited"), "cannot change"),
            (lambda: BudgetVersion.objects.filter(id=v1).update(status="DRAFT"), "cannot change"),
            (
                lambda: BudgetVersion.objects.filter(id=v1).update(status="SUBMITTED"),
                "cannot change",
            ),
            (
                lambda: BudgetVersion.objects.filter(id=v1).update(
                    status="LOCKED", approved_at=None
                ),
                "cannot change",
            ),
            (lambda: _sql("DELETE FROM budgeting_version WHERE id = %s", v1), "kept"),
            (
                lambda: Budget.objects.filter(id=version.budget_id).update(kind="PROJECT"),
                "never change",
            ),
            (lambda: _sql("DELETE FROM budgeting_budget WHERE id = %s", version.budget_id), "kept"),
        ]
        for change, message in refusals:
            with pytest.raises(DatabaseError, match=message), transaction.atomic():
                change()
        with pytest.raises(DatabaseError, match="starts as a draft"), transaction.atomic():
            BudgetVersion.objects.create(
                tenant_id=version.tenant_id,
                legal_entity_id=version.legal_entity_id,
                budget_id=version.budget_id,
                number=7,
                supersedes=version,
                reason="x",
                status="APPROVED",
                created_by_id=version.created_by_id,
            )
        Budget.objects.filter(id=version.budget_id).update(name="Renamed")  # names may change
        assert BudgetVersion.objects.get(id=v1).status == "APPROVED"


def test_reason_filter_and_service_level_checks(bu: dict[str, Any]) -> None:
    budget = create(bu).json()
    v1 = budget["open_version_id"]
    reason = f"{bu['base']}/budget-versions/{v1}/reason"
    assert bu["preparer"].put_json(reason, {"reason": "First draft"}).json()["reason"] == (
        "First draft"
    )
    listed = bu["viewer"].get(f"{bu['base']}/budgets?fiscal_year_id={bu['fy']['id']}").json()
    assert [b["id"] for b in listed] == [budget["id"]]
    assert bu["viewer"].get(f"{bu['base']}/budgets?fiscal_year_id={uuid4()}").json() == []
    save(bu, v1, [sales()])
    act(bu, bu["preparer"], v1, "submit")
    act(bu, bu["manager"], v1, "approve")
    v2 = act(bu, bu["preparer"], v1, "revise", {"reason": "Q2 update"}).json()["id"]
    path = f"{bu['base']}/budget-versions/{v2}/reason"
    assert bu["preparer"].put_json(path, {"reason": ""}).status_code == 422
    assert (
        bu["preparer"]
        .put_json(f"{bu['base']}/budget-versions/{v1}/reason", {"reason": "x"})
        .status_code
        == 409
    )

    with transaction.atomic():
        ctx = enter_workspace(bu["owner"], bu["ws"]["slug"])
        entity = bu["entity"]["id"]
        version = services._version(entity, v2)
        months = services.fiscal_months(date(2026, 1, 1), date(2026, 12, 31))
        tax = services.LineInput(taxonomy_code="REV.SALES")
        cases: list[Any] = [
            [services.LineInput(taxonomy_code="REV.SALES", method="GUESS")],
            [services.LineInput(taxonomy_code="REV.SALES", note="x" * 301)],
            [services.LineInput(taxonomy_code="REV.SALES", amounts={months[0]: Decimal("1e16")})],
            [tax] * (services.MAX_LINES + 1),
        ]
        for lines in cases:
            with pytest.raises(ValidationFailedError):
                services._validated(ctx, version.budget, months, lines)
        with pytest.raises(ValidationFailedError):
            services.create_budget(
                ctx,
                entity,
                services.BudgetInput("Other", version.budget.fiscal_year_id, kind="WEEKLY"),
            )
        with pytest.raises(ValidationFailedError):
            services.set_reason(ctx, entity, v2, "x" * 501)
        assert services.set_settings(ctx, entity, services.Settings(sod_required=True)).sod_required
        with pytest.raises(ValidationFailedError):
            services.set_settings(ctx, entity, services.Settings(True, Decimal(-1)))
    # A short first fiscal year: the last quarter holds what is left.
    seven = [date(2026, m, 1) for m in range(6, 13)]
    assert services.quarters(seven, [Decimal(1)] * 7) == [Decimal(3), Decimal(3), Decimal(1)]
