"""Ledger integrity job detects corruption (doc 09 AC-C10)."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from fcp.core.db.rls import set_context
from fcp.modules.ledger.integrity import run_checks

from .conftest import join
from .test_entries import SALE, post_through_workflow

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]


@pytest.fixture
def posted(books: dict[str, Any], make_user: Make, api_client: Make) -> dict[str, Any]:
    reviewer = join(
        books["client"], books["ws"]["slug"], make_user("ir@example.test"), api_client, "reviewer"
    )
    first = post_through_workflow(books, reviewer, *SALE)
    second = post_through_workflow(books, reviewer, ("6100", "50.00", "0"), ("1300", "0", "50.00"))
    return {"first": first, "second": second}


def failed(tenant_id: Any) -> set[str]:
    run = run_checks(tenant_id)
    return {r["check"] for r in run.results if not r["ok"]}


@contextmanager
def tampering(*tables: str) -> Iterator[Any]:
    """An attacker with DDL rights disables the protection triggers."""
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        for table in tables:
            cursor.execute(f'ALTER TABLE "{table}" DISABLE TRIGGER USER')
        try:
            yield cursor
        finally:
            for table in tables:
                cursor.execute(f'ALTER TABLE "{table}" ENABLE TRIGGER USER')


def test_clean_ledger_passes(books: dict[str, Any], posted: dict[str, Any]) -> None:
    run = run_checks(books["ws"]["id"])
    assert run.status == "PASSED"
    assert {r["check"] for r in run.results} == {
        "posted_entries_balance",
        "balances_match_lines",
        "numbers_are_gapless",
        "no_untagged_postings_after_lock",
        "audit_chain_verifies",
    }


def test_corrupted_balance_snapshot_is_detected(
    books: dict[str, Any], posted: dict[str, Any]
) -> None:
    set_context(tenant_id=books["ws"]["id"])
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ledger_account_balance SET debit_total = debit_total + 0.01 "
            "WHERE debit_total > 0 AND id = (SELECT id FROM ledger_account_balance "
            "WHERE debit_total > 0 LIMIT 1)"
        )
    assert failed(books["ws"]["id"]) == {"balances_match_lines"}


def test_broken_audit_hash_is_detected(books: dict[str, Any], posted: dict[str, Any]) -> None:
    set_context(tenant_id=books["ws"]["id"])
    with tampering("audit_log_event") as cursor:
        cursor.execute("UPDATE audit_log_event SET action = 'forged' WHERE seq = 2")
    assert failed(books["ws"]["id"]) == {"audit_chain_verifies"}


def test_unbalanced_posted_entry_is_detected(books: dict[str, Any], posted: dict[str, Any]) -> None:
    set_context(tenant_id=books["ws"]["id"])
    with tampering("ledger_journal_line") as cursor:
        cursor.execute(
            "UPDATE ledger_journal_line SET credit = credit - 1 WHERE entry_id = %s "
            "AND credit > 0 AND line_no = 2",
            [posted["first"]["id"]],
        )
    assert "posted_entries_balance" in failed(books["ws"]["id"])


def test_numbering_gap_is_detected(books: dict[str, Any], posted: dict[str, Any]) -> None:
    set_context(tenant_id=books["ws"]["id"])
    with tampering("ledger_journal_entry") as cursor:
        cursor.execute(
            "UPDATE ledger_journal_entry SET entry_no = 7, posting_seq = 9 WHERE id = %s",
            [posted["second"]["id"]],
        )
    assert failed(books["ws"]["id"]) == {"numbers_are_gapless"}


def test_untagged_posting_after_lock_is_detected(
    books: dict[str, Any], posted: dict[str, Any]
) -> None:
    set_context(tenant_id=books["ws"]["id"])
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE ledger_period SET status = 'LOCKED', status_changed_at = now() - "
            "interval '1 day' WHERE id = %s",
            [posted["first"]["period_id"]],
        )
    assert failed(books["ws"]["id"]) == {"no_untagged_postings_after_lock"}


def test_command_checks_every_workspace_and_fails_loudly(
    books: dict[str, Any], posted: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    call_command("ledger_integrity_check")
    assert "Checked 1 workspace(s); 0 failed." in capsys.readouterr().out
    set_context(tenant_id=books["ws"]["id"])
    with connection.cursor() as cursor:
        cursor.execute("UPDATE ledger_account_balance SET credit_total = credit_total + 5")
    with pytest.raises(CommandError, match="1 workspace"):
        call_command("ledger_integrity_check")


def test_integrity_api_requires_permission(
    books: dict[str, Any], posted: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    slug = books["ws"]["slug"]
    created = books["client"].post_json(f"/api/w/{slug}/integrity-checks", {})
    assert created.status_code == 201
    assert created.json()["status"] == "PASSED"
    assert created.json()["trigger"] == "ON_DEMAND"
    assert len(books["client"].get(f"/api/w/{slug}/integrity-checks").json()) == 1
    viewer = join(books["client"], slug, make_user("v3@example.test"), api_client, "read_only")
    assert viewer.get(f"/api/w/{slug}/integrity-checks").status_code == 403
