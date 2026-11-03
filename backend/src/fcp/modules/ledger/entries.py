"""Journal entries: drafting, approval workflow and posting (doc 05 §2-3, backlog M1-8).

Lifecycle: DRAFT -> SUBMITTED -> APPROVED -> POSTED, with REJECTED (back to editing) and VOID.
The database enforces the same invariants independently (migration 0004): balance, one positive
side per line, immutability of posted rows and period status.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from fcp.core.errors import NotFoundError
from fcp.core.money import Money, MoneyError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import Tenant, WorkspaceContext, get_entity

from .errors import (
    AccountNotPostableError,
    ApprovalRequiredError,
    ApprovalStaleError,
    InvalidLineError,
    InvalidStateError,
    NoPeriodError,
    PeriodLockedError,
    PeriodSoftClosedError,
    PostingRejectedByDatabaseError,
    SegregationOfDutiesError,
    TooFewLinesError,
    UnbalancedEntryError,
)
from .models import (
    Account,
    EntrySequence,
    Journal,
    JournalEntry,
    JournalLine,
    LedgerSettings,
    Period,
    PostingCounter,
)
from .periods import period_for_date

Status = JournalEntry.Status
EDITABLE = (Status.DRAFT, Status.REJECTED)
DEFAULT_JOURNALS = {"GJ": "General journal"}


@dataclass(frozen=True)
class LineInput:
    account_id: UUID
    debit: str = "0"
    credit: str = "0"
    memo: str = ""


@dataclass(frozen=True)
class EntryInput:
    accounting_date: date
    description: str
    lines: Sequence[LineInput]
    document_date: date | None = None
    journal_code: str = "GJ"
    use_adjustment_period: bool = False


# --- settings, journals ----------------------------------------------------------------------


def ledger_settings(ctx: WorkspaceContext, entity_id: UUID) -> LedgerSettings:
    """The entity's controls, created with a kind-appropriate default on first use."""
    found: LedgerSettings | None = LedgerSettings.objects.filter(legal_entity_id=entity_id).first()
    if found is not None:
        return found
    policy = (
        LedgerSettings.Approval.NONE
        if ctx.tenant.kind == Tenant.Kind.PERSONAL
        else LedgerSettings.Approval.ALWAYS
    )
    # Race-safe first use: concurrent requests may both try to create the default row.
    LedgerSettings.objects.bulk_create(
        [
            LedgerSettings(
                tenant=ctx.tenant,
                legal_entity_id=entity_id,
                approval_policy=policy,
                updated_by=ctx.user,
            )
        ],
        ignore_conflicts=True,
    )
    created: LedgerSettings = LedgerSettings.objects.get(legal_entity_id=entity_id)
    return created


@transaction.atomic
def update_settings(
    ctx: WorkspaceContext, entity_id: UUID, *, approval_policy: str, threshold: str | None
) -> LedgerSettings:
    entity = get_entity(ctx, entity_id, "ledger.settings.manage")
    current = ledger_settings(ctx, entity.id)
    if approval_policy == LedgerSettings.Approval.THRESHOLD:
        if threshold is None:
            raise InvalidLineError(
                "A threshold amount is required for the threshold policy.",
                field_errors={"approval_threshold": ["required"]},
            )
        amount = Money.of(threshold, entity.functional_currency)
        if amount.is_negative() or not amount.is_rounded():
            raise InvalidLineError(
                "The threshold must be a non-negative amount in whole cents.",
                field_errors={"approval_threshold": ["invalid"]},
            )
    before = {
        "approval_policy": current.approval_policy,
        "approval_threshold": current.approval_threshold,
    }
    current.approval_policy = approval_policy
    current.approval_threshold = (
        Decimal(threshold)
        if approval_policy == LedgerSettings.Approval.THRESHOLD and threshold
        else None
    )
    current.updated_by = ctx.user
    current.save()
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="ledger.settings.updated",
        subject_type="ledger_settings",
        subject_id=current.id,
        entity_id=entity.id,
        changes={
            "before": before,
            "after": {
                "approval_policy": current.approval_policy,
                "approval_threshold": current.approval_threshold,
            },
        },
    )
    return current


