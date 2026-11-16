"""Corrections and period unlocks (doc 05 §4, backlog M1-9).

There is no "edit posted entry" path anywhere. Errors are corrected by:
- **reversal**: a mirrored entry linked both ways; an entry can be reversed once (AC-C6);
- **adjustment**: a new entry referencing the original, with a mandatory reason;
- **period unlock**: two distinct approvers (neither the requester, both with a recent sign-in)
  open a time-boxed window; entries posted in it are tagged with the unlock (AC-C7).
"""

from datetime import date, timedelta
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import entries
from .errors import AlreadyReversedError, InvalidStateError, SegregationOfDutiesError
from .models import JournalEntry, JournalLine, Period, PeriodUnlock
from .periods import first_open_period_on_or_after, get_period

MAX_UNLOCK_MINUTES = 8 * 60


def _require_reason(reason: str, field: str = "reason") -> str:
    cleaned = reason.strip()
    if len(cleaned) < 5:
        raise ValidationFailedError(
            "Explain the correction (at least 5 characters); it is kept in the audit trail.",
            field_errors={field: ["required"]},
        )
    return cleaned


# --- reversal ------------------------------------------------------------------------------------


def _reversal_date(original: JournalEntry, requested: date | None) -> date:
    if requested is not None:
        return requested
    period = original.period
    if period is not None and period.status == Period.Status.OPEN:
        return original.accounting_date
    open_period = first_open_period_on_or_after(original.legal_entity_id, original.accounting_date)
    if open_period is None:
        raise ValidationFailedError(
            "The original period is closed and there is no later open period. Open a period or "
            "give a reversal date.",
            field_errors={"reversal_date": ["required"]},
        )
    return open_period.start_date


@transaction.atomic
def reverse(
    ctx: WorkspaceContext,
    entity_id: UUID,
    entry_id: UUID,
    *,
    reason: str,
    reversal_date: date | None = None,
) -> JournalEntry:
    """Create the reversal as a draft; it follows the normal approval workflow to be posted."""
    get_entity(ctx, entity_id, "ledger.entry.create")
    reason = _require_reason(reason)
    original = entries.get_entry(ctx, entity_id, entry_id, lock=True)
    if original.status != JournalEntry.Status.POSTED:
        raise InvalidStateError("Only posted entries can be reversed; void drafts instead.")
    if original.entry_type == JournalEntry.EntryType.REVERSAL:
        raise InvalidStateError("A reversal cannot itself be reversed; post a new entry instead.")
    if (
        original.reversed_by_entry_id
        or JournalEntry.objects.filter(reverses_entry=original)
        .exclude(status__in=[JournalEntry.Status.VOID, JournalEntry.Status.REJECTED])
        .exists()
    ):
        raise AlreadyReversedError(
            "This entry has already been reversed (or a reversal is pending)."
        )
    mirrored = [
        entries.LineInput(
            line.account_id,
            debit=f"{line.credit:.2f}",
            credit=f"{line.debit:.2f}",
            memo=line.memo,
            dimension_value_ids=tuple(t.value_id for t in line.dimension_tags.all()),
            counterparty_id=line.counterparty_id,
            reference=line.reference,
            due_date=line.due_date,
        )
        for line in sorted(original.lines.all(), key=lambda ln: ln.line_no)
    ]
    data = entries.EntryInput(
        accounting_date=_reversal_date(original, reversal_date),
        description=f"Reversal of entry {original.journal.code}-{original.entry_no}: {reason}"[
            :500
        ],
        lines=mirrored,
        journal_code=original.journal.code,
    )
    try:
        with transaction.atomic():
            return entries.create_draft(
                ctx,
                entity_id,
                data,
                entry_type=JournalEntry.EntryType.REVERSAL,
                mirror=True,
                reverses_entry=original,
                correction_reason=reason,
            )
    except IntegrityError:
        raise AlreadyReversedError("This entry has already been reversed.") from None


