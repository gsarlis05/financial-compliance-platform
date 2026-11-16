"""Journal entries: validation, workflow, SoD, DB guards, numbering, idempotency (AC-C1..C5, C7)."""

import threading
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.db import DatabaseError, connection, connections, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.identity.models import User
from fcp.modules.ledger import accounts, entries, periods
from fcp.modules.ledger.models import AccountBalance, JournalEntry, JournalLine
from fcp.modules.tenancy import services as tenancy

from .conftest import join

Make = Callable[..., Any]


def lines(*pairs: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"account_id": acc, "debit": d, "credit": c} for acc, d, c in pairs]


def payload(
    books: dict[str, Any], *line_list: tuple[str, str, str], day: str = "2026-03-15", **extra: Any
) -> dict[str, Any]:
    acc = books["accounts"]
    resolved = [(acc[code]["id"] if code in acc else code, d, c) for code, d, c in line_list]
    return {"accounting_date": day, "description": "Test entry", "lines": lines(*resolved), **extra}


SALE = (("1300", "1190.00", "0"), ("4000", "0", "1000.00"), ("2120", "0", "190.00"))


@pytest.fixture
def reviewer(books: dict[str, Any], make_user: Make, api_client: Make) -> Any:
    return join(
        books["client"],
        books["ws"]["slug"],
        make_user("reviewer@example.test"),
        api_client,
        "reviewer",
    )


def create(
    books: dict[str, Any], *line_list: tuple[str, str, str], client: Any = None, **kw: Any
) -> Any:
    return (client or books["client"]).post_json(
        f"{books['base']}/journal-entries", payload(books, *line_list, **kw)
    )


def act(
    books: dict[str, Any], entry_id: str, action: str, client: Any = None, body: Any = None
) -> Any:
    return (client or books["client"]).post_json(
        f"{books['base']}/journal-entries/{entry_id}/{action}", body or {}
    )


def post_through_workflow(
    books: dict[str, Any], reviewer: Any, *line_list: tuple[str, str, str], **kw: Any
) -> dict[str, Any]:
    entry = create(books, *line_list, **kw).json()
    assert act(books, entry["id"], "submit").status_code == 200
    assert act(books, entry["id"], "approve", reviewer).status_code == 200
    posted = act(books, entry["id"], "post", reviewer)
    assert posted.status_code == 200, posted.content
    body: dict[str, Any] = posted.json()
    return body


# --- happy path ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_full_workflow_posts_numbers_and_updates_balances(
    books: dict[str, Any], reviewer: Any
) -> None:
    posted = post_through_workflow(books, reviewer, *SALE)
    assert posted["status"] == "POSTED"
    assert posted["entry_no"] == 1
    assert posted["posting_seq"] == 1
    assert posted["total_debit"] == posted["total_credit"] == "1190.00"
    assert [ln["account_code"] for ln in posted["lines"]] == ["1300", "4000", "2120"]
    set_context(tenant_id=books["ws"]["id"])
    balances = {
        b.account.code: (b.debit_total, b.credit_total)
        for b in AccountBalance.objects.select_related("account")
    }
    assert balances["1300"][0] == 1190
    assert balances["4000"][1] == 1000
    second = post_through_workflow(books, reviewer, *SALE)
    assert (second["entry_no"], second["posting_seq"]) == (2, 2)
    set_context(tenant_id=books["ws"]["id"])
    assert AccountBalance.objects.get(account__code="1300").debit_total == 2380


@pytest.mark.django_db
def test_amounts_are_returned_as_strings(books: dict[str, Any]) -> None:
    body = create(books, *SALE).json()
    assert body["lines"][0]["debit"] == "1190.00"
    assert isinstance(body["total_debit"], str)


# --- AC-C1: validation with distinct codes --------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("line_list", "code"),
    [
        ((("1300", "100.00", "0"), ("4000", "0", "99.99")), "ledger.entry.unbalanced"),
        ((("1300", "100.00", "0"),), "ledger.entry.too_few_lines"),
    ],
)
def test_incomplete_entries_cannot_be_submitted(
    books: dict[str, Any], line_list: tuple[tuple[str, str, str], ...], code: str
) -> None:
    entry = create(books, *line_list).json()  # drafts may be incomplete while editing
    response = act(books, entry["id"], "submit")
    assert response.status_code == 422
    assert response.json()["code"] == code
    if code == "ledger.entry.unbalanced":
        assert "0.01" in response.json()["detail"]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("line_list", "status", "code"),
    [
        ((("1300", "0", "0"), ("4000", "0", "10.00")), 422, "ledger.line.invalid"),
        ((("1300", "10.00", "10.00"), ("4000", "0", "10.00")), 422, "ledger.line.invalid"),
        ((("1300", "10.005", "0"), ("4000", "0", "10.005")), 422, "ledger.line.invalid"),
        ((("1300", "-10.00", "0"), ("4000", "0", "10.00")), 422, "validation_failed"),
        ((("1300", "1e3", "0"), ("4000", "0", "10.00")), 422, "validation_failed"),
        ((("13", "10.00", "0"), ("4000", "0", "10.00")), 422, "ledger.account.not_postable"),
    ],
)
def test_invalid_lines_are_rejected(
    books: dict[str, Any], line_list: tuple[tuple[str, str, str], ...], status: int, code: str
) -> None:
    acc = books["accounts"]
    if "13" not in acc:
        acc["13"] = acc["11"]  # a heading (non-postable) account
    response = create(books, *line_list)
    assert response.status_code == status, response.content
    assert response.json()["code"] == code


