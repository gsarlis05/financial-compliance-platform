"""Reversals, adjustments and the period unlock workflow (doc 09 AC-C6, AC-C7)."""

import time
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fcp.core.db.rls import set_context
from fcp.modules.identity import oidc
from fcp.modules.ledger import corrections
from fcp.modules.ledger.models import AccountBalance, PeriodUnlock

from .conftest import join
from .test_entries import SALE, act, create, payload, post_through_workflow

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]


@pytest.fixture
def team(books: dict[str, Any], make_user: Make, api_client: Make) -> dict[str, Any]:
    slug = books["ws"]["slug"]
    return {
        "reviewer": join(
            books["client"], slug, make_user("rev@example.test"), api_client, "reviewer"
        ),
        "accountant": join(
            books["client"], slug, make_user("acc@example.test"), api_client, "accountant"
        ),
        "manager": join(
            books["client"], slug, make_user("fm@example.test"), api_client, "finance_manager"
        ),
    }


def balances(books: dict[str, Any]) -> dict[str, Decimal]:
    set_context(tenant_id=books["ws"]["id"])
    totals: dict[str, Decimal] = {}
    for b in AccountBalance.objects.select_related("account"):
        totals[b.account.code] = (
            totals.get(b.account.code, Decimal(0)) + b.debit_total - b.credit_total
        )
    return totals


def reverse(books: dict[str, Any], entry_id: str, client: Any = None, **body: Any) -> Any:
    return (client or books["client"]).post_json(
        f"{books['base']}/journal-entries/{entry_id}/reverse",
        {"reason": "Posted to wrong account", **body},
    )


def post_reversal(books: dict[str, Any], team: dict[str, Any], entry_id: str) -> dict[str, Any]:
    draft = reverse(books, entry_id).json()
    act(books, draft["id"], "submit")
    act(books, draft["id"], "approve", team["reviewer"])
    posted = act(books, draft["id"], "post", team["reviewer"])
    assert posted.status_code == 200, posted.content
    body: dict[str, Any] = posted.json()
    return body


# --- AC-C6: reversal ------------------------------------------------------------------------------


def test_reversal_mirrors_links_and_nets_to_zero(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    reversal = post_reversal(books, team, original["id"])
    assert reversal["entry_type"] == "REVERSAL"
    assert reversal["reverses_entry_id"] == original["id"]
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in reversal["lines"]] == [
        ("1300", "0.00", "1190.00"),
        ("4000", "1000.00", "0.00"),
        ("2120", "190.00", "0.00"),
    ]
    refreshed = books["client"].get(f"{books['base']}/journal-entries/{original['id']}").json()
    assert refreshed["reversed_by_entry_id"] == reversal["id"]
    assert refreshed["status"] == "POSTED"
    assert all(v == 0 for v in balances(books).values())


def test_an_entry_can_be_reversed_only_once(books: dict[str, Any], team: dict[str, Any]) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    assert reverse(books, original["id"]).status_code == 201
    pending = reverse(books, original["id"])  # a reversal draft already exists
    assert pending.status_code == 409
    assert pending.json()["code"] == "ledger.entry.already_reversed"


