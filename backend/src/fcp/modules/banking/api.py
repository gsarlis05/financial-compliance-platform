"""Public interface of the ``banking`` module and its HTTP routes (M2-5).

Bank accounts, statement imports (CAMT.053 and CSV), matching to ledger lines and reconciliation.
Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, File, Form, Query, Router, Schema, Status
from ninja.files import UploadedFile

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import WorkspaceContext, workspace_ctx

from . import services
from .models import BankAccount, Reconciliation, StatementImport, StatementLine
from .parsers import DATE_FORMATS, ENCODINGS, MAX_BYTES

__all__: list[str] = ["BankAccountStatus", "reconciliation_status", "router"]


@dataclass(frozen=True)
class BankAccountStatus:
    """A bank account's ledger account and the date it was last reconciled (for forecasts)."""

    name: str
    ledger_account_id: UUID
    last_reconciled: date | None


def reconciliation_status(ctx: WorkspaceContext, entity_id: UUID) -> list[BankAccountStatus]:
    """Active bank accounts with their last reconciliation date (requires ``banking.read``)."""
    result = []
    for account in services.list_accounts(ctx, entity_id):
        if account.status != BankAccount.Status.ACTIVE:
            continue
        last = services.last_reconciliation(account)
        result.append(BankAccountStatus(account.name, account.ledger_account_id,
                                        last.as_of if last else None))  # fmt: skip
    return result