@pytest.mark.django_db
def test_json_numbers_are_rejected_for_amounts(books: dict[str, Any]) -> None:
    body = payload(books, *SALE)
    body["lines"][0]["debit"] = 1190.0
    response = books["client"].post_json(f"{books['base']}/journal-entries", body)
    assert response.status_code == 422


@pytest.mark.django_db
def test_inactive_and_foreign_accounts_are_rejected(books: dict[str, Any]) -> None:
    acc = books["accounts"]
    books["client"].patch(
        f"{books['base']}/accounts/{acc['6900']['id']}",
        {"status": "INACTIVE"},
        content_type="application/json",
        headers=books["client"]._csrf(),
    )
    inactive = create(books, ("6900", "10.00", "0"), ("1300", "0", "10.00"))
    assert inactive.json()["code"] == "ledger.account.not_postable"
    foreign = create(books, (str(uuid.uuid4()), "10.00", "0"), ("1300", "0", "10.00"))
    assert foreign.status_code == 422
    assert "lines.0.account_id" in foreign.json()["errors"]


@pytest.mark.django_db
def test_date_without_a_period_is_rejected(books: dict[str, Any]) -> None:
    entry = create(books, *SALE, day="2031-01-10").json()
    response = act(books, entry["id"], "submit")
    assert response.json()["code"] == "ledger.period.not_found"


# --- AC-C3: segregation of duties and approval binding ------------------------------------------


@pytest.mark.django_db
def test_preparer_cannot_approve_own_entry(books: dict[str, Any]) -> None:
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    response = act(books, entry["id"], "approve")
    assert response.status_code == 403
    assert response.json()["code"] == "ledger.entry.sod_violation"


@pytest.mark.django_db
def test_approval_is_required_by_default_for_businesses(books: dict[str, Any]) -> None:
    entry = create(books, *SALE).json()
    response = act(books, entry["id"], "post")
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.approval_required"


@pytest.mark.django_db
def test_change_after_approval_invalidates_it(books: dict[str, Any], reviewer: Any) -> None:
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", reviewer)
    edit = books["client"].put_json(
        f"{books['base']}/journal-entries/{entry['id']}", payload(books, *SALE)
    )
    assert edit.status_code == 409  # approved entries cannot be edited through the API
    set_context(tenant_id=books["ws"]["id"])
    JournalLine.objects.filter(entry_id=entry["id"], line_no=3).update(
        memo="changed behind the scenes"
    )
    response = act(books, entry["id"], "post", reviewer)
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.approval_stale"


@pytest.mark.django_db
def test_reject_edit_and_resubmit(books: dict[str, Any], reviewer: Any) -> None:
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    rejected = act(books, entry["id"], "reject", reviewer, {"reason": "Wrong VAT account"})
    assert rejected.json()["status"] == "REJECTED"
    assert rejected.json()["rejection_reason"] == "Wrong VAT account"
    edited = books["client"].put_json(
        f"{books['base']}/journal-entries/{entry['id']}", payload(books, *SALE)
    )
    assert edited.json()["status"] == "DRAFT"
    assert act(books, entry["id"], "submit").json()["status"] == "SUBMITTED"


@pytest.mark.django_db
def test_threshold_policy(books: dict[str, Any]) -> None:
    put = books["client"].put_json(
        f"{books['base']}/ledger-settings",
        {"approval_policy": "THRESHOLD", "approval_threshold": "500.00"},
    )
    assert put.status_code == 200
    small = create(books, ("6100", "400.00", "0"), ("1300", "0", "400.00")).json()
    assert act(books, small["id"], "post").json()["status"] == "POSTED"
    large = create(books, *SALE).json()
    assert act(books, large["id"], "post").json()["code"] == "ledger.entry.approval_required"