def _journal(ctx: WorkspaceContext, entity_id: UUID, code: str) -> Journal:
    journal: Journal | None = Journal.objects.filter(legal_entity_id=entity_id, code=code).first()
    if journal is not None:
        return journal
    if code not in DEFAULT_JOURNALS:
        raise InvalidLineError("Unknown journal.", field_errors={"journal": ["not found"]})
    Journal.objects.bulk_create(
        [
            Journal(
                tenant=ctx.tenant, legal_entity_id=entity_id, code=code, name=DEFAULT_JOURNALS[code]
            )
        ],
        ignore_conflicts=True,
    )
    created: Journal = Journal.objects.get(legal_entity_id=entity_id, code=code)
    return created


# --- validation -------------------------------------------------------------------------------


def _amount(value: str, currency: str, field: str) -> Money:
    try:
        money = Money.of(value, currency)
    except (MoneyError, TypeError):
        raise InvalidLineError(
            "Amounts must be decimal numbers.", field_errors={field: ["invalid"]}
        ) from None
    if money.is_negative():
        raise InvalidLineError("Amounts cannot be negative.", field_errors={field: ["negative"]})
    if not money.is_rounded():
        raise InvalidLineError(
            f"Amounts in {currency} have at most {money.currency.minor_units} decimal places.",
            field_errors={field: ["too many decimal places"]},
        )
    return money


def _validated_lines(
    entity_id: UUID, currency: str, lines: Sequence[LineInput]
) -> list[dict[str, Any]]:
    """Structural checks that apply to drafts too (each line: one side, positive, rounded)."""
    accounts = {
        a.id: a
        for a in Account.objects.filter(
            legal_entity_id=entity_id, id__in=[ln.account_id for ln in lines]
        )
    }
    result = []
    for i, line in enumerate(lines):
        debit = _amount(line.debit, currency, f"lines.{i}.debit")
        credit = _amount(line.credit, currency, f"lines.{i}.credit")
        if debit.is_zero() == credit.is_zero():
            raise InvalidLineError(
                "Each line needs either a debit or a credit amount greater than zero, not both.",
                field_errors={f"lines.{i}": ["exactly one of debit or credit must be positive"]},
            )
        account = accounts.get(line.account_id)
        if account is None:
            raise InvalidLineError(
                "The account does not exist in this entity's chart of accounts.",
                field_errors={f"lines.{i}.account_id": ["not found"]},
            )
        if not account.is_postable or account.status != Account.Status.ACTIVE:
            raise AccountNotPostableError(
                f"Account {account.code} is a heading or inactive and cannot be posted to.",
                field_errors={f"lines.{i}.account_id": ["not postable"]},
            )
        result.append(
            {
                "line_no": i + 1,
                "account": account,
                "debit": debit.amount,
                "credit": credit.amount,
                "memo": line.memo.strip(),
            }
        )
    return result


def _check_complete(entry: JournalEntry) -> None:
    """Posting-level checks: at least two lines and balanced (AC-C1)."""
    lines = list(entry.lines.all())
    if len(lines) < 2:
        raise TooFewLinesError("An entry needs at least two lines.")
    debits = sum((ln.debit for ln in lines), Decimal(0))
    credits = sum((ln.credit for ln in lines), Decimal(0))
    if debits != credits:
        raise UnbalancedEntryError(
            f"Debits ({debits:.2f}) and credits ({credits:.2f}) differ by "
            f"{abs(debits - credits):.2f}. Correct the lines so they balance.",
            field_errors={"lines": [f"difference {abs(debits - credits):.2f}"]},
        )
    for ln in lines:
        if not ln.account.is_postable or ln.account.status != Account.Status.ACTIVE:
            raise AccountNotPostableError(
                f"Account {ln.account.code} is a heading or inactive and cannot be posted to."
            )


