"""Year-end close and re-open (M2-9, AC-M2-9; doc 05 §5)."""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from django.db import DatabaseError, connection, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger import periods

from .conftest import join
from .test_dimensions import commit_point, make_dimension, set_rules
from .test_entries import act, create, reviewer

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["reviewer"]


def no_approval(books: dict[str, Any]) -> None:
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})


def post(
    books: dict[str, Any],
    *lines: tuple[str, str, str],
    day: str = "2026-03-15",
    dims: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    acc = books["accounts"]
    body = {
        "accounting_date": day,
        "description": "Entry",
        "lines": [
            {
                "account_id": acc[c]["id"],
                "debit": d,
                "credit": cr,
                "dimension_value_ids": (dims or {}).get(c, []),
            }
            for c, d, cr in lines
        ],
    }
    draft = books["client"].post_json(f"{books['base']}/journal-entries", body)
    assert draft.status_code == 201, draft.content
    posted = act(books, draft.json()["id"], "post")
    assert posted.status_code == 200, posted.content
    result: dict[str, Any] = posted.json()
    return result


def fy_url(books: dict[str, Any], fy: dict[str, Any] | None = None) -> str:
    return f"{books['base']}/fiscal-years/{(fy or books['fy'])['id']}"


def close_status(books: dict[str, Any], fy: dict[str, Any] | None = None) -> dict[str, Any]:
    response = books["client"].get(f"{fy_url(books, fy)}/close")
    assert response.status_code == 200, response.content
    body: dict[str, Any] = response.json()
    return body


def generate(
    books: dict[str, Any],
    account: str = "3200",
    client: Any = None,
    fy: dict[str, Any] | None = None,
) -> Any:
    return (client or books["client"]).post_json(
        f"{fy_url(books, fy)}/close",
        {"retained_earnings_account_id": books["accounts"][account]["id"]},
    )


def tb(books: dict[str, Any], as_of: str = "2026-12-31") -> dict[str, tuple[str, str]]:
    """Non-zero balances (accounts with activity but a zero balance are left out)."""
    rows = books["client"].get(f"{books['base']}/reports/trial-balance", {"as_of": as_of}).json()
    return {
        r["code"]: (r["debit"], r["credit"])
        for r in rows["rows"]
        if (r["debit"], r["credit"]) != ("0.00", "0.00")
    }


def close_year(books: dict[str, Any]) -> dict[str, Any]:
    generated = generate(books)
    assert generated.status_code == 201, generated.content
    posted = act(books, generated.json()["id"], "post")
    assert posted.status_code == 200, posted.content
    commit_point()
    body: dict[str, Any] = posted.json()
    return body


@pytest.fixture
def year(books: dict[str, Any]) -> dict[str, Any]:
    """FY2026 with a profit of 700: sales 1000, rent 300."""
    no_approval(books)
    post(books, ("1300", "1000.00", "0"), ("4000", "0", "1000.00"))
    post(books, ("6100", "300.00", "0"), ("1300", "0", "300.00"), day="2026-06-30")
    commit_point()
    return books


def test_close_moves_the_result_to_retained_earnings_and_closes_the_year(
    year: dict[str, Any],
) -> None:
    preview = close_status(year)
    assert preview["status"] == "OPEN"
    assert preview["result"] == "700.00"
    assert preview["blockers"] == []
    assert [(ln["account_code"], ln["balance"]) for ln in preview["lines"]] == [
        ("4000", "-1000.00"),
        ("6100", "300.00"),
    ]

    generated = generate(year)
    assert generated.status_code == 201, generated.content
    entry = generated.json()
    assert (entry["entry_type"], entry["status"], entry["accounting_date"]) == (
        "CLOSING",
        "SUBMITTED",
        "2026-12-31",
    )
    assert [(ln["account_code"], ln["debit"], ln["credit"]) for ln in entry["lines"]] == [
        ("4000", "1000.00", "0.00"),
        ("6100", "0.00", "300.00"),
        ("3200", "0.00", "700.00"),
    ]

    posted = act(year, entry["id"], "post")
    assert posted.status_code == 200, posted.content
    commit_point()
    adjustment = next(p for p in year["fy"]["periods"] if p["number"] == 13)
    assert posted.json()["period_id"] == adjustment["id"]  # the adjustment period
    balances = tb(year)
    assert "4000" not in balances
    assert "6100" not in balances
    assert balances["3200"] == ("0.00", "700.00")
    assert balances["1300"] == ("700.00", "0.00")

    closed = close_status(year)
    assert closed["status"] == "CLOSED"
    assert closed["closing_entry_id"] == entry["id"]
    assert {c["code"]: c["ok"] for c in closed["checks"]} == {
        "result_closed": True,
        "opening_equals_closing_balance_sheet": True,
    }
    set_context(tenant_id=year["ws"]["id"])
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"ledger.fiscal_year.close_generated", "ledger.fiscal_year.closed"} <= actions