def test_reversal_after_voiding_the_first_draft_is_allowed(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    first = reverse(books, original["id"]).json()
    act(books, first["id"], "void")
    assert reverse(books, original["id"]).status_code == 201


def test_posted_reversal_blocks_further_reversals(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    reversal = post_reversal(books, team, original["id"])
    assert reverse(books, original["id"]).json()["code"] == "ledger.entry.already_reversed"
    assert reverse(books, reversal["id"]).status_code == 409  # a reversal is not reversed


@pytest.mark.parametrize("reason", ["", "abc"])
def test_reversal_needs_a_reason(books: dict[str, Any], team: dict[str, Any], reason: str) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    response = reverse(books, original["id"], reason=reason)
    assert response.status_code == 422


def test_only_posted_entries_can_be_reversed(books: dict[str, Any]) -> None:
    draft = create(books, *SALE).json()
    assert reverse(books, draft["id"]).status_code == 409


def test_reversal_dated_in_first_open_period_when_original_period_closed(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)  # March
    march = next(p for p in books["fy"]["periods"] if p["number"] == 3)
    books["client"].post_json(f"{books['base']}/periods/{march['id']}/status", {"status": "LOCKED"})
    draft = reverse(books, original["id"]).json()
    assert draft["accounting_date"] == "2026-04-01"


def test_tampered_reversal_lines_are_refused_at_posting(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    draft = reverse(books, original["id"]).json()
    altered = payload(books, ("1300", "0", "1000.00"), ("4000", "1000.00", "0"))
    books["client"].put_json(f"{books['base']}/journal-entries/{draft['id']}", altered)
    act(books, draft["id"], "submit")
    act(books, draft["id"], "approve", team["reviewer"])
    response = act(books, draft["id"], "post", team["reviewer"])
    assert response.status_code == 409
    assert "mirror" in response.json()["detail"]


@settings(
    max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(amounts=st.lists(st.integers(min_value=1, max_value=10_000_000), min_size=1, max_size=5))
def test_reversed_pairs_always_net_every_account_to_zero(
    books: dict[str, Any], team: dict[str, Any], amounts: list[int]
) -> None:
    """Property: for any balanced entry, posting it and its reversal leaves every balance zero."""
    expense_codes = ["6000", "6100", "6110", "6200", "6300"]
    debit_lines = [
        (expense_codes[i], f"{Decimal(a) / 100:.2f}", "0") for i, a in enumerate(amounts)
    ]
    total = f"{Decimal(sum(amounts)) / 100:.2f}"
    with transaction.atomic():
        before = balances(books)
        original = post_through_workflow(
            books, team["reviewer"], *debit_lines, ("1300", "0", total)
        )
        post_reversal(books, team, original["id"])
        after = balances(books)
        assert {k: v for k, v in after.items() if v} == {k: v for k, v in before.items() if v}
        transaction.set_rollback(True)


# --- adjustments --------------------------------------------------------------------------------


def test_adjustment_references_original_and_needs_reason(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    body = payload(
        books,
        ("6900", "10.00", "0"),
        ("1300", "0", "10.00"),
        day="2026-12-31",
        use_adjustment_period=True,
        reason="Audit adjustment: bank fee",
    )
    created = books["client"].post_json(
        f"{books['base']}/journal-entries/{original['id']}/adjust", body
    )
    assert created.status_code == 201
    assert created.json()["entry_type"] == "ADJUSTMENT"
    assert created.json()["related_entry_id"] == original["id"]
    assert created.json()["correction_reason"] == "Audit adjustment: bank fee"
    body["reason"] = "x"
    assert (
        books["client"]
        .post_json(f"{books['base']}/journal-entries/{original['id']}/adjust", body)
        .status_code
        == 422
    )


# --- AC-C7: period unlock -------------------------------------------------------------------------


def _lock_march(books: dict[str, Any]) -> str:
    march = next(p for p in books["fy"]["periods"] if p["number"] == 3)
    books["client"].post_json(f"{books['base']}/periods/{march['id']}/status", {"status": "LOCKED"})
    return str(march["id"])


def _request(books: dict[str, Any], client: Any, period_id: str, minutes: int = 30) -> Any:
    return client.post_json(
        f"{books['base']}/periods/{period_id}/unlock-requests",
        {"reason": "Late supplier invoice for March", "window_minutes": minutes},
    )


def _decide(books: dict[str, Any], client: Any, unlock_id: str, decision: str = "approve") -> Any:
    return client.post_json(f"{books['base']}/unlock-requests/{unlock_id}/{decision}", {})


def test_unlock_needs_two_distinct_approvers_and_tags_postings(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    period_id = _lock_march(books)
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", team["reviewer"])
    assert (
        act(books, entry["id"], "post", team["reviewer"]).json()["code"] == "ledger.period.locked"
    )

    requested = _request(books, team["accountant"], period_id)
    assert requested.status_code == 201
    unlock_id = requested.json()["id"]
    assert (
        _decide(books, team["accountant"], unlock_id).status_code == 403
    )  # requester has no right
    first = _decide(books, books["client"], unlock_id)
    assert first.json()["status"] == "REQUESTED"
    same = _decide(books, books["client"], unlock_id)
    assert same.json()["code"] == "ledger.entry.sod_violation"
    second = _decide(books, team["manager"], unlock_id)
    assert second.json()["status"] == "ACTIVE"
    assert second.json()["active_until"] is not None

    posted = act(books, entry["id"], "post", team["reviewer"])
    assert posted.json()["status"] == "POSTED"
    assert posted.json()["unlock_request_id"] == unlock_id
    period = next(
        p
        for fy in books["client"].get(f"{books['base']}/fiscal-years").json()
        for p in fy["periods"]
        if p["id"] == period_id
    )
    assert period["status"] == "LOCKED", "the period stays locked; only the window is open"


def test_requester_cannot_approve_own_unlock(books: dict[str, Any], team: dict[str, Any]) -> None:
    period_id = _lock_march(books)
    unlock_id = _request(books, team["manager"], period_id).json()["id"]
    response = _decide(books, team["manager"], unlock_id)
    assert response.status_code == 403
    assert response.json()["code"] == "ledger.entry.sod_violation"


def test_unlock_approval_requires_recent_sign_in(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    period_id = _lock_march(books)
    unlock_id = _request(books, team["accountant"], period_id).json()["id"]
    session = books["client"].session
    session[oidc.SESSION_AUTH_TIME] = int(time.time()) - 600
    session.save()
    assert _decide(books, books["client"], unlock_id).json()["code"] == "auth.step_up_required"


def test_expired_unlock_relocks_automatically(books: dict[str, Any], team: dict[str, Any]) -> None:
    period_id = _lock_march(books)
    unlock_id = _request(books, team["accountant"], period_id).json()["id"]
    _decide(books, books["client"], unlock_id)
    _decide(books, team["manager"], unlock_id)
    set_context(tenant_id=books["ws"]["id"])
    PeriodUnlock.objects.filter(id=unlock_id).update(
        active_until=timezone.now() - timedelta(seconds=1)
    )
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", team["reviewer"])
    assert (
        act(books, entry["id"], "post", team["reviewer"]).json()["code"] == "ledger.period.locked"
    )
    listed = books["client"].get(f"{books['base']}/unlock-requests").json()
    assert listed[0]["status"] == "CLOSED"


def test_unlock_can_be_closed_early_and_rejected(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    period_id = _lock_march(books)
    unlock_id = _request(books, team["accountant"], period_id).json()["id"]
    assert _decide(books, books["client"], unlock_id, "reject").json()["status"] == "REJECTED"
    again = _request(books, team["accountant"], period_id).json()["id"]
    _decide(books, books["client"], again)
    _decide(books, team["manager"], again)
    closed = team["accountant"].post_json(f"{books['base']}/unlock-requests/{again}/close", {})
    assert closed.json()["status"] == "CLOSED"


def test_only_one_open_unlock_per_period(books: dict[str, Any], team: dict[str, Any]) -> None:
    period_id = _lock_march(books)
    assert _request(books, team["accountant"], period_id).status_code == 201
    assert _request(books, team["accountant"], period_id).status_code == 409


def test_unlock_is_only_for_locked_periods(books: dict[str, Any], team: dict[str, Any]) -> None:
    open_period = next(p for p in books["fy"]["periods"] if p["number"] == 5)
    assert _request(books, team["accountant"], open_period["id"]).status_code == 409


def test_database_rejects_posting_with_an_inactive_unlock(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    period_id = _lock_march(books)
    unlock_id = _request(books, team["accountant"], period_id).json()["id"]  # requested, not active
    entry = create(books, *SALE).json()
    set_context(tenant_id=books["ws"]["id"])
    with (
        pytest.raises(DatabaseError, match="active unlock"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE ledger_journal_entry SET status = 'POSTED', period_id = %s, "
            "fiscal_year_id = (SELECT fiscal_year_id FROM ledger_period WHERE id = %s), "
            "entry_no = 999, posting_seq = 999, unlock_request_id = %s WHERE id = %s",
            [period_id, period_id, unlock_id, entry["id"]],
        )


def test_database_rejection_at_posting_is_reported_not_500(
    books: dict[str, Any], team: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the unlock closes between the application's check and the write, the user gets an
    actionable 409 and nothing is posted."""
    period_id = _lock_march(books)
    unlock_id = _request(books, team["accountant"], period_id).json()["id"]
    _decide(books, books["client"], unlock_id)
    _decide(books, team["manager"], unlock_id)
    entry = create(books, *SALE).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", team["reviewer"])

    original = corrections.active_unlock

    def stale_check(period: Any) -> Any:
        unlock = original(period)
        PeriodUnlock.objects.filter(id=unlock_id).update(status="CLOSED")  # closes "concurrently"
        return unlock

    monkeypatch.setattr(corrections, "active_unlock", stale_check)
    response = act(books, entry["id"], "post", team["reviewer"])
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.rejected_by_database"
    assert "locked period" in response.json()["detail"]
    status = books["client"].get(f"{books['base']}/journal-entries/{entry['id']}").json()["status"]
    assert status == "APPROVED"
