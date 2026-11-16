"""Public interface of the ``ledger`` module and its HTTP routes.

All routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.identity.api import require_recent_auth
from fcp.modules.tenancy.api import workspace_ctx

from . import accounts, corrections, entries, idempotency, periods
from .models import Account, FiscalYear, JournalEntry, LedgerSettings, Period, PeriodUnlock

__all__ = ["Account", "FiscalYear", "JournalEntry", "Period", "router"]

router = Router(tags=["ledger"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class AccountIn(Schema):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=200)
    name_el: str = Field(default="", max_length=200)
    type: Account.Type
    parent_code: str | None = Field(default=None, max_length=20)
    is_postable: bool = True
    currency: str = Field(default="", pattern=r"^([A-Z]{3})?$")


class AccountPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_el: str | None = Field(default=None, max_length=200)
    status: Account.Status | None = None


class AccountOut(Schema):
    id: UUID
    code: str
    name: str
    name_el: str
    type: str
    normal_side: str
    parent_id: UUID | None
    is_postable: bool
    status: str
    currency: str


class TemplateIn(Schema):
    template: Literal["cy_business", "personal"]


class PeriodOut(Schema):
    id: UUID
    number: int
    start_date: date
    end_date: date
    is_adjustment: bool
    status: str


class FiscalYearIn(Schema):
    start_date: date
    months: int = Field(default=12, ge=1, le=18)
    adjustment_period: bool = True
    name: str | None = Field(default=None, max_length=40)


class FiscalYearOut(Schema):
    id: UUID
    name: str
    start_date: date
    end_date: date
    status: str
    periods: list[PeriodOut]


class PeriodStatusIn(Schema):
    status: Literal["OPEN", "SOFT_CLOSED", "LOCKED"]


def _fy_out(year: FiscalYear) -> FiscalYearOut:
    return FiscalYearOut(
        id=year.id,
        name=year.name,
        start_date=year.start_date,
        end_date=year.end_date,
        status=year.status,
        periods=[PeriodOut.from_orm(p) for p in sorted(year.periods.all(), key=lambda p: p.number)],
    )


# --- chart of accounts ---------------------------------------------------------------------------


@router.get(f"{BASE}/accounts", response=list[AccountOut])
@requires("ledger.account.read")
def list_accounts(request: HttpRequest, slug: str, entity_id: UUID) -> list[Account]:
    return accounts.list_accounts(workspace_ctx(request, slug, entity_id), entity_id)


@router.post(f"{BASE}/accounts", response={201: AccountOut})
@requires("ledger.account.manage")
def create_account(
    request: HttpRequest, slug: str, entity_id: UUID, payload: AccountIn
) -> Status[Account]:
    ctx = workspace_ctx(request, slug, entity_id)
    data = accounts.AccountInput(**payload.dict())
    return Status(201, accounts.create_account(ctx, entity_id, data))


@router.get(f"{BASE}/accounts/{{uuid:account_id}}", response=AccountOut)
@requires("ledger.account.read")
def get_account(request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID) -> Account:
    return accounts.get_account(workspace_ctx(request, slug, entity_id), entity_id, account_id)


@router.patch(f"{BASE}/accounts/{{uuid:account_id}}", response=AccountOut)
@requires("ledger.account.manage")
def update_account(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, payload: AccountPatch
) -> Account:
    ctx = workspace_ctx(request, slug, entity_id)
    return accounts.update_account(ctx, entity_id, account_id, **payload.dict(exclude_unset=True))


@router.post(f"{BASE}/accounts/apply-template", response={201: list[AccountOut]})
@requires("ledger.account.manage")
def apply_template(
    request: HttpRequest, slug: str, entity_id: UUID, payload: TemplateIn
) -> Status[list[Account]]:
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, accounts.apply_template(ctx, entity_id, payload.template))


# --- fiscal years and periods ----------------------------------------------------------------


@router.get(f"{BASE}/fiscal-years", response=list[FiscalYearOut])
@requires("ledger.period.read")
def list_fiscal_years(request: HttpRequest, slug: str, entity_id: UUID) -> list[FiscalYearOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_fy_out(y) for y in periods.list_fiscal_years(ctx, entity_id)]


@router.post(f"{BASE}/fiscal-years", response={201: FiscalYearOut})
@requires("ledger.period.manage")
def create_fiscal_year(
    request: HttpRequest, slug: str, entity_id: UUID, payload: FiscalYearIn
) -> Status[FiscalYearOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    year = periods.create_fiscal_year(ctx, entity_id, **payload.dict())
    return Status(201, _fy_out(year))


@router.post(f"{BASE}/periods/{{uuid:period_id}}/status", response=PeriodOut)
@requires("ledger.period.read")
def change_period_status(
    request: HttpRequest, slug: str, entity_id: UUID, period_id: UUID, payload: PeriodStatusIn
) -> Period:
    # The transition-specific permission (manage or lock) is enforced by the service.
    ctx = workspace_ctx(request, slug, entity_id)
    return periods.change_status(ctx, entity_id, period_id, payload.status)


# --- journal entries (M1-8) ---------------------------------------------------------------------

AMOUNT = r"^\d{1,15}(\.\d{1,4})?$"


class LineIn(Schema):
    account_id: UUID
    debit: str = Field(default="0", pattern=AMOUNT, description='Decimal string, e.g. "120.50"')
    credit: str = Field(default="0", pattern=AMOUNT, description="Decimal string")
    memo: str = Field(default="", max_length=300)


class EntryIn(Schema):
    accounting_date: date
    document_date: date | None = None
    description: str = Field(min_length=1, max_length=500)
    journal: str = Field(default="GJ", max_length=10)
    use_adjustment_period: bool = False
    lines: list[LineIn] = Field(min_length=1, max_length=500)


class LineOut(Schema):
    line_no: int
    account_id: UUID
    account_code: str
    debit: str
    credit: str
    memo: str


class EntryOut(Schema):
    id: UUID
    status: str
    entry_type: str
    journal: str
    entry_no: int | None
    posting_seq: int | None
    accounting_date: date
    document_date: date | None
    use_adjustment_period: bool
    description: str
    currency: str
    period_id: UUID | None
    reverses_entry_id: UUID | None
    reversed_by_entry_id: UUID | None
    related_entry_id: UUID | None
    correction_reason: str
    prepared_by_id: UUID
    approved_by_id: UUID | None
    posted_by_id: UUID | None
    rejection_reason: str
    unlock_request_id: UUID | None
    content_hash: str
    total_debit: str
    total_credit: str
    lines: list[LineOut]


class RejectIn(Schema):
    reason: str = Field(min_length=1, max_length=500)


class SettingsIn(Schema):
    approval_policy: LedgerSettings.Approval
    approval_threshold: str | None = Field(default=None, pattern=AMOUNT)


class SettingsOut(Schema):
    approval_policy: str
    approval_threshold: str | None


def entry_out(entry: JournalEntry) -> EntryOut:
    lines = sorted(entry.lines.all(), key=lambda ln: ln.line_no)
    return EntryOut(
        id=entry.id,
        status=entry.status,
        entry_type=entry.entry_type,
        journal=entry.journal.code,
        entry_no=entry.entry_no,
        posting_seq=entry.posting_seq,
        accounting_date=entry.accounting_date,
        document_date=entry.document_date,
        use_adjustment_period=entry.use_adjustment_period,
        description=entry.description,
        currency=entry.currency,
        period_id=entry.period_id,
        reverses_entry_id=entry.reverses_entry_id,
        reversed_by_entry_id=entry.reversed_by_entry_id,
        related_entry_id=entry.related_entry_id,
        correction_reason=entry.correction_reason,
        prepared_by_id=entry.prepared_by_id,
        approved_by_id=entry.approved_by_id,
        posted_by_id=entry.posted_by_id,
        rejection_reason=entry.rejection_reason,
        unlock_request_id=entry.unlock_request_id,
        content_hash=entry.content_hash,
        total_debit=f"{sum(ln.debit for ln in lines):.2f}",
        total_credit=f"{sum(ln.credit for ln in lines):.2f}",
        lines=[
            LineOut(
                line_no=ln.line_no,
                account_id=ln.account_id,
                account_code=ln.account.code,
                debit=f"{ln.debit:.2f}",
                credit=f"{ln.credit:.2f}",
                memo=ln.memo,
            )
            for ln in lines
        ],
    )


def _entry_input(payload: EntryIn) -> entries.EntryInput:
    return entries.EntryInput(
        accounting_date=payload.accounting_date,
        document_date=payload.document_date,
        description=payload.description,
        journal_code=payload.journal,
        use_adjustment_period=payload.use_adjustment_period,
        lines=[
            entries.LineInput(ln.account_id, ln.debit, ln.credit, ln.memo) for ln in payload.lines
        ],
    )


def _json(entry: JournalEntry) -> dict[str, Any]:
    body: dict[str, Any] = entry_out(entry).model_dump(mode="json")
    return body


@router.post(f"{BASE}/journal-entries", response={201: EntryOut})
@requires("ledger.entry.create")
def create_entry(
    request: HttpRequest, slug: str, entity_id: UUID, payload: EntryIn
) -> Status[dict[str, Any]]:
    ctx = workspace_ctx(request, slug, entity_id)
    status, body = idempotency.run(
        ctx,
        request,
        f"create:{entity_id}",
        payload.model_dump(mode="json"),
        lambda: (201, _json(entries.create_draft(ctx, entity_id, _entry_input(payload)))),
    )
    return Status(status, body)


class EntryFilter(Schema):
    status: JournalEntry.Status | None = None
    date_from: date | None = None
    date_to: date | None = None
    limit: int = Field(default=100, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


@router.get(f"{BASE}/journal-entries", response=list[EntryOut])
@requires("ledger.entry.read")
def list_entries(
    request: HttpRequest, slug: str, entity_id: UUID, filters: Query[EntryFilter]
) -> list[EntryOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    found = entries.list_entries(
        ctx,
        entity_id,
        status=filters.status,
        date_from=filters.date_from,
        date_to=filters.date_to,
        limit=filters.limit,
        offset=filters.offset,
    )
    return [entry_out(e) for e in found]


@router.get(f"{BASE}/journal-entries/{{uuid:entry_id}}", response=EntryOut)
@requires("ledger.entry.read")
def get_entry(request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID) -> EntryOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return entry_out(entries.get_entry(ctx, entity_id, entry_id))


@router.put(f"{BASE}/journal-entries/{{uuid:entry_id}}", response=EntryOut)
@requires("ledger.entry.create")
def update_entry(
    request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID, payload: EntryIn
) -> EntryOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return entry_out(entries.update_draft(ctx, entity_id, entry_id, _entry_input(payload)))


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/submit", response=EntryOut)
@requires("ledger.entry.create")
def submit_entry(request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID) -> EntryOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return entry_out(entries.submit(ctx, entity_id, entry_id))


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/approve", response=EntryOut)
@requires("ledger.entry.approve")
def approve_entry(request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID) -> EntryOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return entry_out(entries.approve(ctx, entity_id, entry_id))


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/reject", response=EntryOut)
@requires("ledger.entry.approve")
def reject_entry(
    request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID, payload: RejectIn
) -> EntryOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return entry_out(entries.reject(ctx, entity_id, entry_id, payload.reason))


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/post", response=EntryOut)
@requires("ledger.entry.post")
def post_entry(
    request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID
) -> Status[dict[str, Any]]:
    ctx = workspace_ctx(request, slug, entity_id)
    status, body = idempotency.run(
        ctx,
        request,
        f"post:{entry_id}",
        {},
        lambda: (200, _json(entries.post(ctx, entity_id, entry_id))),
    )
    return Status(status, body)


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/void", response=EntryOut)
@requires("ledger.entry.create")
def void_entry(request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID) -> EntryOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return entry_out(entries.void(ctx, entity_id, entry_id))


@router.get(f"{BASE}/ledger-settings", response=SettingsOut)
@requires("ledger.entry.read")
def get_settings(request: HttpRequest, slug: str, entity_id: UUID) -> SettingsOut:
    ctx = workspace_ctx(request, slug, entity_id)
    found = entries.ledger_settings(ctx, entity_id)
    threshold = found.approval_threshold
    return SettingsOut(
        approval_policy=found.approval_policy,
        approval_threshold=f"{threshold:.2f}" if threshold is not None else None,
    )


@router.put(f"{BASE}/ledger-settings", response=SettingsOut)
@requires("ledger.settings.manage")
def put_settings(
    request: HttpRequest, slug: str, entity_id: UUID, payload: SettingsIn
) -> SettingsOut:
    ctx = workspace_ctx(request, slug, entity_id)
    found = entries.update_settings(
        ctx,
        entity_id,
        approval_policy=payload.approval_policy,
        threshold=payload.approval_threshold,
    )
    threshold = found.approval_threshold
    return SettingsOut(
        approval_policy=found.approval_policy,
        approval_threshold=f"{threshold:.2f}" if threshold is not None else None,
    )


# --- corrections and period unlocks (M1-9) -------------------------------------------------------


class ReverseIn(Schema):
    reason: str = Field(min_length=1, max_length=500)
    reversal_date: date | None = None


class AdjustIn(EntryIn):
    reason: str = Field(min_length=1, max_length=500)


class UnlockIn(Schema):
    reason: str = Field(min_length=1, max_length=500)
    window_minutes: int = Field(default=60, ge=5, le=corrections.MAX_UNLOCK_MINUTES)


class UnlockDecisionIn(Schema):
    note: str = Field(default="", max_length=500)


class UnlockOut(Schema):
    id: UUID
    period_id: UUID
    reason: str
    window_minutes: int
    status: str
    requested_by_id: UUID
    first_approver_id: UUID | None
    second_approver_id: UUID | None
    active_from: datetime | None
    active_until: datetime | None
    closed_at: datetime | None
    decision_note: str


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/reverse", response={201: EntryOut})
@requires("ledger.entry.create")
def reverse_entry(
    request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID, payload: ReverseIn
) -> Status[EntryOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    reversal = corrections.reverse(
        ctx, entity_id, entry_id, reason=payload.reason, reversal_date=payload.reversal_date
    )
    return Status(201, entry_out(reversal))


@router.post(f"{BASE}/journal-entries/{{uuid:entry_id}}/adjust", response={201: EntryOut})
@requires("ledger.entry.create")
def adjust_entry(
    request: HttpRequest, slug: str, entity_id: UUID, entry_id: UUID, payload: AdjustIn
) -> Status[EntryOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    adjustment = corrections.adjust(
        ctx, entity_id, entry_id, _entry_input(payload), reason=payload.reason
    )
    return Status(201, entry_out(adjustment))


@router.post(f"{BASE}/periods/{{uuid:period_id}}/unlock-requests", response={201: UnlockOut})
@requires("ledger.period.unlock_request")
def request_unlock(
    request: HttpRequest, slug: str, entity_id: UUID, period_id: UUID, payload: UnlockIn
) -> Status[PeriodUnlock]:
    ctx = workspace_ctx(request, slug, entity_id)
    unlock = corrections.request_unlock(
        ctx, entity_id, period_id, reason=payload.reason, window_minutes=payload.window_minutes
    )
    return Status(201, unlock)


@router.get(f"{BASE}/unlock-requests", response=list[UnlockOut])
@requires("ledger.period.read")
def list_unlocks(request: HttpRequest, slug: str, entity_id: UUID) -> list[PeriodUnlock]:
    return corrections.list_unlocks(workspace_ctx(request, slug, entity_id), entity_id)


@router.post(f"{BASE}/unlock-requests/{{uuid:unlock_id}}/approve", response=UnlockOut)
@requires("ledger.period.unlock_approve")
def approve_unlock(
    request: HttpRequest, slug: str, entity_id: UUID, unlock_id: UUID
) -> PeriodUnlock:
    ctx = workspace_ctx(request, slug, entity_id)
    require_recent_auth(request.session, request.path)  # step-up (doc 04 §2)
    return corrections.approve_unlock(ctx, entity_id, unlock_id)


@router.post(f"{BASE}/unlock-requests/{{uuid:unlock_id}}/reject", response=UnlockOut)
@requires("ledger.period.unlock_approve")
def reject_unlock(
    request: HttpRequest, slug: str, entity_id: UUID, unlock_id: UUID, payload: UnlockDecisionIn
) -> PeriodUnlock:
    ctx = workspace_ctx(request, slug, entity_id)
    return corrections.reject_unlock(ctx, entity_id, unlock_id, payload.note)


@router.post(f"{BASE}/unlock-requests/{{uuid:unlock_id}}/close", response=UnlockOut)
@requires("ledger.period.unlock_request")
def close_unlock(request: HttpRequest, slug: str, entity_id: UUID, unlock_id: UUID) -> PeriodUnlock:
    ctx = workspace_ctx(request, slug, entity_id)
    return corrections.close_unlock(ctx, entity_id, unlock_id)
