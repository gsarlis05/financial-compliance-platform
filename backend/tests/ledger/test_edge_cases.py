"""Edge cases of the posting and correction workflows (AC-G1: every branch of posting code).

Each test names the rule it proves. Paths that the API's own validation already blocks are driven
through the service layer directly, so the service-level guard is proven too (defence in depth).
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.db import IntegrityError, transaction

from fcp.core.db.rls import set_context
from fcp.core.errors import ValidationFailedError
from fcp.modules.ledger import corrections, entries
from fcp.modules.ledger.errors import InvalidLineError
from fcp.modules.ledger.models import JournalEntry
from fcp.modules.tenancy import services as tenancy

from .test_corrections import _decide, _lock_march, _request, reverse, team
from .test_entries import SALE, act, create, payload, post_through_workflow, reviewer

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["reviewer", "team"]  # fixtures re-used from sibling modules


def _tamper_description(books: dict[str, Any], entry_id: str) -> None:
    """Change an entry behind the API's back (as a bug or an attacker with DB access would)."""
    with transaction.atomic():
        set_context(tenant_id=books["ws"]["id"])
        JournalEntry.objects.filter(id=entry_id).update(description="Changed afterwards")


def _ctx(books: dict[str, Any]) -> tenancy.WorkspaceContext:
    return tenancy.enter_workspace(books["owner"], books["ws"]["slug"])


# --- settings and validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("threshold", "error"),
    [(None, "required"), ("10.005", "invalid")],
)
def test_threshold_policy_needs_a_valid_threshold(
    books: dict[str, Any], threshold: str | None, error: str
) -> None:
    body = {"approval_policy": "THRESHOLD", "approval_threshold": threshold}
    response = books["client"].put_json(f"{books['base']}/ledger-settings", body)
    assert response.status_code == 422
    assert response.json()["errors"]["approval_threshold"] == [error]


def test_unknown_journal_is_rejected(books: dict[str, Any]) -> None:
    response = create(books, *SALE, journal="XX")
    assert response.status_code == 422
    assert response.json()["errors"]["journal"] == ["not found"]


@pytest.mark.parametrize("value", ["abc", "1.005", "-1.00"])
def test_service_rejects_malformed_amounts(value: str) -> None:
    with pytest.raises(InvalidLineError):
        entries._amount(value, "EUR", "lines.0.debit")  # the guard itself


def test_account_deactivated_after_drafting_blocks_submission(books: dict[str, Any]) -> None:
    draft = create(books, ("6100", "50.00", "0"), ("1300", "0", "50.00")).json()
    rent = books["accounts"]["6100"]["id"]
    patched = books["client"].patch(
        f"{books['base']}/accounts/{rent}",
        {"status": "INACTIVE"},
        content_type="application/json",
        headers={"X-CSRFToken": books["client"].cookies["__Host-fcp_csrftoken"].value},
    )
    assert patched.status_code == 200, patched.content
    submitted = act(books, draft["id"], "submit")
    assert submitted.status_code == 422
    assert submitted.json()["code"] == "ledger.account.not_postable"


# --- reading -------------------------------------------------------------------------------------


def test_unknown_entry_is_404(books: dict[str, Any]) -> None:
    response = books["client"].get(f"{books['base']}/journal-entries/{uuid.uuid4()}")
    assert response.status_code == 404


def test_entry_list_filters(books: dict[str, Any], reviewer: Any) -> None:
    posted = post_through_workflow(books, reviewer, *SALE, day="2026-02-10")
    draft = create(books, *SALE, day="2026-04-10").json()
    url = f"{books['base']}/journal-entries"

    def ids(query: str) -> set[str]:
        return {e["id"] for e in books["client"].get(f"{url}?{query}").json()}

    assert ids("status=POSTED") == {posted["id"]}
    assert ids("date_from=2026-03-01") == {draft["id"]}
    assert ids("date_to=2026-03-01") == {posted["id"]}


# --- workflow state rules ------------------------------------------------------------------------


def test_only_submitted_entries_can_be_approved(books: dict[str, Any], reviewer: Any) -> None:
    draft = create(books, *SALE).json()
    assert act(books, draft["id"], "approve", reviewer).status_code == 409


def test_change_after_submission_invalidates_the_submission(
    books: dict[str, Any], reviewer: Any
) -> None:
    draft = create(books, *SALE).json()
    act(books, draft["id"], "submit")
    _tamper_description(books, draft["id"])
    response = act(books, draft["id"], "approve", reviewer)
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.approval_stale"


def test_change_after_approval_blocks_posting(books: dict[str, Any], reviewer: Any) -> None:
    draft = create(books, *SALE).json()
    act(books, draft["id"], "submit")
    act(books, draft["id"], "approve", reviewer)
    _tamper_description(books, draft["id"])
    response = act(books, draft["id"], "post", reviewer)
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.approval_stale"


def test_drafts_cannot_be_rejected(books: dict[str, Any], reviewer: Any) -> None:
    draft = create(books, *SALE).json()
    rejected = act(books, draft["id"], "reject", reviewer, {"reason": "Not ready"})
    assert rejected.status_code == 409


def test_posted_entries_cannot_be_voided(books: dict[str, Any], reviewer: Any) -> None:
    posted = post_through_workflow(books, reviewer, *SALE)
    assert act(books, posted["id"], "void").status_code == 409