@pytest.mark.django_db
def test_void_draft(books: dict[str, Any]) -> None:
    entry = create(books, *SALE).json()
    assert act(books, entry["id"], "void").json()["status"] == "VOID"
    assert act(books, entry["id"], "submit").status_code == 409


# --- AC-C2: database guards hold when the application is bypassed --------------------------------


def _sql(statement: str, params: list[Any] | None = None) -> None:
    with connection.cursor() as cursor:
        cursor.execute(statement, params or [])


@pytest.mark.django_db
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE ledger_journal_entry SET description = 'forged' WHERE id = %s",
        "DELETE FROM ledger_journal_entry WHERE id = %s",
        "UPDATE ledger_journal_line SET debit = debit + 1 WHERE entry_id = %s",
        "DELETE FROM ledger_journal_line WHERE entry_id = %s",
        "INSERT INTO ledger_journal_line "
        "(id, tenant_id, created_at, entry_id, line_no, account_id, debit, credit, memo) "
        "SELECT gen_random_uuid(), tenant_id, now(), entry_id, 99, account_id, 1, 0, '' "
        "FROM ledger_journal_line WHERE entry_id = %s LIMIT 1",
    ],
)
def test_posted_entries_are_immutable_in_the_database(
    books: dict[str, Any], reviewer: Any, statement: str
) -> None:
    posted = post_through_workflow(books, reviewer, *SALE)
    with transaction.atomic():
        _sql("SET LOCAL ROLE fcp_app")
        set_context(tenant_id=books["ws"]["id"])
        with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
            _sql(statement, [posted["id"]])


