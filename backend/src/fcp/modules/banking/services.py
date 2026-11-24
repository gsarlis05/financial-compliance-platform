"""Banking services: bank accounts, statement imports, matching and reconciliation (M2-5).

Imports: the request stores the file (size-checked, hashed) as a PENDING import; a worker parses it
(``process_pending``; ADR-0015). In development and tests, ``BANKING_PROCESS_INLINE`` processes it
at once. Parsing never touches the ledger; matching and reconciliation read it through
``ledger.api`` and new entries are drafts that follow the normal approval workflow.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from fcp.core.db.rls import set_context
from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger import api as ledger
from fcp.modules.registers.api import OpenItem, open_items
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import parsers
from .models import BankAccount, Reconciliation, StatementImport, StatementLine
from .parsers import CsvMapping, ParsedStatement, StatementFormatError

log = structlog.get_logger(__name__)
ZERO = Decimal(0)
MATCH_WINDOW = timedelta(days=7)


class DuplicateImportError(ConflictError):
    code = "banking.import.duplicate"
    title = "This file was already imported"


def _audit(
    ctx: WorkspaceContext,
    entity_id: UUID,
    action: str,
    subject_type: str,
    subject_id: object,
    changes: dict[str, Any],
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        entity_id=entity_id,
        changes=changes,
    )


def _masked_iban(iban: str) -> str:
    return f"…{iban[-4:]}" if iban else ""


# --- bank accounts --------------------------------------------------------------------------------


def _iban(raw: str) -> str:
    iban = raw.replace(" ", "").upper()
    if not iban:
        return ""
    valid = len(iban) >= 15 and iban[:2].isalpha() and iban[2:4].isdigit() and iban.isalnum()
    if valid:
        digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
        valid = int(digits) % 97 == 1
    if not valid:
        raise ValidationFailedError(
            "This IBAN is not valid (check digits).", field_errors={"iban": ["invalid"]}
        )
    return iban


def list_accounts(ctx: WorkspaceContext, entity_id: UUID) -> list[BankAccount]:
    entity = get_entity(ctx, entity_id, "banking.read")
    return list(BankAccount.objects.filter(legal_entity=entity).order_by("name"))


def get_account(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, permission: str = "banking.read"
) -> BankAccount:
    entity = get_entity(ctx, entity_id, permission)
    account = BankAccount.objects.filter(legal_entity=entity, id=account_id).first()
    if account is None:
        raise NotFoundError("Bank account not found.")
    return account


@transaction.atomic
def create_account(
    ctx: WorkspaceContext, entity_id: UUID, *, ledger_account_id: UUID, name: str, iban: str = ""
) -> BankAccount:
    entity = get_entity(ctx, entity_id, "banking.account.manage")
    target = next(
        (a for a in ledger.account_list(ctx, entity.id) if a.id == ledger_account_id), None
    )
    if (
        target is None
        or target.type != "ASSET"
        or not target.is_postable
        or target.status != "ACTIVE"
    ):
        raise ValidationFailedError(
            "Link the bank account to an active, postable asset account (for example 1300 Bank).",
            field_errors={"ledger_account_id": ["must be an active, postable asset account"]},
        )
    try:
        with transaction.atomic():
            account = BankAccount.objects.create(
                tenant=ctx.tenant,
                legal_entity=entity,
                ledger_account_id=target.id,
                name=name.strip(),
                iban=_iban(iban),
                currency=entity.functional_currency,
                created_by=ctx.user,
            )
    except IntegrityError:
        raise ConflictError(
            f"Account {target.code} already has a bank account linked to it."
        ) from None
    _audit(
        ctx,
        entity.id,
        "banking.account.created",
        "bank_account",
        account.id,
        {"name": account.name, "iban": _masked_iban(account.iban), "ledger_account": target.code},
    )
    return account


@transaction.atomic
def set_csv_mapping(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, mapping: dict[str, Any]
) -> BankAccount:
    account = get_account(ctx, entity_id, account_id, "banking.account.manage")
    _mapping_from(mapping).validate()
    account.csv_mapping = mapping
    account.save(update_fields=["csv_mapping"])
    _audit(
        ctx,
        account.legal_entity_id,
        "banking.account.csv_mapping_set",
        "bank_account",
        account.id,
        {"mapping": mapping},
    )
    return account


def _mapping_from(raw: dict[str, Any] | None) -> CsvMapping:
    if not raw:
        return parsers.DEFAULT_CSV_MAPPING
    known = {k: v for k, v in raw.items() if k in CsvMapping.__dataclass_fields__ and k != "strict"}
    return CsvMapping(**known)


def last_reconciliation(account: BankAccount) -> Reconciliation | None:
    found: Reconciliation | None = (
        Reconciliation.objects.filter(bank_account=account)
        .order_by("-as_of", "-created_at")
        .first()
    )
    return found


# --- imports --------------------------------------------------------------------------------------


@transaction.atomic
def upload(
    ctx: WorkspaceContext,
    entity_id: UUID,
    account_id: UUID,
    *,
    filename: str,
    content: bytes,
    fmt: str,
) -> StatementImport:
    account = get_account(ctx, entity_id, account_id, "banking.statement.manage")
    if fmt not in StatementImport.Format.values:
        raise ValidationFailedError("Choose CAMT053 or CSV.", field_errors={"format": ["invalid"]})
    if not content or len(content) > parsers.MAX_BYTES:
        raise StatementFormatError("The file is empty or larger than 5 MB.")
    digest = hashlib.sha256(content).hexdigest()
    earlier = (
        StatementImport.objects.filter(bank_account=account, file_sha256=digest)
        .exclude(status=StatementImport.Status.FAILED)
        .first()
    )
    if earlier is not None:
        raise DuplicateImportError(
            f"This file was already imported on {earlier.created_at.date().isoformat()}; nothing "
            "was imported again."
        )
    statement = StatementImport.objects.create(
        tenant=ctx.tenant,
        bank_account=account,
        format=fmt,
        filename=filename[:200],
        file_sha256=digest,
        content=content,
        created_by=ctx.user,
    )
    _audit(
        ctx,
        account.legal_entity_id,
        "banking.import.uploaded",
        "statement_import",
        statement.id,
        {"filename": statement.filename, "format": fmt, "sha256": digest, "bytes": len(content)},
    )
    if getattr(settings, "BANKING_PROCESS_INLINE", False):
        process(statement.id)
        statement.refresh_from_db()
    return statement


def _line_hashes(account: BankAccount, parsed: ParsedStatement) -> list[str]:
    """Stable per transaction: the same transaction in two overlapping files gets the same hash;
    two identical transactions in one file are told apart by their occurrence number."""
    seen: Counter[tuple[str, ...]] = Counter()
    hashes = []
    for ln in parsed.lines:
        key = (
            ln.booking_date.isoformat(),
            f"{ln.amount:.2f}",
            ln.bank_ref or f"{ln.description}|{ln.reference}",
        )
        seen[key] += 1
        text = "|".join((str(account.id), *key, str(seen[key])))
        hashes.append(hashlib.sha256(text.encode()).hexdigest())
    return hashes


def _parse(statement: StatementImport, account: BankAccount) -> ParsedStatement:
    data = bytes(statement.content)
    if statement.format == StatementImport.Format.CAMT053:
        parsed = parsers.parse_camt053(data)
        if account.iban and parsed.iban and parsed.iban != account.iban:
            raise StatementFormatError(
                f"The statement is for account {_masked_iban(parsed.iban)}, not "
                f"{_masked_iban(account.iban)}."
            )
        if parsed.currency != account.currency:
            raise StatementFormatError(
                f"The statement is in {parsed.currency}; the bank account is in {account.currency}."
            )
        return parsed
    parsed = parsers.parse_csv(data, _mapping_from(account.csv_mapping))
    return replace(parsed, currency=account.currency)


def process(import_id: UUID) -> None:
    """Parse one pending import and add its new lines (current RLS context; own savepoint)."""
    with transaction.atomic():
        statement = (
            StatementImport.objects.select_for_update(skip_locked=True)
            .filter(id=import_id, status=StatementImport.Status.PENDING)
            .first()
        )
        if statement is None:
            return
        account = BankAccount.objects.get(id=statement.bank_account_id)
        try:
            parsed = _parse(statement, account)
        except StatementFormatError as exc:
            statement.status, statement.error = StatementImport.Status.FAILED, exc.detail[:500]
        else:
            hashes = _line_hashes(account, parsed)
            existing = set(
                StatementLine.objects.filter(
                    bank_account=account, line_hash__in=hashes
                ).values_list("line_hash", flat=True)
            )
            new = [
                StatementLine(
                    tenant_id=statement.tenant_id,
                    bank_account=account,
                    statement_import=statement,
                    booking_date=ln.booking_date,
                    value_date=ln.value_date,
                    amount=ln.amount,
                    description=ln.description,
                    counterparty_name=ln.counterparty_name,
                    reference=ln.reference,
                    bank_ref=ln.bank_ref,
                    line_hash=h,
                )
                for ln, h in zip(parsed.lines, hashes, strict=True)
                if h not in existing
            ]
            StatementLine.objects.bulk_create(new)
            statement.status = StatementImport.Status.DONE
            statement.statement_id = parsed.statement_id[:100]
            statement.opening_balance = parsed.opening_balance
            statement.closing_balance = parsed.closing_balance
            statement.closing_date = parsed.closing_date
            statement.lines_created = len(new)
            statement.lines_duplicate = len(parsed.lines) - len(new)
        statement.processed_at = timezone.now()
        statement.save()
        audit(
            tenant_id=statement.tenant_id,
            actor_user_id=statement.created_by_id,
            action="banking.import.processed",
            subject_type="statement_import",
            subject_id=statement.id,
            entity_id=account.legal_entity_id,
            changes={
                "status": statement.status,
                "error": statement.error,
                "lines_created": statement.lines_created,
                "lines_duplicate": statement.lines_duplicate,
            },
        )
        log.info(
            "banking.import_processed",
            import_id=str(statement.id),
            status=statement.status,
            lines=statement.lines_created,
        )


def process_pending(limit: int = 50) -> int:
    """Worker: process pending imports of every workspace (oldest first). Returns how many."""
    done = 0
    with connection.cursor() as cursor:  # only workspaces with pending imports (migration 0003)
        cursor.execute("SELECT banking_pending_tenant_ids()")
        tenant_ids = [row[0] for row in cursor.fetchall()]
    for tenant_id in tenant_ids:
        with transaction.atomic():
            set_context(tenant_id=tenant_id)
            ids = list(
                StatementImport.objects.filter(status=StatementImport.Status.PENDING)
                .order_by("created_at")
                .values_list("id", flat=True)[:limit]
            )
            for import_id in ids:
                process(import_id)
                done += 1
    return done


def list_imports(ctx: WorkspaceContext, entity_id: UUID, account_id: UUID) -> list[StatementImport]:
    account = get_account(ctx, entity_id, account_id)
    return list(
        StatementImport.objects.filter(bank_account=account)
        .defer("content")
        .order_by("-created_at")
    )


def list_lines(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, *, status: str | None = None
) -> list[StatementLine]:
    account = get_account(ctx, entity_id, account_id)
    lines = StatementLine.objects.filter(bank_account=account)
    if status:
        lines = lines.filter(status=status)
    return list(lines.order_by("booking_date", "created_at"))


# --- matching -------------------------------------------------------------------------------------


def _line(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID) -> StatementLine:
    entity = get_entity(ctx, entity_id, "banking.statement.manage")
    line = (
        StatementLine.objects.select_for_update()
        .filter(id=line_id, bank_account__legal_entity=entity)
        .first()
    )
    if line is None:
        raise NotFoundError("Statement line not found.")
    return line


def _candidates(
    ctx: WorkspaceContext, account: BankAccount, start: date, end: date
) -> list[ledger.PostedLine]:
    taken = set(
        StatementLine.objects.filter(bank_account=account, matched_line__isnull=False).values_list(
            "matched_line_id", flat=True
        )
    )
    posted = ledger.posted_lines(
        ctx,
        account.legal_entity_id,
        account.ledger_account_id,
        date_from=start - MATCH_WINDOW,
        date_to=end + MATCH_WINDOW,
    )
    return [p for p in posted if p.line_id not in taken]


def _refers(line: StatementLine, posted: ledger.PostedLine) -> bool:
    keys = [k.lower() for k in (line.reference, line.bank_ref) if len(k) >= 3]
    text = f"{posted.reference} {posted.memo} {posted.description}".lower()
    return any(k in text for k in keys)


def _set_match(
    ctx: WorkspaceContext, line: StatementLine, line_id: UUID | None, status: str, note: str = ""
) -> None:
    line.matched_line_id, line.status, line.note = line_id, status, note
    line.updated_by = ctx.user
    line.save(update_fields=["matched_line", "status", "note", "updated_by"])


@transaction.atomic
def auto_match(ctx: WorkspaceContext, entity_id: UUID, account_id: UUID) -> int:
    """Match unmatched lines to posted ledger lines of the same amount within 7 days, when the
    reference agrees or exactly one candidate exists (never a guess between equal amounts)."""
    account = get_account(ctx, entity_id, account_id, "banking.statement.manage")
    lines = list(
        StatementLine.objects.select_for_update()
        .filter(bank_account=account, status=StatementLine.Status.UNMATCHED)
        .order_by("booking_date")
    )
    if not lines:
        return 0
    pool = _candidates(ctx, account, lines[0].booking_date, lines[-1].booking_date)
    matched = 0
    for line in lines:
        near = [
            p
            for p in pool
            if p.net_debit == line.amount
            and abs(p.accounting_date - line.booking_date) <= MATCH_WINDOW
        ]
        referred = [p for p in near if _refers(line, p)]
        choice = referred[0] if referred else (near[0] if len(near) == 1 else None)
        if choice is None:
            continue
        pool.remove(choice)
        _set_match(ctx, line, choice.line_id, StatementLine.Status.MATCHED)
        matched += 1
    _audit(
        ctx,
        account.legal_entity_id,
        "banking.lines.auto_matched",
        "bank_account",
        account.id,
        {"matched": matched},
    )
    return matched


def candidates(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID) -> list[ledger.PostedLine]:
    """Posted ledger lines a statement line could be matched to (same amount, within 7 days)."""
    with transaction.atomic():
        line = _line(ctx, entity_id, line_id)
        account = BankAccount.objects.get(id=line.bank_account_id)
        pool = _candidates(ctx, account, line.booking_date, line.booking_date)
    return [p for p in pool if p.net_debit == line.amount]


@transaction.atomic
def match(
    ctx: WorkspaceContext, entity_id: UUID, line_id: UUID, journal_line_id: UUID
) -> StatementLine:
    line = _line(ctx, entity_id, line_id)
    if line.status != StatementLine.Status.UNMATCHED:
        raise ConflictError("Unmatch or un-ignore this line first.")
    account = BankAccount.objects.get(id=line.bank_account_id)
    choice = next(
        (
            p
            for p in _candidates(ctx, account, line.booking_date, line.booking_date)
            if p.line_id == journal_line_id
        ),
        None,
    )
    if choice is None or choice.net_debit != line.amount:
        raise ValidationFailedError(
            "Choose a posted line on the bank's ledger account, with the same amount, within 7 "
            "days, that is not matched yet.",
            field_errors={"journal_line_id": ["not a candidate"]},
        )
    _set_match(ctx, line, choice.line_id, StatementLine.Status.MATCHED)
    _audit(
        ctx,
        account.legal_entity_id,
        "banking.line.matched",
        "statement_line",
        line.id,
        {"journal_line_id": choice.line_id, "entry": choice.entry_ref},
    )
    return line


@transaction.atomic
def unmatch(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID) -> StatementLine:
    line = _line(ctx, entity_id, line_id)
    before = (line.status, line.matched_line_id)
    _set_match(ctx, line, None, StatementLine.Status.UNMATCHED)
    _audit(
        ctx,
        entity_id,
        "banking.line.unmatched",
        "statement_line",
        line.id,
        {"before": {"status": before[0], "journal_line_id": before[1]}},
    )
    return line


@transaction.atomic
def ignore(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID, note: str) -> StatementLine:
    line = _line(ctx, entity_id, line_id)
    if line.status != StatementLine.Status.UNMATCHED:
        raise ConflictError("Only unmatched lines can be ignored.")
    if len(note.strip()) < 5:
        raise ValidationFailedError(
            "Explain why the line is ignored (at least 5 characters).",
            field_errors={"note": ["required"]},
        )
    _set_match(ctx, line, None, StatementLine.Status.IGNORED, note.strip()[:500])
    _audit(ctx, entity_id, "banking.line.ignored", "statement_line", line.id, {"note": line.note})
    return line


@dataclass(frozen=True)
class Suggestion:
    """An open invoice the payment probably settles (same open amount; reference first)."""

    item: OpenItem
    reference_matches: bool


def suggestions(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID) -> list[Suggestion]:
    line = _line(ctx, entity_id, line_id)
    side = "RECEIVABLE" if line.amount > 0 else "PAYABLE"
    items = open_items(ctx, entity_id, as_of=line.booking_date, side=side)
    found = [
        Suggestion(i, bool(line.reference) and i.reference.lower() == line.reference.lower())
        for i in items
        if i.kind == "INVOICE" and i.open_amount == abs(line.amount) and not i.disputed
    ]
    return sorted(found, key=lambda s: (not s.reference_matches, s.item.due_date))[:10]


@dataclass(frozen=True)
class Booking:
    """How to book an unmatched statement line: the other account (and the customer or supplier
    on control accounts), with an optional reference and description."""

    account_id: UUID
    counterparty_id: UUID | None = None
    reference: str = ""
    description: str = ""


@transaction.atomic
def create_entry(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID, booking: Booking) -> Any:
    """Book an unmatched line: a draft entry between the bank's ledger account and the chosen
    account (with the customer or supplier on control accounts). Once it is posted, automatic
    matching links it (same amount, same reference)."""
    line = _line(ctx, entity_id, line_id)
    if line.status != StatementLine.Status.UNMATCHED:
        raise ConflictError("This line is already matched or ignored.")
    bank = BankAccount.objects.get(id=line.bank_account_id)
    ref = (booking.reference or line.reference or line.bank_ref)[:50]
    amount = f"{abs(line.amount):.2f}"
    money_in = line.amount > 0
    data = ledger.EntryInput(
        accounting_date=line.booking_date,
        description=(booking.description or line.description or "Bank transaction")[:500],
        lines=[
            ledger.LineInput(
                bank.ledger_account_id,
                debit=amount if money_in else "0",
                credit="0" if money_in else amount,
                memo=f"Bank: {bank.name}"[:300],
                reference=ref,
            ),
            ledger.LineInput(
                booking.account_id,
                debit="0" if money_in else amount,
                credit=amount if money_in else "0",
                counterparty_id=booking.counterparty_id,
                reference=ref,
            ),
        ],
    )
    entry = ledger.create_entry_draft(ctx, entity_id, data)
    _audit(
        ctx,
        entity_id,
        "banking.line.entry_created",
        "statement_line",
        line.id,
        {"entry_id": entry.id},
    )
    return entry


# --- reconciliation -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconciliationResult:
    as_of: date
    statement_balance: Decimal
    ledger_balance: Decimal
    unmatched_lines: int
    reconciliation: Reconciliation | None

    @property
    def difference(self) -> Decimal:
        return self.ledger_balance - self.statement_balance

    @property
    def reconciled(self) -> bool:
        return self.reconciliation is not None


@transaction.atomic
def reconcile(
    ctx: WorkspaceContext,
    entity_id: UUID,
    account_id: UUID,
    *,
    as_of: date,
    statement_balance: Decimal | None = None,
) -> ReconciliationResult:
    """Reconciled when the ledger balance of the bank's ledger account at ``as_of`` equals the
    statement balance at that date (AC-M2-5). The statement balance is the closing balance of an
    import ending that day, unless given. Unmatched lines are reported, not blocking: matching is
    the tool for finding a difference, the balances are the proof."""
    account = get_account(ctx, entity_id, account_id, "banking.reconcile")
    if statement_balance is None:
        source = (
            StatementImport.objects.filter(
                bank_account=account,
                status=StatementImport.Status.DONE,
                closing_date=as_of,
                closing_balance__isnull=False,
            )
            .order_by("-created_at")
            .first()
        )
        if source is None or source.closing_balance is None:
            raise ValidationFailedError(
                "No imported statement closes on this date. Enter the statement balance.",
                field_errors={"statement_balance": ["required"]},
            )
        statement_balance = source.closing_balance
    balance = ledger.account_balance(ctx, entity_id, account.ledger_account_id, as_of=as_of)
    unmatched = StatementLine.objects.filter(
        bank_account=account, status=StatementLine.Status.UNMATCHED, booking_date__lte=as_of
    ).count()
    record = None
    if balance == statement_balance:
        record = Reconciliation.objects.create(
            tenant=ctx.tenant,
            bank_account=account,
            as_of=as_of,
            statement_balance=statement_balance,
            ledger_balance=balance,
            unmatched_lines=unmatched,
            created_by=ctx.user,
        )
        _audit(
            ctx,
            account.legal_entity_id,
            "banking.reconciled",
            "bank_account",
            account.id,
            {"as_of": as_of, "unmatched_lines": unmatched},
        )
    return ReconciliationResult(as_of, statement_balance, balance, unmatched, record)
