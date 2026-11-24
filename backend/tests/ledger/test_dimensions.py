"""Analytical dimensions on journal lines (M2-1, AC-M2-1)."""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger.models import JournalEntry, LineDimension

from .conftest import join
from .test_entries import act, post_through_workflow, reviewer

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["reviewer"]


def commit_point() -> None:
    """Run the deferred posting checks now, as a real request's commit would (tests share one
    transaction, so otherwise they would run at teardown against later state)."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute("SET CONSTRAINTS ALL DEFERRED")


def dims_url(books: dict[str, Any]) -> str:
    return f"{books['base']}/dimensions"


def make_dimension(
    books: dict[str, Any],
    code: str = "DEPT",
    kind: str = "DEPARTMENT",
    values: tuple[str, ...] = ("SALES", "ADMIN"),
) -> dict[str, Any]:
    created = books["client"].post_json(dims_url(books), {"code": code, "name": code, "kind": kind})
    assert created.status_code == 201, created.content
    dim: dict[str, Any] = created.json()
    dim["v"] = {}
    for value in values:
        made = books["client"].post_json(
            f"{dims_url(books)}/{dim['id']}/values", {"code": value, "name": value.title()}
        )
        assert made.status_code == 201, made.content
        dim["v"][value] = made.json()["id"]
    return dim


def set_rules(books: dict[str, Any], code: str, rules: list[dict[str, str]]) -> Any:
    account = books["accounts"][code]["id"]
    return books["client"].put_json(f"{books['base']}/accounts/{account}/dimension-rules", rules)


def rent(books: dict[str, Any], *value_ids: str, amount: str = "100.00") -> list[Any]:
    acc = books["accounts"]
    return [
        {"account_id": acc["6100"]["id"], "debit": amount, "dimension_value_ids": list(value_ids)},
        {"account_id": acc["1300"]["id"], "credit": amount},
    ]


def entry(books: dict[str, Any], lines: list[Any], day: str = "2026-03-15") -> Any:
    return books["client"].post_json(
        f"{books['base']}/journal-entries",
        {"accounting_date": day, "description": "Rent", "lines": lines},
    )


# --- set-up --------------------------------------------------------------------------------------


def test_dimensions_and_values_are_created_listed_and_audited(books: dict[str, Any]) -> None:
    dim = make_dimension(books)
    listed = books["client"].get(dims_url(books)).json()
    assert [d["code"] for d in listed] == ["DEPT"]
    assert [v["code"] for v in listed[0]["values"]] == ["ADMIN", "SALES"]
    child = books["client"].post_json(
        f"{dims_url(books)}/{dim['id']}/values",
        {"code": "sales-cy", "name": "Sales Cyprus", "parent_code": "SALES"},
    )
    assert child.status_code == 201
    assert child.json()["code"] == "SALES-CY"
    assert child.json()["parent_id"] == dim["v"]["SALES"]
    set_context(tenant_id=books["ws"]["id"])
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"ledger.dimension.created", "ledger.dimension_value.created"} <= actions


@pytest.mark.parametrize(
    ("body", "status", "field"),
    [
        ({"code": "bad code!", "name": "x", "kind": "PROJECT"}, 422, "code"),
        ({"code": "P", "name": "x", "kind": "PLANET"}, 422, "kind"),
    ],
)
def test_dimension_validation(
    books: dict[str, Any], body: dict[str, str], status: int, field: str
) -> None:
    response = books["client"].post_json(dims_url(books), body)
    assert response.status_code == status


def test_duplicate_codes_conflict(books: dict[str, Any]) -> None:
    dim = make_dimension(books)
    again = books["client"].post_json(
        dims_url(books), {"code": "dept", "name": "x", "kind": "DEPARTMENT"}
    )
    assert again.status_code == 409
    value = books["client"].post_json(
        f"{dims_url(books)}/{dim['id']}/values", {"code": "sales", "name": "Again"}
    )
    assert value.status_code == 409
    parent = books["client"].post_json(
        f"{dims_url(books)}/{dim['id']}/values", {"code": "X", "name": "x", "parent_code": "NOPE"}
    )
    assert parent.status_code == 422


def test_rename_and_deactivate(books: dict[str, Any]) -> None:
    dim = make_dimension(books)
    renamed = books["client"].patch(
        f"{dims_url(books)}/{dim['id']}",
        {"name": "Departments", "status": "INACTIVE"},
        content_type="application/json",
        headers={"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value},
    )
    assert renamed.json()["name"] == "Departments"
    assert renamed.json()["status"] == "INACTIVE"
    value = books["client"].patch(
        f"{books['base']}/dimension-values/{dim['v']['SALES']}",
        {"status": "INACTIVE"},
        content_type="application/json",
        headers={"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value},
    )
    assert value.json()["status"] == "INACTIVE"
    missing = books["client"].patch(
        f"{books['base']}/dimension-values/{uuid.uuid4()}",
        {"name": "x"},
        content_type="application/json",
        headers={"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value},
    )
    assert missing.status_code == 404


def test_only_managers_change_dimensions(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(
        books["client"], books["ws"]["slug"], make_user("ro@example.test"), api_client, "read_only"
    )
    assert viewer.get(dims_url(books)).status_code == 200
    denied = viewer.post_json(dims_url(books), {"code": "P", "name": "P", "kind": "PROJECT"})
    assert denied.status_code == 403


# --- tagging lines -------------------------------------------------------------------------------


def test_lines_carry_tags_in_hash_audit_and_response(books: dict[str, Any], reviewer: Any) -> None:
    dim = make_dimension(books)
    tagged = entry(books, rent(books, dim["v"]["SALES"])).json()
    line = tagged["lines"][0]
    assert line["dimensions"] == [
        {
            "dimension_id": dim["id"],
            "dimension_code": "DEPT",
            "value_id": dim["v"]["SALES"],
            "value_code": "SALES",
            "value_name": "Sales",
        }
    ]
    assert tagged["lines"][1]["dimensions"] == []
    untagged = entry(books, rent(books)).json()
    act(books, tagged["id"], "submit")
    act(books, untagged["id"], "submit")
    hashes = {
        e["id"]: e["content_hash"]
        for e in books["client"].get(f"{books['base']}/journal-entries").json()
    }
    assert hashes[tagged["id"]] != hashes[untagged["id"]]  # the tag is part of what is approved
    set_context(tenant_id=books["ws"]["id"])
    created = AuditEvent.objects.get(subject_id=str(tagged["id"]), action="ledger.entry.created")
    assert "DEPT=SALES" in str(created.changes)


@pytest.mark.parametrize("problem", ["unknown", "two_of_one_dimension", "inactive", "foreign"])
def test_invalid_tags_are_rejected(
    books: dict[str, Any], problem: str, make_user: Make, make_workspace: Make, api_client: Make
) -> None:
    dim = make_dimension(books)
    if problem == "unknown":
        values = [str(uuid.uuid4())]
    elif problem == "two_of_one_dimension":
        values = [dim["v"]["SALES"], dim["v"]["ADMIN"]]
    elif problem == "inactive":
        books["client"].patch(
            f"{books['base']}/dimension-values/{dim['v']['SALES']}",
            {"status": "INACTIVE"},
            content_type="application/json",
            headers={"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value},
        )
        values = [dim["v"]["SALES"]]
    else:  # a value of another entity in another workspace
        other_owner = make_user("other@example.test")
        ws = make_workspace(other_owner, name="Other")
        other = api_client(other_owner)
        other_entity = other.get(f"/api/w/{ws['slug']}/entities").json()[0]
        base = f"/api/w/{ws['slug']}/entities/{other_entity['id']}/dimensions"
        d = other.post_json(base, {"code": "DEPT", "name": "D", "kind": "DEPARTMENT"}).json()
        made = other.post_json(f"{base}/{d['id']}/values", {"code": "X", "name": "X"})
        values = [made.json()["id"]]
    response = entry(books, rent(books, *values))
    assert response.status_code == 422
    assert response.json()["code"] == "ledger.line.dimension_invalid"


# --- account rules -------------------------------------------------------------------------------


def test_required_dimension_blocks_submission_until_tagged(
    books: dict[str, Any], reviewer: Any
) -> None:
    dim = make_dimension(books)
    required = [{"dimension_id": dim["id"], "rule": "REQUIRED"}]
    assert set_rules(books, "6100", required).status_code == 200
    draft = entry(books, rent(books)).json()  # drafts may be incomplete
    refused = act(books, draft["id"], "submit")
    assert refused.status_code == 422
    assert refused.json()["code"] == "ledger.line.dimension_required"
    assert "requires a DEPT value" in refused.json()["detail"]
    fixed = books["client"].put_json(
        f"{books['base']}/journal-entries/{draft['id']}",
        {
            "accounting_date": "2026-03-15",
            "description": "Rent",
            "lines": rent(books, dim["v"]["ADMIN"]),
        },
    )
    assert fixed.status_code == 200
    assert act(books, draft["id"], "submit").status_code == 200
    assert act(books, draft["id"], "approve", reviewer).status_code == 200
    assert act(books, draft["id"], "post", reviewer).json()["status"] == "POSTED"
    rules = (
        books["client"]
        .get(f"{books['base']}/accounts/{books['accounts']['6100']['id']}/dimension-rules")
        .json()
    )
    assert rules == [{"dimension_id": dim["id"], "rule": "REQUIRED"}]


def test_blocked_dimension_is_refused(books: dict[str, Any]) -> None:
    dim = make_dimension(books)
    set_rules(books, "6100", [{"dimension_id": dim["id"], "rule": "BLOCKED"}])
    draft = entry(books, rent(books, dim["v"]["SALES"])).json()
    refused = act(books, draft["id"], "submit")
    assert refused.status_code == 422
    assert "does not allow DEPT" in refused.json()["detail"]


def test_value_deactivated_after_submission_blocks_posting(
    books: dict[str, Any], reviewer: Any
) -> None:
    dim = make_dimension(books)
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    draft = entry(books, rent(books, dim["v"]["SALES"])).json()
    books["client"].patch(
        f"{books['base']}/dimension-values/{dim['v']['SALES']}",
        {"status": "INACTIVE"},
        content_type="application/json",
        headers={"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value},
    )
    refused = act(books, draft["id"], "post")
    assert refused.status_code == 422
    assert "inactive" in refused.json()["detail"]


@pytest.mark.parametrize(
    ("rules", "field"),
    [
        ([{"dimension_id": "RANDOM", "rule": "REQUIRED"}], "rules.0.dimension_id"),
        (
            [
                {"dimension_id": "DIM", "rule": "REQUIRED"},
                {"dimension_id": "DIM", "rule": "BLOCKED"},
            ],
            "rules.1.dimension_id",
        ),
    ],
)
def test_rule_validation(books: dict[str, Any], rules: list[dict[str, str]], field: str) -> None:
    dim = make_dimension(books)
    resolved = [
        {**r, "dimension_id": dim["id"] if r["dimension_id"] == "DIM" else str(uuid.uuid4())}
        for r in rules
    ]
    response = set_rules(books, "6100", resolved)
    assert response.status_code == 422
    assert field in response.json()["errors"]


def test_rules_for_unknown_account_are_404(books: dict[str, Any]) -> None:
    response = books["client"].put_json(
        f"{books['base']}/accounts/{uuid.uuid4()}/dimension-rules", []
    )
    assert response.status_code == 404


# --- database enforcement ------------------------------------------------------------------------


def _post_bypassing_the_application(books: dict[str, Any], entry_id: str) -> None:
    """Simulate a bug or direct SQL access: set POSTED without the application's checks."""
    with transaction.atomic():
        set_context(tenant_id=books["ws"]["id"])
        period = next(p["id"] for p in books["fy"]["periods"] if p["number"] == 3)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(
                "UPDATE ledger_journal_entry SET status = 'POSTED', entry_no = 999, "
                "posting_seq = 999, period_id = %s, posted_at = now() WHERE id = %s",
                [period, entry_id],
            )