def test_rejected_entries_cannot_be_posted_directly(books: dict[str, Any], reviewer: Any) -> None:
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    draft = create(books, *SALE).json()
    act(books, draft["id"], "submit")
    act(books, draft["id"], "reject", reviewer, {"reason": "Wrong VAT"})
    response = act(books, draft["id"], "post")
    assert response.status_code == 409
    assert "corrected and submitted again" in response.json()["detail"]


# --- reversals and adjustments -------------------------------------------------------------------


def test_reversal_on_a_requested_date(books: dict[str, Any], team: dict[str, Any]) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    draft = reverse(books, original["id"], reversal_date="2026-05-02").json()
    assert draft["accounting_date"] == "2026-05-02"


def test_reversal_needs_a_date_when_no_later_period_is_open(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    for period in books["fy"]["periods"]:
        if period["number"] >= 3:
            books["client"].post_json(
                f"{books['base']}/periods/{period['id']}/status", {"status": "LOCKED"}
            )
    response = reverse(books, original["id"])
    assert response.status_code == 422
    assert response.json()["errors"]["reversal_date"] == ["required"]


def test_concurrent_duplicate_reversal_is_reported(
    books: dict[str, Any], team: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)

    def unique_violation(*args: Any, **kwargs: Any) -> Any:
        raise IntegrityError("duplicate key value violates unique constraint")

    monkeypatch.setattr(entries, "create_draft", unique_violation)
    response = reverse(books, original["id"])
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.already_reversed"


def test_reversal_cannot_post_if_the_original_was_reversed_meanwhile(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    first = reverse(books, original["id"]).json()
    other = post_through_workflow(books, team["reviewer"], *SALE)
    with transaction.atomic():  # simulate a link left by another path
        set_context(tenant_id=books["ws"]["id"])
        JournalEntry.objects.filter(id=original["id"]).update(reversed_by_entry_id=other["id"])
    act(books, first["id"], "submit")
    act(books, first["id"], "approve", team["reviewer"])
    response = act(books, first["id"], "post", team["reviewer"])
    assert response.status_code == 409
    assert response.json()["code"] == "ledger.entry.already_reversed"


def test_edited_reversal_that_no_longer_mirrors_cannot_post(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    original = post_through_workflow(books, team["reviewer"], *SALE)
    draft = reverse(books, original["id"]).json()
    edited = books["client"].put_json(
        f"{books['base']}/journal-entries/{draft['id']}",
        payload(books, ("4000", "500.00", "0"), ("1300", "0", "500.00"), day="2026-03-15"),
    )
    assert edited.status_code == 200, edited.content
    act(books, draft["id"], "submit")
    act(books, draft["id"], "approve", team["reviewer"])
    response = act(books, draft["id"], "post", team["reviewer"])
    assert response.status_code == 409
    assert "mirror" in response.json()["detail"]


def test_adjustments_must_reference_a_posted_entry(books: dict[str, Any]) -> None:
    draft = create(books, *SALE).json()
    body = {**payload(books, ("6100", "10.00", "0"), ("1300", "0", "10.00")), "reason": "Fee fix"}
    response = books["client"].post_json(
        f"{books['base']}/journal-entries/{draft['id']}/adjust", body
    )
    assert response.status_code == 409


# --- period unlock state rules -------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [4, corrections.MAX_UNLOCK_MINUTES + 1])
def test_service_rejects_unlock_windows_out_of_range(books: dict[str, Any], minutes: int) -> None:
    period_id = _lock_march(books)
    with transaction.atomic():
        ctx = _ctx(books)
        with pytest.raises(ValidationFailedError):
            corrections.request_unlock(
                ctx,
                uuid.UUID(books["entity"]["id"]),
                uuid.UUID(period_id),
                reason="Late supplier invoice",
                window_minutes=minutes,
            )


def test_new_request_while_an_unlock_is_active_is_refused(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    period_id = _lock_march(books)
    unlock = _request(books, team["accountant"], period_id).json()
    _decide(books, team["manager"], unlock["id"])
    assert _decide(books, books["client"], unlock["id"]).json()["status"] == "ACTIVE"
    again = _request(books, team["accountant"], period_id)
    assert again.status_code == 409


def test_unlock_decisions_follow_the_state_machine(
    books: dict[str, Any], team: dict[str, Any]
) -> None:
    assert _decide(books, team["manager"], str(uuid.uuid4())).status_code == 404
    period_id = _lock_march(books)
    unlock = _request(books, team["accountant"], period_id).json()
    # Closing is only for active unlocks.
    assert _decide(books, team["accountant"], unlock["id"], "close").status_code == 409
    assert _decide(books, team["manager"], unlock["id"], "reject").status_code == 200
    # A rejected request can be neither approved nor rejected again.
    assert _decide(books, books["client"], unlock["id"]).status_code == 409
    assert _decide(books, books["client"], unlock["id"], "reject").status_code == 409


def test_linking_a_non_reversal_is_a_no_op(books: dict[str, Any], reviewer: Any) -> None:
    posted = post_through_workflow(books, reviewer, *SALE)
    with transaction.atomic():
        set_context(tenant_id=books["ws"]["id"])
        entry = JournalEntry.objects.get(id=posted["id"])
        corrections.link_reversal(entry)
        assert JournalEntry.objects.get(id=posted["id"]).reversed_by_entry_id is None
