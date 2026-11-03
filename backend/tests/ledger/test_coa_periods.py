"""Chart of accounts and fiscal calendar (backlog M1-6, M1-7)."""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.db import IntegrityError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger.accounts import load_template
from fcp.modules.ledger.models import Account
from fcp.modules.ledger.periods import period_for_date

from .conftest import join

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]


# --- chart of accounts ---------------------------------------------------------------------------


def test_cy_template_builds_a_consistent_hierarchy(books: dict[str, Any]) -> None:
    accounts = books["accounts"]
    assert len(accounts) == len(load_template("cy_business")["accounts"]) == 55
    assert accounts["1200"]["name"] == "Trade receivables"
    assert accounts["1200"]["normal_side"] == "DEBIT"
    assert accounts["2100"]["normal_side"] == "CREDIT"
    assert accounts["4000"]["normal_side"] == "CREDIT"
    assert accounts["6000"]["normal_side"] == "DEBIT"
    assert accounts["1"]["is_postable"] is False
    assert accounts["1300"]["parent_id"] == accounts["11"]["id"]
    assert accounts["2120"]["name_el"] == "ΦΠΑ εκροών"
    for account in accounts.values():
        if account["parent_id"]:
            parent = next(a for a in accounts.values() if a["id"] == account["parent_id"])
            assert parent["is_postable"] is False
            assert parent["type"] == account["type"]


def test_template_only_applies_to_an_empty_chart(books: dict[str, Any]) -> None:
    again = books["client"].post_json(f"{books['base']}/accounts/apply-template",
                                      {"template": "personal"})  # fmt: skip
    assert again.status_code == 409


