"""Trial balance, general ledger and CSV export (doc 05 §7, backlog M1-10).

Only POSTED entries count. A trial balance that does not balance is never shown: it raises an
integrity error and logs an alert, because it means the ledger itself is corrupt (AC-C8).
"""

import csv
import io
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from uuid import UUID

import structlog
from django.db import connection

from fcp.core.errors import DomainError, NotFoundError
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Account, JournalEntry

log = structlog.get_logger(__name__)
ZERO = Decimal(0)


class LedgerIntegrityError(DomainError):
    code = "ledger.integrity_failure"
    status = 500
    title = "Ledger integrity check failed"


@dataclass(frozen=True)
class TrialBalanceRow:
    account_id: UUID
    code: str
    name: str
    type: str
    normal_side: str
    debit_total: Decimal
    credit_total: Decimal

    @property
    def balance(self) -> Decimal:
        """Signed balance on the account's normal side (positive = normal)."""
        net = self.debit_total - self.credit_total
        return net if self.normal_side == Account.Side.DEBIT else -net

    @property
    def balance_debit(self) -> Decimal:
        net = self.debit_total - self.credit_total
        return net if net > 0 else ZERO

    @property
    def balance_credit(self) -> Decimal:
        net = self.credit_total - self.debit_total
        return net if net > 0 else ZERO


@dataclass(frozen=True)
class TrialBalance:
    as_of: date
    date_from: date | None
    rows: list[TrialBalanceRow]
    unposted_entries: int
    restated_after_lock: int
    total_debit: Decimal = field(init=False)
    total_credit: Decimal = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "total_debit", sum((r.balance_debit for r in self.rows), ZERO))
        object.__setattr__(self, "total_credit", sum((r.balance_credit for r in self.rows), ZERO))


def build_trial_balance(
    accounts: Iterable[Account],
    sums: Mapping[UUID, tuple[Decimal, Decimal]],
    *,
    include_zero: bool = False,
) -> list[TrialBalanceRow]:
    """Pure aggregation step (property-tested): one row per postable account with activity."""
    rows = []
    for account in sorted(accounts, key=lambda a: a.code):
        debit, credit = sums.get(account.id, (ZERO, ZERO))
        if not include_zero and debit == credit == ZERO:
            continue
        rows.append(
            TrialBalanceRow(
                account.id,
                account.code,
                account.name,
                account.type,
                account.normal_side,
                debit,
                credit,
            )
        )
    return rows


def _line_sums(
    entity_id: UUID, as_of: date, date_from: date | None
) -> dict[UUID, tuple[Decimal, Decimal]]:
    sql = (
        "SELECT l.account_id, coalesce(sum(l.debit), 0), coalesce(sum(l.credit), 0) "
        "FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id "
        "WHERE e.legal_entity_id = %s AND e.status = 'POSTED' AND e.accounting_date <= %s"
    )
    params: list[UUID | date] = [entity_id, as_of]
    if date_from is not None:
        sql += " AND e.accounting_date >= %s"
        params.append(date_from)
    sql += " GROUP BY l.account_id"
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return {row[0]: (row[1], row[2]) for row in cursor.fetchall()}


def trial_balance(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    as_of: date,
    date_from: date | None = None,
    include_zero: bool = False,
) -> TrialBalance:
    """Cumulative balances up to ``as_of`` (or activity within ``date_from``..``as_of``)."""
    get_entity(ctx, entity_id, "reports.read")
    accounts = Account.objects.filter(legal_entity_id=entity_id, is_postable=True)
    rows = build_trial_balance(
        accounts, _line_sums(entity_id, as_of, date_from), include_zero=include_zero
    )
    posted = JournalEntry.objects.filter(legal_entity_id=entity_id, accounting_date__lte=as_of)
    if date_from is not None:
        posted = posted.filter(accounting_date__gte=date_from)
    result = TrialBalance(
        as_of=as_of,
        date_from=date_from,
        rows=rows,
        unposted_entries=posted.filter(
            status__in=[
                JournalEntry.Status.DRAFT,
                JournalEntry.Status.SUBMITTED,
                JournalEntry.Status.APPROVED,
            ]
        ).count(),
        restated_after_lock=posted.filter(
            status=JournalEntry.Status.POSTED, unlock_request_id__isnull=False
        ).count(),
    )
    if result.total_debit != result.total_credit:
        log.error(
            "ledger.trial_balance_unbalanced",
            entity_id=str(entity_id),
            error_code=LedgerIntegrityError.code,
        )
        raise LedgerIntegrityError(
            "The trial balance does not balance, which means the ledger data is inconsistent. "
            "The incident has been logged; contact support."
        )
    return result