def test_database_rejects_posting_without_a_required_dimension(books: dict[str, Any]) -> None:
    dim = make_dimension(books)
    set_rules(books, "6100", [{"dimension_id": dim["id"], "rule": "REQUIRED"}])
    draft = entry(books, rent(books)).json()
    with pytest.raises(DatabaseError, match="lacks a dimension required"):
        _post_bypassing_the_application(books, draft["id"])


def test_database_rejects_posting_a_blocked_dimension(books: dict[str, Any]) -> None:
    dim = make_dimension(books)
    draft = entry(books, rent(books, dim["v"]["SALES"])).json()
    set_rules(books, "6100", [{"dimension_id": dim["id"], "rule": "BLOCKED"}])
    with pytest.raises(DatabaseError, match="blocked, inactive or foreign"):
        _post_bypassing_the_application(books, draft["id"])


def test_tags_of_posted_lines_are_immutable(books: dict[str, Any], reviewer: Any) -> None:
    dim = make_dimension(books)
    lines = (("6100", "100.00", "0"), ("1300", "0", "100.00"))
    posted = post_through_workflow(books, reviewer, *lines)
    set_context(tenant_id=books["ws"]["id"])
    entry_obj = JournalEntry.objects.get(id=posted["id"])
    line = entry_obj.lines.get(line_no=1)
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        LineDimension.objects.create(
            tenant_id=books["ws"]["id"],
            line=line,
            dimension_id=dim["id"],
            value_id=dim["v"]["SALES"],
        )