def content_hash(entry: JournalEntry) -> str:
    """Canonical hash of what is being approved; any change afterwards invalidates approval."""
    payload = {
        "legal_entity_id": str(entry.legal_entity_id),
        "journal_id": str(entry.journal_id),
        "entry_type": entry.entry_type,
        "accounting_date": entry.accounting_date.isoformat(),
        "document_date": entry.document_date.isoformat() if entry.document_date else None,
        "use_adjustment_period": entry.use_adjustment_period,
        "description": entry.description,
        "currency": entry.currency,
        "reverses_entry_id": str(entry.reverses_entry_id) if entry.reverses_entry_id else None,
        "related_entry_id": str(entry.related_entry_id) if entry.related_entry_id else None,
        "lines": [
            [ln.line_no, str(ln.account_id), f"{ln.debit:.2f}", f"{ln.credit:.2f}", ln.memo]
            for ln in sorted(entry.lines.all(), key=lambda x: x.line_no)
        ],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _total(entry: JournalEntry) -> Decimal:
    return sum((ln.debit for ln in entry.lines.all()), Decimal(0))


def approval_required(ctx: WorkspaceContext, entry: JournalEntry) -> bool:
    policy = ledger_settings(ctx, entry.legal_entity_id)
    if policy.approval_policy == LedgerSettings.Approval.NONE:
        return False
    if policy.approval_policy == LedgerSettings.Approval.ALWAYS:
        return True
    return _total(entry) > (policy.approval_threshold or Decimal(0))


# --- reading ------------------------------------------------------------------------------------


def get_entry(
    ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID, *, lock: bool = False
) -> JournalEntry:
    get_entity(ctx, entity_id, "ledger.entry.read")
    queryset = JournalEntry.objects.filter(legal_entity_id=entity_id, id=entry_id)
    if lock:
        queryset = queryset.select_for_update()
    entry: JournalEntry | None = queryset.first()
    if entry is None:
        raise NotFoundError("Journal entry not found.")
    return entry


def list_entries(  # noqa: PLR0913 - keyword-only filters
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[JournalEntry]:
    get_entity(ctx, entity_id, "ledger.entry.read")
    queryset = JournalEntry.objects.filter(legal_entity_id=entity_id).prefetch_related(
        "lines__account"
    )
    if status:
        queryset = queryset.filter(status=status)
    if date_from:
        queryset = queryset.filter(accounting_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(accounting_date__lte=date_to)
    return list(queryset.order_by("-accounting_date", "-created_at")[offset : offset + limit])


# --- drafting ------------------------------------------------------------------------------------


def _audit(
    ctx: WorkspaceContext, entry: JournalEntry, action: str, changes: dict[str, Any]
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type="journal_entry",
        subject_id=entry.id,
        entity_id=entry.legal_entity_id,
        changes=changes,
    )


def _line_snapshot(entry: JournalEntry) -> list[list[str]]:
    return [
        [ln.account.code, f"{ln.debit:.2f}", f"{ln.credit:.2f}", ln.memo]
        for ln in sorted(entry.lines.all(), key=lambda x: x.line_no)
    ]


def _write_lines(ctx: WorkspaceContext, entry: JournalEntry, lines: list[dict[str, Any]]) -> None:
    entry.lines.all().delete()
    JournalLine.objects.bulk_create(
        [JournalLine(tenant=ctx.tenant, entry=entry, **line) for line in lines]
    )


@transaction.atomic
def create_draft(  # noqa: PLR0913 - keyword-only options
    ctx: WorkspaceContext,
    entity_id: UUID,
    data: EntryInput,
    *,
    entry_type: str = JournalEntry.EntryType.STANDARD,
    reverses_entry: JournalEntry | None = None,
    related_entry: JournalEntry | None = None,
    correction_reason: str = "",
    source: str = JournalEntry.Source.MANUAL,
) -> JournalEntry:
    entity = get_entity(ctx, entity_id, "ledger.entry.create")
    lines = _validated_lines(entity.id, entity.functional_currency, data.lines)
    entry = JournalEntry.objects.create(
        tenant=ctx.tenant,
        legal_entity=entity,
        journal=_journal(ctx, entity.id, data.journal_code),
        entry_type=entry_type,
        source=source,
        accounting_date=data.accounting_date,
        document_date=data.document_date,
        use_adjustment_period=data.use_adjustment_period,
        description=data.description.strip(),
        currency=entity.functional_currency,
        reverses_entry=reverses_entry,
        related_entry=related_entry,
        correction_reason=correction_reason,
        prepared_by=ctx.user,
    )
    _write_lines(ctx, entry, lines)
    _audit(
        ctx,
        entry,
        "ledger.entry.created",
        {
            "entry_type": entry_type,
            "accounting_date": entry.accounting_date,
            "description": entry.description,
            "lines": _line_snapshot(entry),
            "reverses_entry_id": entry.reverses_entry_id,
            "correction_reason": correction_reason,
        },
    )
    return entry


@transaction.atomic
def update_draft(
    ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID, data: EntryInput
) -> JournalEntry:
    entity = get_entity(ctx, entity_id, "ledger.entry.create")
    entry = get_entry(ctx, entity_id, entry_id, lock=True)
    if entry.status not in EDITABLE:
        raise InvalidStateError(f"A {entry.status.lower()} entry cannot be edited.")
    lines = _validated_lines(entity.id, entity.functional_currency, data.lines)
    before = {
        "accounting_date": entry.accounting_date,
        "description": entry.description,
        "lines": _line_snapshot(entry),
    }
    entry.accounting_date = data.accounting_date
    entry.document_date = data.document_date
    entry.description = data.description.strip()
    entry.use_adjustment_period = data.use_adjustment_period
    entry.journal = _journal(ctx, entity.id, data.journal_code)
    entry.status = Status.DRAFT
    entry.approved_by, entry.approved_at, entry.approved_hash = None, None, ""
    entry.content_hash = ""
    entry.save()
    _write_lines(ctx, entry, lines)
    _audit(
        ctx,
        entry,
        "ledger.entry.updated",
        {
            "before": before,
            "after": {
                "accounting_date": entry.accounting_date,
                "description": entry.description,
                "lines": _line_snapshot(entry),
            },
        },
    )
    return entry


def _transition(
    ctx: WorkspaceContext, entry: JournalEntry, to: str, action: str, **changes: Any
) -> None:
    before = entry.status
    entry.status = to
    entry.save()
    _audit(ctx, entry, action, {"from": before, "to": to, **changes})


@transaction.atomic
def submit(ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID) -> JournalEntry:
    get_entity(ctx, entity_id, "ledger.entry.create")
    entry = get_entry(ctx, entity_id, entry_id, lock=True)
    if entry.status not in EDITABLE:
        raise InvalidStateError(f"A {entry.status.lower()} entry cannot be submitted.")
    _check_complete(entry)
    # Fail early if no period exists. Lock status is a posting-time rule, so a correction can be
    # prepared and approved while an unlock is being requested.
    if (
        period_for_date(
            entry.legal_entity_id, entry.accounting_date, adjustment=entry.use_adjustment_period
        )
        is None
    ):
        _posting_period(ctx, entry)  # raises the descriptive "no period" error
    entry.content_hash = content_hash(entry)
    entry.submitted_at = timezone.now()
    entry.rejection_reason = ""
    _transition(
        ctx, entry, Status.SUBMITTED, "ledger.entry.submitted", content_hash=entry.content_hash
    )
    return entry


@transaction.atomic
def approve(ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID) -> JournalEntry:
    get_entity(ctx, entity_id, "ledger.entry.approve")
    entry = get_entry(ctx, entity_id, entry_id, lock=True)
    if entry.status != Status.SUBMITTED:
        raise InvalidStateError("Only submitted entries can be approved.")
    if entry.prepared_by_id == ctx.user.id:
        raise SegregationOfDutiesError(
            "You prepared this entry, so someone else must approve it (segregation of duties)."
        )
    current = content_hash(entry)
    if current != entry.content_hash:
        raise ApprovalStaleError("The entry changed after it was submitted. Submit it again.")
    entry.approved_by, entry.approved_at, entry.approved_hash = ctx.user, timezone.now(), current
    _transition(ctx, entry, Status.APPROVED, "ledger.entry.approved", approved_hash=current)
    return entry


@transaction.atomic
def reject(ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID, reason: str) -> JournalEntry:
    get_entity(ctx, entity_id, "ledger.entry.approve")
    entry = get_entry(ctx, entity_id, entry_id, lock=True)
    if entry.status not in (Status.SUBMITTED, Status.APPROVED):
        raise InvalidStateError("Only submitted or approved entries can be rejected.")
    entry.rejection_reason = reason.strip()
    entry.approved_by, entry.approved_at, entry.approved_hash = None, None, ""
    _transition(ctx, entry, Status.REJECTED, "ledger.entry.rejected", reason=entry.rejection_reason)
    return entry


@transaction.atomic
def void(ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID) -> JournalEntry:
    get_entity(ctx, entity_id, "ledger.entry.create")
    entry = get_entry(ctx, entity_id, entry_id, lock=True)
    if entry.status not in EDITABLE:
        raise InvalidStateError(
            "Only draft or rejected entries can be voided; posted entries are reversed."
        )
    _transition(ctx, entry, Status.VOID, "ledger.entry.voided")
    return entry


# --- posting -------------------------------------------------------------------------------------


def _posting_period(ctx: WorkspaceContext, entry: JournalEntry) -> Period:
    period = period_for_date(
        entry.legal_entity_id, entry.accounting_date, adjustment=entry.use_adjustment_period
    )
    if period is None:
        raise NoPeriodError(
            f"There is no {'adjustment ' if entry.use_adjustment_period else ''}period for "
            f"{entry.accounting_date}. Create the fiscal year first.",
            field_errors={"accounting_date": ["no period"]},
        )
    if period.status == Period.Status.LOCKED:
        from .corrections import active_unlock  # noqa: PLC0415 - avoids an import cycle

        unlock = active_unlock(period)
        if unlock is None:
            raise PeriodLockedError(
                f"Period {period.number} of {period.fiscal_year.name} is locked. "
                "Request an unlock, which needs two approvers."
            )
        entry.unlock_request_id = unlock.id
    if period.status == Period.Status.SOFT_CLOSED and not ctx.can(
        "ledger.period.post_soft_closed", entry.legal_entity_id
    ):
        raise PeriodSoftClosedError(
            f"Period {period.number} of {period.fiscal_year.name} is soft-closed. Ask someone "
            "with permission to post into soft-closed periods."
        )
    return period


def _next_number(ctx: WorkspaceContext, entry: JournalEntry, period: Period) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ledger_entry_sequence "
            "(id, tenant_id, created_at, journal_id, fiscal_year_id, last_no) "
            "VALUES (gen_random_uuid(), %s, now(), %s, %s, 0) "
            "ON CONFLICT (journal_id, fiscal_year_id) DO NOTHING",
            [ctx.tenant.id, entry.journal_id, period.fiscal_year_id],
        )
    sequence = EntrySequence.objects.select_for_update().get(
        journal_id=entry.journal_id, fiscal_year_id=period.fiscal_year_id
    )
    sequence.last_no += 1
    sequence.save(update_fields=["last_no"])
    return sequence.last_no


def _next_posting_seq(ctx: WorkspaceContext) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO ledger_posting_counter (tenant_id, last_seq) VALUES (%s, 0) "
            "ON CONFLICT (tenant_id) DO NOTHING",
            [ctx.tenant.id],
        )
    counter = PostingCounter.objects.select_for_update().get(tenant_id=ctx.tenant.id)
    counter.last_seq += 1
    counter.save(update_fields=["last_seq"])
    return counter.last_seq


@transaction.atomic
def post(ctx: WorkspaceContext, entity_id: UUID, entry_id: UUID) -> JournalEntry:
    """Post an entry: validate, number gaplessly, stamp the watermark, update balances."""
    get_entity(ctx, entity_id, "ledger.entry.post")
    entry = get_entry(ctx, entity_id, entry_id, lock=True)
    if entry.status == Status.APPROVED:
        if content_hash(entry) != entry.approved_hash:
            raise ApprovalStaleError("The entry changed after it was approved. Submit it again.")
    elif entry.status in (Status.DRAFT, Status.SUBMITTED, Status.REJECTED):
        if entry.status == Status.REJECTED:
            raise InvalidStateError("A rejected entry must be corrected and submitted again.")
        if approval_required(ctx, entry):
            raise ApprovalRequiredError(
                "This entry must be approved by someone else before posting."
            )
    else:
        raise InvalidStateError(f"A {entry.status.lower()} entry cannot be posted.")

    _check_complete(entry)
    period = _posting_period(ctx, entry)
    entry.period = period
    entry.fiscal_year = period.fiscal_year
    entry.posted_in_soft_closed = period.status == Period.Status.SOFT_CLOSED
    entry.entry_no = _next_number(ctx, entry, period)
    entry.posting_seq = _next_posting_seq(ctx)
    entry.content_hash = content_hash(entry)
    entry.posted_by, entry.posted_at = ctx.user, timezone.now()
    previous = entry.status
    entry.status = Status.POSTED
    try:
        with transaction.atomic():
            entry.save()
    except IntegrityError as exc:
        # Our guard messages contain no personal data; surface the first line to the user.
        reason = str(exc).splitlines()[0] if str(exc) else "integrity rule"
        raise PostingRejectedByDatabaseError(
            f"Nothing was posted: {reason}. Check the period and try again."
        ) from None
    from .balances import apply_posting  # noqa: PLC0415 - avoids an import cycle
    from .corrections import link_reversal  # noqa: PLC0415

    if entry.reverses_entry_id:
        link_reversal(entry)
    apply_posting(entry)
    _audit(
        ctx,
        entry,
        "ledger.entry.posted",
        {
            "from": previous,
            "entry_no": entry.entry_no,
            "posting_seq": entry.posting_seq,
            "period_id": period.id,
            "content_hash": entry.content_hash,
            "soft_closed": entry.posted_in_soft_closed,
            "unlock_request_id": entry.unlock_request_id,
            "reverses_entry_id": entry.reverses_entry_id,
        },
    )
    return entry