@pytest.mark.django_db
def test_database_rejects_an_unbalanced_post(books: dict[str, Any]) -> None:
    entry = create(books, ("1300", "100.00", "0"), ("4000", "0", "90.00")).json()
    set_context(tenant_id=books["ws"]["id"])
    period = periods.period_for_date(books["entity"]["id"], date(2026, 3, 15))
    assert period is not None
    with pytest.raises(DatabaseError, match="unbalanced"), transaction.atomic():  # noqa: PT012
        _sql(
            "UPDATE ledger_journal_entry SET status = 'POSTED', period_id = %s, "
            "fiscal_year_id = %s, entry_no = 999, posting_seq = 999 WHERE id = %s",
            [period.id, period.fiscal_year_id, entry["id"]],
        )
        _sql("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.django_db
def test_database_rejects_posting_into_a_locked_period(books: dict[str, Any]) -> None:
    entry = create(books, *SALE).json()
    set_context(tenant_id=books["ws"]["id"])
    period = periods.period_for_date(books["entity"]["id"], date(2026, 3, 15))
    assert period is not None
    _sql("UPDATE ledger_period SET status = 'LOCKED' WHERE id = %s", [period.id])
    with pytest.raises(DatabaseError, match="locked period"), transaction.atomic():
        _sql(
            "UPDATE ledger_journal_entry SET status = 'POSTED', period_id = %s, "
            "fiscal_year_id = %s, entry_no = 999, posting_seq = 999 WHERE id = %s",
            [period.id, period.fiscal_year_id, entry["id"]],
        )


# --- AC-C7 (posting rules): locked and soft-closed periods ----------------------------------------


def _period_id(books: dict[str, Any], number: int) -> str:
    return str(next(p["id"] for p in books["fy"]["periods"] if p["number"] == number))


@pytest.mark.django_db
def test_locked_period_rejects_posting(books: dict[str, Any], reviewer: Any) -> None:
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", reviewer)
    books["client"].post_json(
        f"{books['base']}/periods/{_period_id(books, 3)}/status", {"status": "LOCKED"}
    )
    response = act(books, entry["id"], "post", reviewer)
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.period.locked"


@pytest.mark.django_db
def test_soft_closed_period_needs_the_privilege(books: dict[str, Any], reviewer: Any) -> None:
    books["client"].post_json(
        f"{books['base']}/periods/{_period_id(books, 3)}/status", {"status": "SOFT_CLOSED"}
    )
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", reviewer)
    denied = act(books, entry["id"], "post", reviewer)  # reviewer lacks post_soft_closed
    assert denied.status_code == 403
    assert denied.json()["code"] == "ledger.period.soft_closed"
    allowed = act(books, entry["id"], "post")  # the owner holds the privilege
    assert allowed.json()["status"] == "POSTED"
    set_context(tenant_id=books["ws"]["id"])
    event = AuditEvent.objects.get(action="ledger.entry.posted")
    assert event.changes["soft_closed"] is True


@pytest.mark.django_db
def test_adjustment_period_posting(books: dict[str, Any], reviewer: Any) -> None:
    posted = post_through_workflow(
        books, reviewer, *SALE, day="2026-12-31", use_adjustment_period=True
    )
    adjustment = next(p for p in books["fy"]["periods"] if p["is_adjustment"])
    assert posted["period_id"] == adjustment["id"]


# --- AC-C5: idempotency ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_idempotent_create_and_post(books: dict[str, Any]) -> None:
    client = books["client"]
    client.put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    headers = {
        "X-CSRFToken": client.cookies["__Host-fcp_csrftoken"].value,
        "Idempotency-Key": "create-0001",
    }
    body = payload(books, *SALE)
    first = client.post(
        f"{books['base']}/journal-entries", body, content_type="application/json", headers=headers
    )
    again = client.post(
        f"{books['base']}/journal-entries", body, content_type="application/json", headers=headers
    )
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    set_context(tenant_id=books["ws"]["id"])
    assert JournalEntry.objects.count() == 1
    other = dict(body, description="Different")
    conflict = client.post(
        f"{books['base']}/journal-entries", other, content_type="application/json", headers=headers
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "ledger.idempotency.conflict"
    post_headers = dict(headers, **{"Idempotency-Key": "post-0001"})
    url = f"{books['base']}/journal-entries/{first.json()['id']}/post"
    p1 = client.post(url, {}, content_type="application/json", headers=post_headers)
    p2 = client.post(url, {}, content_type="application/json", headers=post_headers)
    assert p1.status_code == p2.status_code == 200
    assert p1.json()["entry_no"] == p2.json()["entry_no"] == 1
    without_key = act(books, first.json()["id"], "post")
    assert without_key.status_code == 409  # a second real post is refused


# --- isolation and permissions -------------------------------------------------------------------


@pytest.mark.django_db
def test_other_tenants_cannot_see_entries(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    entry = create(books, *SALE).json()
    outsider = api_client(make_user("x@example.test"))
    assert outsider.get(f"{books['base']}/journal-entries/{entry['id']}").status_code == 404
    assert outsider.get(f"{books['base']}/journal-entries").status_code == 404


@pytest.mark.django_db
def test_reviewer_cannot_create_and_accountant_cannot_post(
    books: dict[str, Any], reviewer: Any, make_user: Make, api_client: Make
) -> None:
    assert create(books, *SALE, client=reviewer).status_code == 403
    accountant = join(
        books["client"],
        books["ws"]["slug"],
        make_user("acc2@example.test"),
        api_client,
        "accountant",
    )
    entry = create(books, *SALE, client=accountant).json()
    act(books, entry["id"], "submit", accountant)
    act(books, entry["id"], "approve", reviewer)
    assert act(books, entry["id"], "post", accountant).status_code == 403


# --- AC-C4: gapless numbering under concurrency -------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_fifty_concurrent_posts_are_gapless(make_user: Make) -> None:
    owner: User = make_user("concurrent@example.test")
    with transaction.atomic():
        ctx = tenancy.create_workspace(owner, name="Concurrent", kind="PERSONAL")
        entity_id = tenancy.list_entities(ctx)[0].id
        chart = {a.code: a for a in accounts.apply_template(ctx, entity_id, "personal")}
        periods.create_fiscal_year(ctx, entity_id, start_date=date(2026, 1, 1))
        draft_ids = [
            entries.create_draft(
                ctx,
                entity_id,
                entries.EntryInput(
                    accounting_date=date(2026, 5, 1 + n % 28),
                    description=f"Spend {n}",
                    lines=[
                        entries.LineInput(chart["6100"].id, debit="10.00"),
                        entries.LineInput(chart["1100"].id, credit="10.00"),
                    ],
                ),
            ).id
            for n in range(50)
        ]
    tenant_id, slug = ctx.tenant.id, ctx.tenant.slug
    errors: list[BaseException] = []

    def post_one(entry_id: uuid.UUID) -> None:
        try:
            with transaction.atomic():
                worker_ctx = tenancy.enter_workspace(owner, slug)
                entries.post(worker_ctx, entity_id, entry_id)
        except BaseException as exc:  # noqa: BLE001 - collected and asserted below
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=post_one, args=(i,)) for i in draft_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    with transaction.atomic():
        set_context(tenant_id=tenant_id)
        posted = JournalEntry.objects.filter(status="POSTED")
        assert sorted(int(n or 0) for n in posted.values_list("entry_no", flat=True)) == list(
            range(1, 51)
        )
        assert sorted(int(n or 0) for n in posted.values_list("posting_seq", flat=True)) == list(
            range(1, 51)
        )
        assert AccountBalance.objects.get(account__code="6100").debit_total == 500