def test_database_keeps_a_value_inside_its_dimension(books: dict[str, Any]) -> None:
    dept = make_dimension(books)
    proj = make_dimension(books, "PROJ", "PROJECT", ("P1",))
    draft = entry(books, rent(books)).json()
    set_context(tenant_id=books["ws"]["id"])
    line = JournalEntry.objects.get(id=draft["id"]).lines.get(line_no=1)
    with pytest.raises(DatabaseError), transaction.atomic():
        LineDimension.objects.create(
            tenant_id=books["ws"]["id"],
            line=line,
            dimension_id=dept["id"],
            value_id=proj["v"]["P1"],
        )


# --- reversal and reports ------------------------------------------------------------------------


def test_reversal_mirrors_tags_even_after_deactivation_and_new_rules(
    books: dict[str, Any], reviewer: Any
) -> None:
    dim = make_dimension(books)
    proj = make_dimension(books, "PROJ", "PROJECT", ("P1",))
    original = entry(books, rent(books, dim["v"]["SALES"])).json()
    for action, client in (("submit", None), ("approve", reviewer), ("post", reviewer)):
        assert act(books, original["id"], action, client).status_code == 200
    commit_point()
    csrf = {"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value}
    books["client"].patch(
        f"{books['base']}/dimension-values/{dim['v']['SALES']}",
        {"status": "INACTIVE"},
        content_type="application/json",
        headers=csrf,
    )
    set_rules(books, "6100", [{"dimension_id": proj["id"], "rule": "REQUIRED"}])
    reversal = books["client"].post_json(
        f"{books['base']}/journal-entries/{original['id']}/reverse", {"reason": "Wrong month"}
    )
    assert reversal.status_code == 201, reversal.content
    body = reversal.json()
    assert body["lines"][0]["credit"] == "100.00"  # mirrored: rent is now credited
    assert body["lines"][0]["dimensions"][0]["value_code"] == "SALES"
    for action, client in (("submit", None), ("approve", reviewer), ("post", reviewer)):
        response = act(books, body["id"], action, client)
        assert response.status_code == 200, response.content


def test_trial_balance_and_ledger_filter_by_dimension_value(
    books: dict[str, Any], reviewer: Any
) -> None:
    dim = make_dimension(books)
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    for value, amount in (("SALES", "100.00"), ("ADMIN", "40.00"), (None, "7.00")):
        ids = [dim["v"][value]] if value else []
        draft = entry(books, rent(books, *ids, amount=amount)).json()
        assert act(books, draft["id"], "post").status_code == 200
    tb_url = f"{books['base']}/reports/trial-balance?as_of=2026-12-31"
    full = books["client"].get(tb_url).json()
    assert full["total_debit"] == full["total_credit"] == "147.00"
    sales = books["client"].get(f"{tb_url}&dimension_value_id={dim['v']['SALES']}").json()
    assert [(r["code"], r["debit"]) for r in sales["rows"]] == [("6100", "100.00")]
    assert sales["total_credit"] == "0.00"  # a partial view need not balance
    gl = (
        books["client"]
        .get(
            f"{books['base']}/reports/general-ledger/{books['accounts']['6100']['id']}"
            f"?date_from=2026-01-01&date_to=2026-12-31&dimension_value_id={dim['v']['ADMIN']}"
        )
        .json()
    )
    assert [ln["debit"] for ln in gl["lines"]] == ["40.00"]
    assert gl["closing_balance"] == "40.00"
    missing = books["client"].get(f"{tb_url}&dimension_value_id={uuid.uuid4()}")
    assert missing.status_code == 404