# --- general ledger ------------------------------------------------------------------------------


@dataclass(frozen=True)
class LedgerLine:
    entry_id: UUID
    entry_no: int
    journal: str
    accounting_date: date
    description: str
    memo: str
    debit: Decimal
    credit: Decimal
    running_balance: Decimal
    restated_after_lock: bool


@dataclass(frozen=True)
class AccountLedger:
    account: Account
    date_from: date
    date_to: date
    opening_balance: Decimal
    lines: list[LedgerLine]
    closing_balance: Decimal


def general_ledger(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, *, date_from: date, date_to: date
) -> AccountLedger:
    """Postings to one account with opening, running and closing balances on its normal side."""
    get_entity(ctx, entity_id, "reports.read")
    account: Account | None = Account.objects.filter(
        legal_entity_id=entity_id, id=account_id
    ).first()
    if account is None:
        raise NotFoundError("Account not found.")
    sign = Decimal(1) if account.normal_side == Account.Side.DEBIT else Decimal(-1)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT coalesce(sum(l.debit - l.credit), 0) FROM ledger_journal_line l "
            "JOIN ledger_journal_entry e ON e.id = l.entry_id WHERE l.account_id = %s "
            "AND e.status = 'POSTED' AND e.accounting_date < %s",
            [account_id, date_from],
        )
        row = cursor.fetchone()
        opening = sign * (row[0] if row else ZERO)
        cursor.execute(
            "SELECT e.id, e.entry_no, j.code, e.accounting_date, e.description, l.memo, l.debit, "
            "l.credit, e.unlock_request_id IS NOT NULL "
            "FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id "
            "JOIN ledger_journal j ON j.id = e.journal_id "
            "WHERE l.account_id = %s AND e.status = 'POSTED' "
            "AND e.accounting_date BETWEEN %s AND %s "
            "ORDER BY e.accounting_date, e.posting_seq, l.line_no",
            [account_id, date_from, date_to],
        )
        rows = cursor.fetchall()
    running = opening
    lines = []
    for entry_id, entry_no, journal, day, description, memo, debit, credit, restated in rows:
        running += sign * (debit - credit)
        lines.append(
            LedgerLine(
                entry_id,
                entry_no,
                journal,
                day,
                description,
                memo,
                debit,
                credit,
                running,
                restated,
            )
        )
    return AccountLedger(account, date_from, date_to, opening, lines, running)


# --- CSV export ----------------------------------------------------------------------------------

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str) -> str:
    """Neutralise spreadsheet formula injection in text cells (threat T9)."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def trial_balance_csv(tb: TrialBalance) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Account", "Name", "Type", "Debit", "Credit"])
    for r in tb.rows:
        writer.writerow(
            [
                safe_text(r.code),
                safe_text(r.name),
                r.type,
                _money(r.balance_debit),
                _money(r.balance_credit),
            ]
        )
    writer.writerow(["", "Total", "", _money(tb.total_debit), _money(tb.total_credit)])
    return out.getvalue()


def general_ledger_csv(gl: AccountLedger) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(
        [
            "Date",
            "Entry",
            "Description",
            "Memo",
            "Debit",
            "Credit",
            "Balance",
            "Restated after lock",
        ]
    )
    writer.writerow(
        [
            gl.date_from.isoformat(),
            "",
            "Opening balance",
            "",
            "",
            "",
            _money(gl.opening_balance),
            "",
        ]
    )
    for ln in gl.lines:
        writer.writerow(
            [
                ln.accounting_date.isoformat(),
                f"{ln.journal}-{ln.entry_no}",
                safe_text(ln.description),
                safe_text(ln.memo),
                _money(ln.debit),
                _money(ln.credit),
                _money(ln.running_balance),
                "yes" if ln.restated_after_lock else "",
            ]
        )
    writer.writerow(
        [gl.date_to.isoformat(), "", "Closing balance", "", "", "", _money(gl.closing_balance), ""]
    )
    return out.getvalue()