def link_reversal(entry: JournalEntry) -> None:
    """At posting time: check the reversal mirrors the original and link the original back."""
    if entry.reverses_entry_id is None:
        return
    original = JournalEntry.objects.select_for_update().get(id=entry.reverses_entry_id)
    if original.status != JournalEntry.Status.POSTED or original.reversed_by_entry_id:
        raise AlreadyReversedError("The original entry is not posted or is already reversed.")

    def tags(ln: JournalLine) -> tuple[str, ...]:
        dims = sorted(str(t.value_id) for t in ln.dimension_tags.all())
        return (*dims, f"counterparty={ln.counterparty_id}")

    expected = sorted((ln.account_id, ln.credit, ln.debit, tags(ln)) for ln in original.lines.all())
    actual = sorted((ln.account_id, ln.debit, ln.credit, tags(ln)) for ln in entry.lines.all())
    if expected != actual:
        raise InvalidStateError("A reversal must exactly mirror the original entry's lines.")
    original.reversed_by_entry = entry
    original.save(update_fields=["reversed_by_entry"])


# --- adjustment ----------------------------------------------------------------------------------


@transaction.atomic
def adjust(
    ctx: WorkspaceContext,
    entity_id: UUID,
    related_entry_id: UUID,
    data: entries.EntryInput,
    *,
    reason: str,
) -> JournalEntry:
    reason = _require_reason(reason)
    related = entries.get_entry(ctx, entity_id, related_entry_id)
    if related.status != JournalEntry.Status.POSTED:
        raise InvalidStateError("Adjustments reference a posted entry.")
    return entries.create_draft(
        ctx,
        entity_id,
        data,
        entry_type=JournalEntry.EntryType.ADJUSTMENT,
        related_entry=related,
        correction_reason=reason,
    )


# --- period unlock -------------------------------------------------------------------------------


def _audit_unlock(
    ctx: WorkspaceContext, unlock: PeriodUnlock, action: str, **changes: object
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type="period_unlock",
        subject_id=unlock.id,
        entity_id=unlock.legal_entity_id,
        changes={"period_id": unlock.period_id, "status": unlock.status, **changes},
    )


def expire_if_due(unlock: PeriodUnlock) -> PeriodUnlock:
    if (
        unlock.status == PeriodUnlock.Status.ACTIVE
        and unlock.active_until is not None
        and unlock.active_until < timezone.now()
    ):
        unlock.status = PeriodUnlock.Status.CLOSED
        unlock.closed_at = unlock.active_until
        unlock.save(update_fields=["status", "closed_at"])
    return unlock


def active_unlock(period: Period) -> PeriodUnlock | None:
    unlock: PeriodUnlock | None = (
        PeriodUnlock.objects.select_for_update()
        .filter(period=period, status=PeriodUnlock.Status.ACTIVE)
        .first()
    )
    if unlock is None:
        return None
    unlock = expire_if_due(unlock)
    return unlock if unlock.status == PeriodUnlock.Status.ACTIVE else None


@transaction.atomic
def request_unlock(
    ctx: WorkspaceContext,
    entity_id: UUID,
    period_id: UUID,
    *,
    reason: str,
    window_minutes: int = 60,
) -> PeriodUnlock:
    get_entity(ctx, entity_id, "ledger.period.unlock_request")
    reason = _require_reason(reason)
    if not 5 <= window_minutes <= MAX_UNLOCK_MINUTES:
        raise ValidationFailedError(
            f"The unlock window is between 5 and {MAX_UNLOCK_MINUTES} minutes.",
            field_errors={"window_minutes": ["out of range"]},
        )
    period = get_period(ctx, entity_id, period_id)
    if period.status != Period.Status.LOCKED:
        raise InvalidStateError("Only locked periods need an unlock.")
    for existing in PeriodUnlock.objects.filter(period=period, status=PeriodUnlock.Status.ACTIVE):
        expire_if_due(existing)
    try:
        with transaction.atomic():
            unlock = PeriodUnlock.objects.create(
                tenant=ctx.tenant,
                legal_entity_id=entity_id,
                period=period,
                reason=reason,
                window_minutes=window_minutes,
                requested_by=ctx.user,
            )
    except IntegrityError:
        raise InvalidStateError("This period already has an open unlock request.") from None
    _audit_unlock(
        ctx, unlock, "ledger.period.unlock_requested", reason=reason, window_minutes=window_minutes
    )
    return unlock


