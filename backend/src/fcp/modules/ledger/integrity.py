"""Ledger integrity checks (doc 05 §7, AC-C10).

Run nightly for every workspace (``python manage.py ledger_integrity_check``) and on demand.
Each check is independent of the application logic that maintains the data, so a bug or a
tampered row is caught even if every write path believed it was correct.
"""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import structlog
from django.db import connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.api import verify as verify_audit_chain

from .models import IntegrityCheckRun

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CheckResult:
    check: str
    ok: bool
    details: list[str]


def _rows(sql: str, params: list[Any]) -> list[tuple[Any, ...]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return list(cursor.fetchall())


def _unbalanced_entries(tenant_id: UUID) -> CheckResult:
    rows = _rows(
        "SELECT e.id, coalesce(sum(l.debit), 0), coalesce(sum(l.credit), 0), count(l.id) "
        "FROM ledger_journal_entry e LEFT JOIN ledger_journal_line l ON l.entry_id = e.id "
        "WHERE e.tenant_id = %s AND e.status = 'POSTED' GROUP BY e.id "
        "HAVING coalesce(sum(l.debit), 0) <> coalesce(sum(l.credit), 0) OR count(l.id) < 2",
        [tenant_id],
    )
    return CheckResult(
        "posted_entries_balance",
        not rows,
        [f"entry {r[0]}: debits {r[1]} credits {r[2]} lines {r[3]}" for r in rows],
    )


def _snapshots_match_lines(tenant_id: UUID) -> CheckResult:
    rows = _rows(
        """
        WITH lines AS (
            SELECT l.account_id, e.period_id, sum(l.debit) AS d, sum(l.credit) AS c
            FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id
            WHERE e.tenant_id = %s AND e.status = 'POSTED'
            GROUP BY l.account_id, e.period_id
        ), snap AS (
            SELECT account_id, period_id, debit_total AS d, credit_total AS c
            FROM ledger_account_balance WHERE tenant_id = %s
        )
        SELECT coalesce(lines.account_id, snap.account_id),
               coalesce(lines.period_id, snap.period_id),
               lines.d, lines.c, snap.d, snap.c
        FROM lines FULL OUTER JOIN snap
          ON snap.account_id = lines.account_id AND snap.period_id = lines.period_id
        WHERE coalesce(lines.d, 0) <> coalesce(snap.d, 0)
           OR coalesce(lines.c, 0) <> coalesce(snap.c, 0)
        """,
        [tenant_id, tenant_id],
    )
    return CheckResult(
        "balances_match_lines",
        not rows,
        [f"account {r[0]} period {r[1]}: lines {r[2]}/{r[3]} snapshot {r[4]}/{r[5]}" for r in rows],
    )


def _gapless_numbers(tenant_id: UUID) -> CheckResult:
    rows = _rows(
        "SELECT journal_id, fiscal_year_id, count(*), min(entry_no), max(entry_no) "
        "FROM ledger_journal_entry WHERE tenant_id = %s AND status = 'POSTED' "
        "GROUP BY journal_id, fiscal_year_id "
        "HAVING min(entry_no) <> 1 OR max(entry_no) <> count(*)",
        [tenant_id],
    )
    details = [
        f"journal {r[0]} fiscal year {r[1]}: {r[2]} entries numbered {r[3]}..{r[4]}" for r in rows
    ]
    seq = _rows(
        "SELECT count(*), coalesce(min(posting_seq), 1), coalesce(max(posting_seq), 0) "
        "FROM ledger_journal_entry WHERE tenant_id = %s AND status = 'POSTED'",
        [tenant_id],
    )[0]
    if seq[0] and (seq[1] != 1 or seq[2] != seq[0]):
        details.append(f"posting_seq: {seq[0]} postings numbered {seq[1]}..{seq[2]}")
    return CheckResult("numbers_are_gapless", not details, details)


def _locked_periods_untouched(tenant_id: UUID) -> CheckResult:
    rows = _rows(
        "SELECT e.id, p.id FROM ledger_journal_entry e JOIN ledger_period p ON p.id = e.period_id "
        "WHERE e.tenant_id = %s AND e.status = 'POSTED' AND p.status = 'LOCKED' "
        "AND e.unlock_request_id IS NULL AND p.status_changed_at IS NOT NULL "
        "AND e.posted_at > p.status_changed_at",
        [tenant_id],
    )
    return CheckResult(
        "no_untagged_postings_after_lock",
        not rows,
        [f"entry {r[0]} posted into locked period {r[1]} without an unlock" for r in rows],
    )


def _audit_chain(tenant_id: UUID) -> CheckResult:
    status = verify_audit_chain(tenant_id)
    details = [] if status.ok else [f"seq {status.broken_at_seq}: {status.reason}"]
    return CheckResult("audit_chain_verifies", status.ok, details)


CHECKS = (
    _unbalanced_entries,
    _snapshots_match_lines,
    _gapless_numbers,
    _locked_periods_untouched,
    _audit_chain,
)


def run_checks(tenant_id: UUID, *, trigger: str = "SCHEDULE") -> IntegrityCheckRun:
    """Run every check for one workspace and store the result (own transaction)."""
    with transaction.atomic():
        set_context(tenant_id=tenant_id)
        results = [check(tenant_id) for check in CHECKS]
        ok = all(r.ok for r in results)
        run: IntegrityCheckRun = IntegrityCheckRun.objects.create(
            tenant_id=tenant_id,
            status=IntegrityCheckRun.Status.PASSED if ok else IntegrityCheckRun.Status.FAILED,
            results=[{"check": r.check, "ok": r.ok, "details": r.details[:50]} for r in results],
            trigger=trigger,
            finished_at=timezone.now(),
        )
    if not ok:
        failed = [r.check for r in results if not r.ok]
        log.error(
            "ledger.integrity_check_failed",
            tenant_id=str(tenant_id),
            count=len(failed),
            error_code="ledger.integrity_failure",
            job=",".join(failed),
        )
    return run