def test_personal_template_for_household(
    make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    user = make_user()
    ws = make_workspace(user, kind="PERSONAL")
    client = api_client(user)
    entity = client.get(f"/api/w/{ws['slug']}/entities").json()[0]
    response = client.post_json(
        f"/api/w/{ws['slug']}/entities/{entity['id']}/accounts/apply-template",
        {"template": "personal"},
    )
    assert response.status_code == 201
    names = {a["code"]: a["name"] for a in response.json()}
    assert names["2200"] == "Mortgage"


@pytest.mark.parametrize(
    ("payload", "status", "field"),
    [
        ({"code": "4000", "name": "Dup", "type": "INCOME"}, 409, None),
        ({"code": "bad code!", "name": "X", "type": "INCOME"}, 422, "code"),
        (
            {"code": "4001", "name": "X", "type": "INCOME", "parent_code": "4000"},
            422,
            "parent_code",
        ),
        ({"code": "4002", "name": "X", "type": "EXPENSE", "parent_code": "4"}, 422, "type"),
        (
            {"code": "4003", "name": "X", "type": "INCOME", "parent_code": "NOPE"},
            422,
            "parent_code",
        ),
        ({"code": "4004", "name": "X", "type": "BANANA"}, 422, "type"),
        ({"code": "4005", "name": "X", "type": "INCOME", "currency": "eur"}, 422, "currency"),
    ],
)
def test_invalid_accounts_are_rejected(
    books: dict[str, Any], payload: dict[str, Any], status: int, field: str | None
) -> None:
    response = books["client"].post_json(f"{books['base']}/accounts", payload)
    assert response.status_code == status
    if field:
        assert field in response.json()["errors"]


def test_create_and_update_account(books: dict[str, Any]) -> None:
    created = books["client"].post_json(
        f"{books['base']}/accounts",
        {"code": "4200", "name": "Consulting revenue", "type": "INCOME", "parent_code": "4"},
    )
    assert created.status_code == 201
    account = created.json()
    assert account["normal_side"] == "CREDIT"
    patched = books["client"].patch(
        f"{books['base']}/accounts/{account['id']}",
        {"name": "Advisory revenue", "status": "INACTIVE", "code": "9000"},
        content_type="application/json",
        headers=books["client"]._csrf(),
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Advisory revenue"
    assert patched.json()["status"] == "INACTIVE"
    assert patched.json()["code"] == "4200", "code is immutable"


def test_parent_must_belong_to_the_same_entity_at_database_level(
    books: dict[str, Any], make_user: Make, api_client: Make, make_workspace: Make
) -> None:
    set_context(tenant_id=books["ws"]["id"])
    second = (
        books["client"]
        .post_json(
            f"/api/w/{books['ws']['slug']}/entities",
            {"legal_name": "Sister Ltd", "entity_type": "COMPANY"},
        )
        .json()
    )
    set_context(tenant_id=books["ws"]["id"])
    heading = Account.objects.get(legal_entity_id=books["entity"]["id"], code="4")
    with pytest.raises(IntegrityError, match="same_entity"), transaction.atomic():
        Account.objects.create(
            tenant_id=books["ws"]["id"], legal_entity_id=second["id"], code="4999", name="X",
            type="INCOME", normal_side="CREDIT", parent=heading, created_by=books["owner"],
        )  # fmt: skip


# --- fiscal years and periods ------------------------------------------------------------------


def test_calendar_year_has_twelve_periods_and_an_adjustment_period(books: dict[str, Any]) -> None:
    fy = books["fy"]
    assert fy["name"] == "2026"
    assert (fy["start_date"], fy["end_date"]) == ("2026-01-01", "2026-12-31")
    regular = [p for p in fy["periods"] if not p["is_adjustment"]]
    adjustment = [p for p in fy["periods"] if p["is_adjustment"]]
    assert len(regular) == 12
    assert regular[1]["end_date"] == "2026-02-28"
    assert [(p["number"], p["start_date"], p["end_date"]) for p in adjustment] == [
        (13, "2026-12-31", "2026-12-31")
    ]
    assert all(p["status"] == "OPEN" for p in fy["periods"])


def test_non_calendar_and_long_first_years(books: dict[str, Any]) -> None:
    july = books["client"].post_json(f"{books['base']}/fiscal-years",
                                     {"start_date": "2027-07-01", "months": 18})  # fmt: skip
    assert july.status_code == 201
    body = july.json()
    assert body["name"] == "2027-07"
    assert body["end_date"] == "2028-12-31"
    assert any(p["end_date"] == "2028-02-29" for p in body["periods"]), "leap year"


@pytest.mark.parametrize(
    ("payload", "status"),
    [
        ({"start_date": "2026-06-01"}, 409),  # overlaps FY2026
        ({"start_date": "2027-01-15"}, 422),  # not the 1st
        ({"start_date": "2027-01-01", "months": 0}, 422),
        ({"start_date": "2027-01-01", "months": 19}, 422),
    ],
)
def test_invalid_fiscal_years(books: dict[str, Any], payload: dict[str, Any], status: int) -> None:
    assert books["client"].post_json(f"{books['base']}/fiscal-years", payload).status_code == status


def _period(books: dict[str, Any], number: int) -> dict[str, Any]:
    return next(p for p in books["fy"]["periods"] if p["number"] == number)


def _set_status(client: Any, books: dict[str, Any], number: int, status: str) -> Any:
    period = _period(books, number)
    return client.post_json(f"{books['base']}/periods/{period['id']}/status", {"status": status})


def test_period_status_transitions(books: dict[str, Any]) -> None:
    client = books["client"]
    assert _set_status(client, books, 1, "SOFT_CLOSED").json()["status"] == "SOFT_CLOSED"
    assert _set_status(client, books, 1, "OPEN").json()["status"] == "OPEN"
    assert _set_status(client, books, 1, "LOCKED").json()["status"] == "LOCKED"
    reopened = _set_status(client, books, 1, "OPEN")
    assert reopened.status_code == 409
    assert "two approvers" in reopened.json()["detail"]
    assert _set_status(client, books, 1, "LOCKED").status_code == 200  # no-op


def test_locking_needs_the_lock_permission(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    accountant = join(books["client"], books["ws"]["slug"], make_user("acc@example.test"),
                      api_client, "accountant")  # fmt: skip
    assert _set_status(accountant, books, 2, "SOFT_CLOSED").status_code == 200
    assert _set_status(accountant, books, 2, "LOCKED").status_code == 403


def test_read_only_member_can_read_but_not_change(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(books["client"], books["ws"]["slug"], make_user("ro@example.test"), api_client,
                  "read_only")  # fmt: skip
    assert viewer.get(f"{books['base']}/accounts").status_code == 200
    assert viewer.get(f"{books['base']}/fiscal-years").status_code == 200
    new_account = {"code": "4300", "name": "X", "type": "INCOME"}
    assert viewer.post_json(f"{books['base']}/accounts", new_account).status_code == 403
    assert _set_status(viewer, books, 3, "SOFT_CLOSED").status_code == 403


def test_entity_scoped_member_cannot_reach_other_entities(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    second = (
        books["client"]
        .post_json(
            f"/api/w/{books['ws']['slug']}/entities",
            {"legal_name": "Other Ltd", "entity_type": "COMPANY"},
        )
        .json()
    )
    scoped = join(books["client"], books["ws"]["slug"], make_user("sc@example.test"), api_client,
                  "accountant", second["id"])  # fmt: skip
    assert scoped.get(f"{books['base']}/accounts").status_code == 404
    other_base = f"/api/w/{books['ws']['slug']}/entities/{second['id']}"
    assert scoped.get(f"{other_base}/accounts").status_code == 200


def test_other_tenants_cannot_see_the_chart(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    outsider = api_client(make_user("outsider@example.test"))
    assert outsider.get(f"{books['base']}/accounts").status_code == 404
    account = books["accounts"]["1200"]
    assert outsider.get(f"{books['base']}/accounts/{account['id']}").status_code == 404


def test_changes_are_audited(books: dict[str, Any]) -> None:
    _set_status(books["client"], books, 4, "SOFT_CLOSED")
    set_context(tenant_id=books["ws"]["id"])
    actions = list(AuditEvent.objects.values_list("action", flat=True))
    assert actions.count("ledger.account.created") == 55
    assert "ledger.fiscal_year.created" in actions
    change = AuditEvent.objects.get(action="ledger.period.status_changed")
    assert change.changes["from"] == "OPEN"
    assert change.changes["to"] == "SOFT_CLOSED"


def test_period_for_date(books: dict[str, Any]) -> None:
    set_context(tenant_id=books["ws"]["id"])
    period = period_for_date(books["entity"]["id"], date(2026, 3, 15))
    assert period is not None
    assert period.number == 3
    adjustment = period_for_date(books["entity"]["id"], date(2026, 12, 31), adjustment=True)
    assert adjustment is not None
    assert adjustment.number == 13
    assert period_for_date(books["entity"]["id"], date(2030, 1, 1)) is None