def test_a_closed_year_refuses_postings_in_the_app_and_the_database(
    year: dict[str, Any],
) -> None:
    close_year(year)
    late = create(year, ("6100", "50.00", "0"), ("1300", "0", "50.00"), day="2026-06-01").json()
    refused = act(year, late["id"], "post")
    assert refused.status_code == 409
    assert refused.json()["code"] == "ledger.fiscal_year.closed"

    set_context(tenant_id=year["ws"]["id"])
    period = periods.period_for_date(year["entity"]["id"], date(2026, 6, 1))
    assert period is not None
    with (
        pytest.raises(DatabaseError, match="closed fiscal year"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(
            "UPDATE ledger_journal_entry SET status = 'POSTED', period_id = %s, "
            "fiscal_year_id = %s, entry_no = 999, posting_seq = 999 WHERE id = %s",
            [period.id, period.fiscal_year_id, late["id"]],
        )


def reopen(books: dict[str, Any]) -> None:
    reopened = books["client"].post_json(f"{fy_url(books)}/reopen", {"reason": "Audit adjustment"})
    assert reopened.status_code == 201, reopened.content
    reversal = reopened.json()
    assert (reversal["entry_type"], reversal["status"], reversal["accounting_date"]) == (
        "REVERSAL",
        "SUBMITTED",
        "2026-12-31",
    )
    assert close_status(books)["reopen_entry_id"] == reversal["id"]
    assert act(books, reversal["id"], "post").status_code == 200
    commit_point()
    assert close_status(books)["status"] == "OPEN"


def test_reopen_and_close_again_reproduces_the_same_balances(year: dict[str, Any]) -> None:
    close_year(year)
    after_first = tb(year)
    reopen(year)
    assert tb(year)["4000"] == ("0.00", "1000.00")  # the result is back in the P&L
    close_year(year)
    assert tb(year) == after_first

    # An audit adjustment in a second cycle: the new result moves to retained earnings.
    reopen(year)
    post(year, ("6900", "100.00", "0"), ("1300", "0", "100.00"), day="2026-12-31")
    close_year(year)
    assert tb(year) == {"1300": ("600.00", "0.00"), "3200": ("0.00", "600.00")}
    set_context(tenant_id=year["ws"]["id"])
    assert AuditEvent.objects.filter(action="ledger.fiscal_year.reopened").count() == 2


def test_closing_is_blocked_while_something_is_unfinished(year: dict[str, Any]) -> None:
    draft = create(year, ("6100", "10.00", "0"), ("1300", "0", "10.00")).json()
    blocked = generate(year)
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ledger.close.blocked"
    assert "1 entries dated in 2026 are not posted" in blocked.json()["detail"]
    assert act(year, draft["id"], "void").status_code == 200

    earlier = year["client"].post_json(f"{year['base']}/fiscal-years", {"start_date": "2025-01-01"})
    assert earlier.status_code == 201
    assert "Close the earlier fiscal year(s) first: 2025" in close_status(year)["blockers"][0]

    assert "no income or expense balances" in close_status(year, earlier.json())["blockers"][0]


def test_only_one_closing_entry_at_a_time_and_it_cannot_be_edited(year: dict[str, Any]) -> None:
    first = generate(year).json()
    second = generate(year)
    assert second.status_code == 409, second.json()
    assert "already submitted" in second.json()["detail"]
    edit = year["client"].put_json(
        f"{year['base']}/journal-entries/{first['id']}",
        {
            "accounting_date": "2026-12-31",
            "description": "x",
            "lines": [
                {"account_id": year["accounts"]["6100"]["id"], "debit": "1.00"},
                {"account_id": year["accounts"]["1300"]["id"], "credit": "1.00"},
            ],
        },
    )
    assert edit.status_code == 409, edit.json()
    assert act(year, first["id"], "post").status_code == 200
    commit_point()
    reverse = act(year, first["id"], "reverse", body={"reason": "Reverse the year-end close"})
    assert reverse.status_code == 409, reverse.json()
    assert "re-opening its fiscal year" in reverse.json()["detail"]


def test_a_stale_closing_entry_is_refused_at_posting(year: dict[str, Any]) -> None:
    entry = generate(year).json()
    post(year, ("6900", "25.00", "0"), ("1300", "0", "25.00"), day="2026-11-30")
    refused = act(year, entry["id"], "post")
    assert refused.status_code == 409
    assert refused.json()["code"] == "ledger.close.stale"
    assert act(year, entry["id"], "reject", body={"reason": "stale"}).status_code == 200
    assert act(year, entry["id"], "void").status_code == 200
    close_year(year)
    assert tb(year)["3200"] == ("0.00", "675.00")


def test_retained_earnings_must_be_a_postable_equity_account(year: dict[str, Any]) -> None:
    refused = generate(year, account="4000")
    assert refused.status_code == 422
    assert refused.json()["errors"] == {
        "retained_earnings_account_id": ["must be an active, postable equity account"]
    }


def test_closing_keeps_dimension_tags_and_ignores_rules_added_later(year: dict[str, Any]) -> None:
    dim = make_dimension(year)
    post(year, ("6100", "200.00", "0"), ("1300", "0", "200.00"), dims={"6100": [dim["v"]["SALES"]]})
    commit_point()
    # A rule added after the fact must not prevent closing the untagged rent posted earlier.
    assert (
        set_rules(year, "6100", [{"dimension_id": dim["id"], "rule": "REQUIRED"}]).status_code
        == 200
    )
    entry = generate(year).json()
    rent = [
        (ln["debit"], ln["credit"], [d["value_id"] for d in ln["dimensions"]])
        for ln in entry["lines"]
        if ln["account_code"] == "6100"
    ]
    assert sorted(rent) == sorted([("0.00", "300.00", []), ("0.00", "200.00", [dim["v"]["SALES"]])])
    assert act(year, entry["id"], "post").status_code == 200
    commit_point()
    tagged = year["client"].get(
        f"{year['base']}/reports/trial-balance",
        {"as_of": "2026-12-31", "dimension_value_id": dim["v"]["SALES"]},
    )
    rent_rows = [(r["debit"], r["credit"]) for r in tagged.json()["rows"] if r["code"] == "6100"]
    assert rent_rows in ([], [("0.00", "0.00")])  # the tagged rent is closed too


def test_closing_needs_lock_permission_and_follows_the_approval_workflow(
    books: dict[str, Any], reviewer: Any, make_user: Make, api_client: Make
) -> None:
    post_with = books["client"]
    draft = create(books, ("1300", "500.00", "0"), ("4000", "0", "500.00")).json()
    assert act(books, draft["id"], "submit").status_code == 200
    assert act(books, draft["id"], "approve", reviewer).status_code == 200
    assert act(books, draft["id"], "post", reviewer).status_code == 200
    commit_point()
    accountant = join(
        post_with, books["ws"]["slug"], make_user("acc@example.test"), api_client, "accountant"
    )
    assert generate(books, client=accountant).status_code == 403
    entry = generate(books).json()  # the owner prepares it ...
    assert act(books, entry["id"], "approve").status_code == 403  # ... so cannot approve it
    assert act(books, entry["id"], "approve", reviewer).status_code == 200
    assert act(books, entry["id"], "post", reviewer).status_code == 200
    commit_point()
    assert close_status(books)["status"] == "CLOSED"


def test_reopen_rules_and_unknown_inputs(year: dict[str, Any]) -> None:
    not_closed = year["client"].post_json(f"{fy_url(year)}/reopen", {"reason": "Nothing to do"})
    assert not_closed.status_code == 409
    assert "is not closed" in not_closed.json()["detail"]
    missing = f"{year['base']}/fiscal-years/00000000-0000-7000-8000-000000000000/close"
    assert year["client"].get(missing).status_code == 404
    unknown = year["client"].post_json(
        f"{fy_url(year)}/close",
        {"retained_earnings_account_id": "00000000-0000-7000-8000-000000000000"},
    )
    assert unknown.status_code == 422

    close_year(year)
    later = year["client"].post_json(f"{year['base']}/fiscal-years", {"start_date": "2027-01-01"})
    assert later.status_code == 201
    post(year, ("1300", "10.00", "0"), ("4000", "0", "10.00"), day="2027-02-01")
    commit_point()
    closed_later = generate(year, fy=later.json())
    assert closed_later.status_code == 201, closed_later.content
    assert act(year, closed_later.json()["id"], "post").status_code == 200
    commit_point()
    refused = year["client"].post_json(f"{fy_url(year)}/reopen", {"reason": "Audit adjustment"})
    assert refused.status_code == 409
    assert "later closed fiscal year(s) first: 2027" in refused.json()["detail"]


def test_a_zero_result_closes_without_a_retained_earnings_line(books: dict[str, Any]) -> None:
    no_approval(books)
    post(books, ("1300", "100.00", "0"), ("4000", "0", "100.00"))
    post(books, ("6100", "100.00", "0"), ("1300", "0", "100.00"))
    commit_point()
    entry = generate(books).json()
    assert {ln["account_code"] for ln in entry["lines"]} == {"4000", "6100"}
    assert act(books, entry["id"], "post").status_code == 200
    commit_point()
    assert close_status(books)["status"] == "CLOSED"
