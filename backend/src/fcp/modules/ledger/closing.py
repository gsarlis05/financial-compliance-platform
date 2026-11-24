"""Year-end close and re-open (M2-9; doc 05 §5; AC-M2-9; ADR-0014).

**Close.** A system ``CLOSING`` entry, dated the year-end (in the adjustment period when the year
has one), moves every income and expense balance to a retained-earnings account the user chooses.
It is split per account *and* per dimension tags, so dimensional P&L reports are zero after the
close as well. The entry is generated as *submitted* and follows the normal approval workflow.
At posting it is recomputed from the ledger: if any balance changed after it was generated, it is
refused (void it and generate it again). Posting it closes the fiscal year, and from then on the
database refuses postings into that year (migration 0015).

**Re-open.** The closing entry is reversed on its own date, again through the approval workflow.
Posting the reversal re-opens the year; closing again reproduces the same balances.

**Opening balances.** Balances in this ledger are cumulative (a trial balance sums every posting up
to a date), so the next year's opening trial balance *is* the closing trial balance. No OPENING
entry is posted at year end, because it would count the balances twice; ``OPENING`` entries are
for cut-over balances when a company moves in from another system. ``year_end_checks`` verifies
AC-M2-9: income and expense accounts are zero at the year-end, and the next year's opening trial
balance equals the closing balance sheet.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from django.db import connection, transaction
from django.db.models import QuerySet

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import entries
from .errors import CloseBlockedError, ClosingStaleError, InvalidStateError
from .models import Account, FiscalYear, JournalEntry, Period

ZERO = Decimal(0)
PL_TYPES = (Account.Type.INCOME, Account.Type.EXPENSE)
Status = JournalEntry.Status
EntryType = JournalEntry.EntryType
PENDING = (Status.DRAFT, Status.SUBMITTED, Status.APPROVED, Status.REJECTED)

_PL_BALANCES = """
WITH tagged AS (
    SELECT l.account_id, l.debit - l.credit AS net,
           coalesce((SELECT array_agg(t.value_id ORDER BY t.value_id)
                       FROM ledger_line_dimension t WHERE t.line_id = l.id), '{}') AS tags
      FROM ledger_journal_line l
      JOIN ledger_journal_entry e ON e.id = l.entry_id
      JOIN ledger_account a ON a.id = l.account_id
     WHERE e.legal_entity_id = %s AND e.status = 'POSTED' AND e.accounting_date <= %s
       AND a.type IN ('INCOME', 'EXPENSE')
)
SELECT account_id, tags, sum(net) FROM tagged GROUP BY account_id, tags HAVING sum(net) <> 0
"""


@dataclass(frozen=True)
class ClosingLine:
    """A non-zero income or expense balance at the year-end, per account and dimension tags."""

    account: Account
    value_ids: tuple[UUID, ...]
    net_debit: Decimal

    @property
    def key(self) -> tuple[UUID, tuple[UUID, ...]]:
        return self.account.id, self.value_ids


def pl_balances(entity_id: UUID, end_date: date) -> list[ClosingLine]:
    """Every non-zero income/expense balance up to ``end_date`` (current RLS context)."""
    with connection.cursor() as cursor:
        cursor.execute(_PL_BALANCES, [entity_id, end_date])
        rows = cursor.fetchall()
    accounts = Account.objects.in_bulk([r[0] for r in rows])
    lines = [ClosingLine(accounts[r[0]], tuple(sorted(r[1])), r[2]) for r in rows]
    return sorted(lines, key=lambda ln: (ln.account.code, [str(v) for v in ln.value_ids]))


@dataclass(frozen=True)
class Check:
    code: str
    ok: bool
    details: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CloseStatus:
    fiscal_year: FiscalYear
    lines: list[ClosingLine]
    blockers: list[str]
    closing_entry: JournalEntry | None  # pending, or posted and not reversed
    reopen_entry: JournalEntry | None  # a pending reversal of the closing entry
    checks: list[Check]  # AC-M2-9, once the year is closed

    @property
    def result(self) -> Decimal:
        """Profit (positive) or loss (negative) still to be closed."""
        return -sum((ln.net_debit for ln in self.lines), ZERO)


def _fiscal_year(entity_id: UUID, fiscal_year_id: UUID, *, lock: bool = False) -> FiscalYear:
    queryset = FiscalYear.objects.filter(legal_entity_id=entity_id, id=fiscal_year_id)
    year = (queryset.select_for_update() if lock else queryset).first()
    if year is None:
        raise NotFoundError("Fiscal year not found.")
    return year


def _closing_entries(year: FiscalYear) -> "QuerySet[JournalEntry]":
    return JournalEntry.objects.filter(
        legal_entity_id=year.legal_entity_id,
        entry_type=EntryType.CLOSING,
        accounting_date=year.end_date,
    ).exclude(status=Status.VOID)


def _live_closing(year: FiscalYear) -> JournalEntry | None:
    for entry in _closing_entries(year).order_by("-created_at"):
        if entry.status in PENDING or (
            entry.status == Status.POSTED and entry.reversed_by_entry_id is None
        ):
            return entry
    return None


def _pending_reopen(closing: JournalEntry | None) -> JournalEntry | None:
    if closing is None or closing.status != Status.POSTED:
        return None
    found: JournalEntry | None = JournalEntry.objects.filter(
        reverses_entry=closing, status__in=PENDING
    ).first()
    return found


def _blockers(
    year: FiscalYear, lines: list[ClosingLine], closing: JournalEntry | None
) -> list[str]:
    blockers = []
    if year.status == FiscalYear.Status.CLOSED:
        blockers.append(f"Fiscal year {year.name} is already closed.")
        return blockers
    earlier = FiscalYear.objects.filter(
        legal_entity_id=year.legal_entity_id,
        start_date__lt=year.start_date,
        status=FiscalYear.Status.OPEN,
    ).order_by("start_date")
    if earlier:
        names = ", ".join(y.name for y in earlier)
        blockers.append(f"Close the earlier fiscal year(s) first: {names}.")
    if closing is not None:
        blockers.append(
            f"A closing entry for {year.name} is already {closing.status.lower()}: post it, or "
            "void it to generate a new one."
        )
    unposted = (
        JournalEntry.objects.filter(
            legal_entity_id=year.legal_entity_id,
            accounting_date__gte=year.start_date,
            accounting_date__lte=year.end_date,
            status__in=PENDING,
        )
        .exclude(entry_type=EntryType.CLOSING)
        .count()
    )
    if unposted:
        blockers.append(
            f"{unposted} entries dated in {year.name} are not posted. Post or void them first, "
            "so nothing is posted into the year after it is closed."
        )
    if not lines and closing is None:
        blockers.append(f"{year.name} has no income or expense balances to close.")
    return blockers


def year_end_checks(entity_id: UUID, year: FiscalYear) -> list[Check]:
    """AC-M2-9 for a closed year: income and expense accounts are zero at the year-end, and the
    opening trial balance of the next year equals the closing balance sheet."""
    remaining = pl_balances(entity_id, year.end_date)
    checks = [
        Check(
            "result_closed",
            not remaining,
            [f"{ln.account.code}: {ln.net_debit:.2f}" for ln in remaining[:50]],
        )
    ]
    next_start = year.end_date + timedelta(days=1)
    closing = _net_by_account(entity_id, before=next_start, exclude_after=year.end_date)
    opening = _net_by_account(entity_id, before=next_start)
    differences = [
        f"{account_id}: closing {closing.get(account_id, ZERO):.2f}, "
        f"opening {opening.get(account_id, ZERO):.2f}"
        for account_id in sorted(set(closing) | set(opening), key=str)
        if closing.get(account_id, ZERO) != opening.get(account_id, ZERO)
    ]
    checks.append(Check("opening_equals_closing_balance_sheet", not differences, differences[:50]))
    return checks


def _net_by_account(
    entity_id: UUID, *, before: date, exclude_after: date | None = None
) -> dict[UUID, Decimal]:
    """Net debit per account from postings dated before ``before``. With ``exclude_after``, the
    closing balance sheet of the year ending that day (income and expense must be zero by then,
    so only balance-sheet accounts can remain)."""
    sql = (
        "SELECT l.account_id, a.type, sum(l.debit - l.credit) "
        "FROM ledger_journal_line l JOIN ledger_journal_entry e ON e.id = l.entry_id "
        "JOIN ledger_account a ON a.id = l.account_id "
        "WHERE e.legal_entity_id = %s AND e.status = 'POSTED' AND e.accounting_date < %s "
        "GROUP BY l.account_id, a.type"
    )
    with connection.cursor() as cursor:
        cursor.execute(sql, [entity_id, before])
        rows = cursor.fetchall()
    result: dict[UUID, Decimal] = {}
    for account_id, account_type, net in rows:
        if exclude_after is not None and account_type in PL_TYPES:
            continue  # the balance sheet: income and expense belong to the result
        if net:
            result[account_id] = net
    return result


def status(ctx: WorkspaceContext, entity_id: UUID, fiscal_year_id: UUID) -> CloseStatus:
    entity = get_entity(ctx, entity_id, "ledger.period.read")
    year = _fiscal_year(entity.id, fiscal_year_id)
    lines = pl_balances(entity.id, year.end_date)
    closing = _live_closing(year)
    closed = year.status == FiscalYear.Status.CLOSED
    return CloseStatus(
        fiscal_year=year,
        lines=lines,
        blockers=_blockers(year, lines, closing),
        closing_entry=closing,
        reopen_entry=_pending_reopen(closing),
        checks=year_end_checks(entity.id, year) if closed else [],
    )


def _retained_earnings(entity_id: UUID, account_id: UUID) -> Account:
    account = Account.objects.filter(legal_entity_id=entity_id, id=account_id).first()
    field_name = "retained_earnings_account_id"
    if account is None:
        raise ValidationFailedError("Account not found.", field_errors={field_name: ["not found"]})
    if (
        account.type != Account.Type.EQUITY
        or not account.is_postable
        or account.status != Account.Status.ACTIVE
    ):
        raise ValidationFailedError(
            f"Account {account.code} cannot take the result: choose an active, postable equity "
            "account such as retained earnings.",
            field_errors={field_name: ["must be an active, postable equity account"]},
        )
    return account


def _amounts(net_debit: Decimal) -> tuple[str, str]:
    """Debit and credit that bring a net debit balance to zero."""
    return (f"{-net_debit:.2f}", "0") if net_debit < 0 else ("0", f"{net_debit:.2f}")


@transaction.atomic
def generate(
    ctx: WorkspaceContext, entity_id: UUID, fiscal_year_id: UUID, retained_earnings_id: UUID
) -> JournalEntry:
    """Generate the closing entry as a submitted entry (prepared by the caller)."""
    entity = get_entity(ctx, entity_id, "ledger.period.lock")
    year = _fiscal_year(entity.id, fiscal_year_id, lock=True)  # one generation at a time
    lines = pl_balances(entity.id, year.end_date)
    blockers = _blockers(year, lines, _live_closing(year))
    if blockers:
        raise CloseBlockedError(" ".join(blockers))
    target = _retained_earnings(entity.id, retained_earnings_id)
    inputs = []
    for ln in lines:
        debit, credit = _amounts(ln.net_debit)
        inputs.append(
            entries.LineInput(
                ln.account.id,
                debit=debit,
                credit=credit,
                memo=f"Close {ln.account.code} to {target.code}"[:300],
                dimension_value_ids=ln.value_ids,
            )
        )
    total = sum((ln.net_debit for ln in lines), ZERO)
    if total:
        debit, credit = _amounts(-total)
        inputs.append(
            entries.LineInput(
                target.id, debit=debit, credit=credit, memo=f"Result of {year.name}"[:300]
            )
        )
    has_adjustment = Period.objects.filter(fiscal_year=year, is_adjustment=True).exists()
    data = entries.EntryInput(
        accounting_date=year.end_date,
        description=f"Year-end close {year.name}: income and expenses to {target.code} "
        f"{target.name}"[:500],
        lines=inputs,
        use_adjustment_period=has_adjustment,
    )
    entry = entries.create_draft(
        ctx,
        entity.id,
        data,
        entry_type=EntryType.CLOSING,
        source=JournalEntry.Source.SYSTEM,
        mirror=True,  # derived from posted balances, like a reversal
    )
    entries.submit(ctx, entity.id, entry.id)
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="ledger.fiscal_year.close_generated",
        subject_type="fiscal_year",
        subject_id=year.id,
        entity_id=entity.id,
        changes={
            "entry_id": entry.id,
            "retained_earnings_account": target.code,
            "result": f"{-total:.2f}",
            "lines": len(inputs),
        },
    )
    entry.refresh_from_db()
    return entry


@transaction.atomic
def reopen(
    ctx: WorkspaceContext, entity_id: UUID, fiscal_year_id: UUID, reason: str
) -> JournalEntry:
    """Reverse the closing entry on its own date (submitted; normal approval workflow)."""
    from .corrections import _require_reason, create_reversal  # noqa: PLC0415 - import cycle

    entity = get_entity(ctx, entity_id, "ledger.period.lock")
    reason = _require_reason(reason)
    year = _fiscal_year(entity.id, fiscal_year_id, lock=True)
    closing = _live_closing(year)
    if (
        year.status != FiscalYear.Status.CLOSED
        or closing is None
        or closing.status != Status.POSTED
    ):
        raise InvalidStateError(f"Fiscal year {year.name} is not closed.")
    later = FiscalYear.objects.filter(
        legal_entity_id=entity.id, start_date__gt=year.start_date, status=FiscalYear.Status.CLOSED
    ).order_by("start_date")
    if later:
        names = ", ".join(y.name for y in later)
        raise InvalidStateError(f"Re-open the later closed fiscal year(s) first: {names}.")
    reversal = create_reversal(
        ctx,
        entity.id,
        closing,
        reason=reason,
        accounting_date=closing.accounting_date,
        use_adjustment_period=closing.use_adjustment_period,
    )
    entries.submit(ctx, entity.id, reversal.id)
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="ledger.fiscal_year.reopen_requested",
        subject_type="fiscal_year",
        subject_id=year.id,
        entity_id=entity.id,
        changes={"entry_id": reversal.id, "closing_entry_id": closing.id, "reason": reason},
    )
    reversal.refresh_from_db()
    return reversal


# --- posting hooks (called by entries.post) -------------------------------------------------------


def verify_before_posting(entry: JournalEntry) -> None:
    """A closing entry must still close exactly the year's income and expense balances."""
    if entry.entry_type != EntryType.CLOSING:
        return
    expected = {
        ln.key: -ln.net_debit for ln in pl_balances(entry.legal_entity_id, entry.accounting_date)
    }
    actual: dict[tuple[UUID, tuple[UUID, ...]], Decimal] = defaultdict(lambda: ZERO)
    others = []
    for line in entry.lines.select_related("account").prefetch_related("dimension_tags"):
        if line.account.type in PL_TYPES:
            tags = tuple(sorted(t.value_id for t in line.dimension_tags.all()))
            actual[(line.account_id, tags)] += line.debit - line.credit
        else:
            others.append(line)
    stale = dict(actual) != expected
    if stale or len(others) > 1 or any(ln.account.type != Account.Type.EQUITY for ln in others):
        raise ClosingStaleError(
            "Income or expense balances changed after this closing entry was generated, so it no "
            "longer closes the year exactly. Void it and generate the closing entry again."
        )


def after_posting(ctx: WorkspaceContext, entry: JournalEntry) -> None:
    """Posting a closing entry closes its fiscal year; posting its reversal re-opens it."""
    is_reopen = (
        entry.entry_type == EntryType.REVERSAL
        and entry.reverses_entry is not None
        and entry.reverses_entry.entry_type == EntryType.CLOSING
    )
    if entry.entry_type != EntryType.CLOSING and not is_reopen:
        return
    if entry.fiscal_year_id is None:  # pragma: no cover - set by posting before this hook
        raise InvalidStateError("A posted entry has a fiscal year.")
    year = FiscalYear.objects.select_for_update().get(id=entry.fiscal_year_id)
    year.status = FiscalYear.Status.OPEN if is_reopen else FiscalYear.Status.CLOSED
    year.save(update_fields=["status"])
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="ledger.fiscal_year.reopened" if is_reopen else "ledger.fiscal_year.closed",
        subject_type="fiscal_year",
        subject_id=year.id,
        entity_id=entry.legal_entity_id,
        changes={"entry_id": entry.id, "entry_no": entry.entry_no},
    )