def _get_unlock(ctx: WorkspaceContext, entity_id: UUID, unlock_id: UUID) -> PeriodUnlock:
    unlock: PeriodUnlock | None = (
        PeriodUnlock.objects.select_for_update()
        .filter(legal_entity_id=entity_id, id=unlock_id)
        .first()
    )
    if unlock is None:
        raise NotFoundError("Unlock request not found.")
    return expire_if_due(unlock)


@transaction.atomic
def approve_unlock(ctx: WorkspaceContext, entity_id: UUID, unlock_id: UUID) -> PeriodUnlock:
    get_entity(ctx, entity_id, "ledger.period.unlock_approve")
    unlock = _get_unlock(ctx, entity_id, unlock_id)
    if unlock.status != PeriodUnlock.Status.REQUESTED:
        raise InvalidStateError(f"This unlock is {unlock.status.lower()}.")
    if ctx.user.id == unlock.requested_by_id:
        raise SegregationOfDutiesError(
            "You requested this unlock, so two other people must approve it."
        )
    if ctx.user.id == unlock.first_approver_id:
        raise SegregationOfDutiesError(
            "You already approved this unlock; a second person must approve."
        )
    if unlock.first_approver_id is None:
        unlock.first_approver = ctx.user
        unlock.save(update_fields=["first_approver"])
        _audit_unlock(ctx, unlock, "ledger.period.unlock_approved", approval=1)
        return unlock
    now = timezone.now()
    unlock.second_approver = ctx.user
    unlock.status = PeriodUnlock.Status.ACTIVE
    unlock.active_from = now
    unlock.active_until = now + timedelta(minutes=unlock.window_minutes)
    unlock.save(update_fields=["second_approver", "status", "active_from", "active_until"])
    _audit_unlock(
        ctx, unlock, "ledger.period.unlock_approved", approval=2, active_until=unlock.active_until
    )
    return unlock


@transaction.atomic
def reject_unlock(
    ctx: WorkspaceContext, entity_id: UUID, unlock_id: UUID, note: str
) -> PeriodUnlock:
    get_entity(ctx, entity_id, "ledger.period.unlock_approve")
    unlock = _get_unlock(ctx, entity_id, unlock_id)
    if unlock.status != PeriodUnlock.Status.REQUESTED:
        raise InvalidStateError(f"This unlock is {unlock.status.lower()}.")
    unlock.status = PeriodUnlock.Status.REJECTED
    unlock.decision_note = note.strip()
    unlock.closed_at = timezone.now()
    unlock.save(update_fields=["status", "decision_note", "closed_at"])
    _audit_unlock(ctx, unlock, "ledger.period.unlock_rejected", note=unlock.decision_note)
    return unlock


@transaction.atomic
def close_unlock(ctx: WorkspaceContext, entity_id: UUID, unlock_id: UUID) -> PeriodUnlock:
    """Re-lock early (requester or an approver)."""
    get_entity(ctx, entity_id, "ledger.period.unlock_request")
    unlock = _get_unlock(ctx, entity_id, unlock_id)
    if unlock.status != PeriodUnlock.Status.ACTIVE:
        raise InvalidStateError(f"This unlock is {unlock.status.lower()}.")
    unlock.status = PeriodUnlock.Status.CLOSED
    unlock.closed_at = timezone.now()
    unlock.save(update_fields=["status", "closed_at"])
    _audit_unlock(ctx, unlock, "ledger.period.unlock_closed")
    return unlock


def list_unlocks(ctx: WorkspaceContext, entity_id: UUID) -> list[PeriodUnlock]:
    get_entity(ctx, entity_id, "ledger.period.read")
    unlocks = PeriodUnlock.objects.filter(legal_entity_id=entity_id).order_by("-created_at")
    return [expire_if_due(u) for u in unlocks]