router = Router(tags=["banking"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
AMOUNT = r"^-?\d{1,15}(\.\d{1,2})?$"


class ReconciliationOut(Schema):
    as_of: date
    statement_balance: str
    ledger_balance: str
    difference: str
    unmatched_lines: int
    reconciled: bool


class BankAccountOut(Schema):
    id: UUID
    name: str
    iban: str
    currency: str
    ledger_account_id: UUID
    status: str
    csv_mapping: dict[str, object] | None
    last_reconciled: ReconciliationOut | None
    unmatched_lines: int


def _recon_out(r: Reconciliation) -> ReconciliationOut:
    return ReconciliationOut(
        as_of=r.as_of,
        statement_balance=f"{r.statement_balance:.2f}",
        ledger_balance=f"{r.ledger_balance:.2f}",
        difference="0.00",
        unmatched_lines=r.unmatched_lines,
        reconciled=True,
    )


def _account_out(a: BankAccount) -> BankAccountOut:
    last = services.last_reconciliation(a)
    unmatched = StatementLine.objects.filter(
        bank_account=a, status=StatementLine.Status.UNMATCHED
    ).count()
    return BankAccountOut(
        id=a.id,
        name=a.name,
        iban=a.iban,
        currency=a.currency,
        ledger_account_id=a.ledger_account_id,
        status=a.status,
        csv_mapping=a.csv_mapping,
        last_reconciled=_recon_out(last) if last else None,
        unmatched_lines=unmatched,
    )


@router.get(f"{BASE}/bank-accounts", response=list[BankAccountOut])
@requires("banking.read")
def bank_accounts(request: HttpRequest, slug: str, entity_id: UUID) -> list[BankAccountOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_account_out(a) for a in services.list_accounts(ctx, entity_id)]


class BankAccountIn(Schema):
    ledger_account_id: UUID
    name: str = Field(min_length=1, max_length=100)
    iban: str = Field(default="", max_length=42)


@router.post(f"{BASE}/bank-accounts", response={201: BankAccountOut})
@requires("banking.account.manage")
def create_bank_account(
    request: HttpRequest, slug: str, entity_id: UUID, payload: BankAccountIn
) -> Status[BankAccountOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    account = services.create_account(
        ctx,
        entity_id,
        ledger_account_id=payload.ledger_account_id,
        name=payload.name,
        iban=payload.iban,
    )
    return Status(201, _account_out(account))


class CsvMappingIn(Schema):
    date: str = Field(min_length=1, max_length=60)
    amount: str = Field(default="", max_length=60)
    debit: str = Field(default="", max_length=60)
    credit: str = Field(default="", max_length=60)
    description: str = Field(default="", max_length=60)
    reference: str = Field(default="", max_length=60)
    counterparty: str = Field(default="", max_length=60)
    balance: str = Field(default="", max_length=60)
    date_format: str = Field(default="%Y-%m-%d", description=f"One of {', '.join(DATE_FORMATS)}")
    delimiter: Literal[",", ";", "\t", "|"] = ","
    decimal_comma: bool = False
    has_header: bool = True
    encoding: str = Field(default="utf-8-sig", description=f"One of {', '.join(ENCODINGS)}")


@router.put(f"{BASE}/bank-accounts/{{uuid:account_id}}/csv-mapping", response=BankAccountOut)
@requires("banking.account.manage")
def set_csv_mapping(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, payload: CsvMappingIn
) -> BankAccountOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _account_out(services.set_csv_mapping(ctx, entity_id, account_id, payload.dict()))


class ImportOut(Schema):
    id: UUID
    format: str
    filename: str
    status: str
    error: str
    statement_id: str
    opening_balance: str | None
    closing_balance: str | None
    closing_date: date | None
    lines_created: int
    lines_duplicate: int
    created_at: datetime
    processed_at: datetime | None


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _import_out(i: StatementImport) -> ImportOut:
    return ImportOut(
        id=i.id,
        format=i.format,
        filename=i.filename,
        status=i.status,
        error=i.error,
        statement_id=i.statement_id,
        opening_balance=_money(i.opening_balance),
        closing_balance=_money(i.closing_balance),
        closing_date=i.closing_date,
        lines_created=i.lines_created,
        lines_duplicate=i.lines_duplicate,
        created_at=i.created_at,
        processed_at=i.processed_at,
    )


@router.post(f"{BASE}/bank-accounts/{{uuid:account_id}}/imports", response={201: ImportOut})
@requires("banking.statement.manage")
def upload_statement(
    request: HttpRequest,
    slug: str,
    entity_id: UUID,
    account_id: UUID,
    file: File[UploadedFile],
    format: Form[Literal["CAMT053", "CSV"]],
) -> Status[ImportOut]:
    """Upload a statement (at most 5 MB). It is parsed by the import worker; the same file is
    refused a second time (409 ``banking.import.duplicate``)."""
    ctx = workspace_ctx(request, slug, entity_id)
    content = file.read(MAX_BYTES + 1)
    statement = services.upload(
        ctx, entity_id, account_id, filename=file.name or "statement", content=content, fmt=format
    )
    return Status(201, _import_out(statement))


@router.get(f"{BASE}/bank-accounts/{{uuid:account_id}}/imports", response=list[ImportOut])
@requires("banking.read")
def statement_imports(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID
) -> list[ImportOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_import_out(i) for i in services.list_imports(ctx, entity_id, account_id)]


class LineOut(Schema):
    id: UUID
    booking_date: date
    value_date: date | None
    amount: str
    description: str
    counterparty_name: str
    reference: str
    bank_ref: str
    status: str
    matched_line_id: UUID | None
    note: str


def _line_out(ln: StatementLine) -> LineOut:
    return LineOut(
        id=ln.id,
        booking_date=ln.booking_date,
        value_date=ln.value_date,
        amount=f"{ln.amount:.2f}",
        description=ln.description,
        counterparty_name=ln.counterparty_name,
        reference=ln.reference,
        bank_ref=ln.bank_ref,
        status=ln.status,
        matched_line_id=ln.matched_line_id,
        note=ln.note,
    )


class LinesQuery(Schema):
    status: Literal["UNMATCHED", "MATCHED", "IGNORED"] | None = None


@router.get(f"{BASE}/bank-accounts/{{uuid:account_id}}/lines", response=list[LineOut])
@requires("banking.read")
def statement_lines(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, q: Query[LinesQuery]
) -> list[LineOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        _line_out(ln) for ln in services.list_lines(ctx, entity_id, account_id, status=q.status)
    ]


class MatchedOut(Schema):
    matched: int


@router.post(f"{BASE}/bank-accounts/{{uuid:account_id}}/auto-match", response=MatchedOut)
@requires("banking.statement.manage")
def auto_match(request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID) -> MatchedOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return MatchedOut(matched=services.auto_match(ctx, entity_id, account_id))


LINE = f"{BASE}/statement-lines/{{uuid:line_id}}"


class CandidateOut(Schema):
    journal_line_id: UUID
    entry_id: UUID
    entry_ref: str
    accounting_date: date
    amount: str
    reference: str
    description: str


@router.get(f"{LINE}/candidates", response=list[CandidateOut])
@requires("banking.statement.manage")
def match_candidates(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID
) -> list[CandidateOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        CandidateOut(
            journal_line_id=p.line_id,
            entry_id=p.entry_id,
            entry_ref=p.entry_ref,
            accounting_date=p.accounting_date,
            amount=f"{p.net_debit:.2f}",
            reference=p.reference,
            description=p.description,
        )
        for p in services.candidates(ctx, entity_id, line_id)
    ]


class MatchIn(Schema):
    journal_line_id: UUID


@router.post(f"{LINE}/match", response=LineOut)
@requires("banking.statement.manage")
def match_line(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID, payload: MatchIn
) -> LineOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _line_out(services.match(ctx, entity_id, line_id, payload.journal_line_id))


@router.post(f"{LINE}/unmatch", response=LineOut)
@requires("banking.statement.manage")
def unmatch_line(request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID) -> LineOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _line_out(services.unmatch(ctx, entity_id, line_id))


class IgnoreIn(Schema):
    note: str = Field(min_length=1, max_length=500)


@router.post(f"{LINE}/ignore", response=LineOut)
@requires("banking.statement.manage")
def ignore_line(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID, payload: IgnoreIn
) -> LineOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _line_out(services.ignore(ctx, entity_id, line_id, payload.note))


class SuggestionOut(Schema):
    counterparty_id: UUID
    counterparty_code: str
    account_code: str
    reference: str
    due_date: date
    open_amount: str
    reference_matches: bool


@router.get(f"{LINE}/suggestions", response=list[SuggestionOut])
@requires("banking.statement.manage")
def line_suggestions(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID
) -> list[SuggestionOut]:
    """Open invoices this payment probably settles (same open amount; matching reference first)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        SuggestionOut(
            counterparty_id=s.item.counterparty_id,
            counterparty_code=s.item.counterparty_code,
            account_code=s.item.account_code,
            reference=s.item.reference,
            due_date=s.item.due_date,
            open_amount=f"{s.item.open_amount:.2f}",
            reference_matches=s.reference_matches,
        )
        for s in services.suggestions(ctx, entity_id, line_id)
    ]


class CreateEntryIn(Schema):
    account_id: UUID
    counterparty_id: UUID | None = None
    reference: str = Field(default="", max_length=50)
    description: str = Field(default="", max_length=500)


class CreatedEntryOut(Schema):
    entry_id: UUID
    status: str


@router.post(f"{LINE}/create-entry", response={201: CreatedEntryOut})
@requires("banking.statement.manage")
def create_entry(
    request: HttpRequest, slug: str, entity_id: UUID, line_id: UUID, payload: CreateEntryIn
) -> Status[CreatedEntryOut]:
    """A draft entry for an unmatched line (normal approval workflow; matched once posted)."""
    ctx = workspace_ctx(request, slug, entity_id)
    booking = services.Booking(
        account_id=payload.account_id,
        counterparty_id=payload.counterparty_id,
        reference=payload.reference,
        description=payload.description,
    )
    entry = services.create_entry(ctx, entity_id, line_id, booking)
    return Status(201, CreatedEntryOut(entry_id=entry.id, status=entry.status))


class ReconcileIn(Schema):
    as_of: date
    statement_balance: str | None = Field(default=None, pattern=AMOUNT)


@router.post(f"{BASE}/bank-accounts/{{uuid:account_id}}/reconcile", response=ReconciliationOut)
@requires("banking.reconcile")
def reconcile(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, payload: ReconcileIn
) -> ReconciliationOut:
    """Reconciled (and recorded) only when the ledger balance equals the statement balance."""
    ctx = workspace_ctx(request, slug, entity_id)
    balance = Decimal(payload.statement_balance) if payload.statement_balance else None
    result = services.reconcile(
        ctx, entity_id, account_id, as_of=payload.as_of, statement_balance=balance
    )
    return ReconciliationOut(
        as_of=result.as_of,
        statement_balance=f"{result.statement_balance:.2f}",
        ledger_balance=f"{result.ledger_balance:.2f}",
        difference=f"{result.difference:.2f}",
        unmatched_lines=result.unmatched_lines,
        reconciled=result.reconciled,
    )


@router.get(
    f"{BASE}/bank-accounts/{{uuid:account_id}}/reconciliations", response=list[ReconciliationOut]
)
@requires("banking.read")
def reconciliations(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID
) -> list[ReconciliationOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    account = services.get_account(ctx, entity_id, account_id)
    return [
        _recon_out(r)
        for r in Reconciliation.objects.filter(bank_account=account).order_by(
            "-as_of", "-created_at"
        )
    ]
