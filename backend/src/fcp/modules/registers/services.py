"""Customers, suppliers, open items, allocations and ageing (backlog M2-2, AC-M2-2).

Open items are the posted lines on control accounts. On a RECEIVABLE account a debit line is an
invoice and a credit line a payment or credit note; on a PAYABLE account it is the reverse. A line's
open amount at a date is its amount minus the allocations effective by that date. Because every
control-account line is an open item, the open items always add up to the control balance.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import DatabaseError, transaction

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger.api import JournalLine
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Allocation, Counterparty, OpenItemFlag

ZERO = Decimal(0)
RECEIVABLE, PAYABLE = "RECEIVABLE", "PAYABLE"
BUCKETS = ("current", "1_30", "31_60", "61_90", "over_90")
_SENSITIVE = ("name", "vat_no", "email")


class AllocationError(ConflictError):
    code = "registers.allocation.invalid"
    title = "These items cannot be matched"


def _audit(ctx: WorkspaceContext, subject_type: str, subject_id: object, entity_id: UUID,
           action: str, changes: dict[str, Any]) -> None:  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=action,
          subject_type=subject_type, subject_id=subject_id, entity_id=entity_id,
          changes=changes, sensitive=[k for k in _SENSITIVE if k in changes])  # fmt: skip


# --- counterparties -------------------------------------------------------------------------------


@dataclass(frozen=True)
class CounterpartyInput:
    code: str
    name: str
    kind: str
    vat_no: str = ""
    email: str = ""
    payment_terms_days: int = 30


def list_counterparties(
    ctx: WorkspaceContext, entity_id: UUID, *, kind: str | None = None, status: str | None = None
) -> list[Counterparty]:
    entity = get_entity(ctx, entity_id, "registers.counterparty.read")
    qs = Counterparty.objects.filter(legal_entity=entity)
    if kind:
        qs = qs.filter(kind__in=[kind, Counterparty.Kind.BOTH])
    if status:
        qs = qs.filter(status=status)
    return list(qs.order_by("code"))


def get_counterparty(ctx: WorkspaceContext, entity_id: UUID, counterparty_id: UUID) -> Counterparty:
    entity = get_entity(ctx, entity_id, "registers.counterparty.read")
    found: Counterparty | None = Counterparty.objects.filter(
        legal_entity=entity, id=counterparty_id
    ).first()
    if found is None:
        raise NotFoundError("Customer or supplier not found.")
    return found


def _code(value: str) -> str:
    code = value.strip().upper()
    if not code or len(code) > 30 or not all(c.isalnum() or c in ".-_" for c in code):
        raise ValidationFailedError(
            "Codes use letters, digits, '.', '-' and '_' (up to 30 characters).",
            field_errors={"code": ["invalid format"]},
        )
    return code


@transaction.atomic
def create_counterparty(
    ctx: WorkspaceContext, entity_id: UUID, data: CounterpartyInput
) -> Counterparty:
    entity = get_entity(ctx, entity_id, "registers.counterparty.manage")
    code = _code(data.code)
    if data.kind not in Counterparty.Kind.values:
        raise ValidationFailedError("Unknown kind.", field_errors={"kind": ["invalid"]})
    if Counterparty.objects.filter(legal_entity=entity, code=code).exists():
        raise ConflictError(f"Code {code} is already used by another customer or supplier.")
    counterparty = Counterparty.objects.create(
        tenant=ctx.tenant, legal_entity=entity, code=code, name=data.name.strip(), kind=data.kind,
        vat_no=data.vat_no.strip().upper(), email=data.email.strip().lower(),
        payment_terms_days=data.payment_terms_days, created_by=ctx.user,
    )  # fmt: skip
    _audit(ctx, "counterparty", counterparty.id, entity.id, "registers.counterparty.created",
           {"code": code, "kind": data.kind, "name": counterparty.name,
            "vat_no": counterparty.vat_no, "email": counterparty.email,
            "payment_terms_days": data.payment_terms_days})  # fmt: skip
    return counterparty


_EDITABLE = ("name", "vat_no", "email", "payment_terms_days", "status")


@transaction.atomic
def update_counterparty(
    ctx: WorkspaceContext, entity_id: UUID, counterparty_id: UUID, changes: dict[str, Any]
) -> Counterparty:
    """Code and kind never change (postings refer to them); the rest can."""
    get_entity(ctx, entity_id, "registers.counterparty.manage")
    counterparty = get_counterparty(ctx, entity_id, counterparty_id)
    if "status" in changes and changes["status"] not in Counterparty.Status.values:
        raise ValidationFailedError("Unknown status.", field_errors={"status": ["invalid"]})
    before = {k: getattr(counterparty, k) for k in _EDITABLE}
    for key in _EDITABLE:
        if key in changes and changes[key] is not None:
            value = changes[key]
            if isinstance(value, str):
                value = value.strip()
                value = value.upper() if key == "vat_no" else value
                value = value.lower() if key == "email" else value
            setattr(counterparty, key, value)
    counterparty.save(update_fields=list(_EDITABLE))
    after = {k: getattr(counterparty, k) for k in _EDITABLE}
    diff = {k: after[k] for k in _EDITABLE if after[k] != before[k]}
    if diff:
        _audit(ctx, "counterparty", counterparty.id, counterparty.legal_entity_id,
               "registers.counterparty.updated", {"code": counterparty.code, **diff})  # fmt: skip
    return counterparty


# --- open items -----------------------------------------------------------------------------------


@dataclass
class OpenItem:
    line_id: UUID
    entry_id: UUID
    entry_ref: str
    side: str  # RECEIVABLE | PAYABLE
    kind: str  # INVOICE | PAYMENT
    account_code: str
    counterparty_id: UUID
    counterparty_code: str
    accounting_date: date
    due_date: date
    reference: str
    description: str
    amount: Decimal
    allocated: Decimal
    disputed: bool = False
    note: str = ""

    @property
    def open_amount(self) -> Decimal:
        return self.amount - self.allocated

    @property
    def status(self) -> str:
        if self.open_amount == ZERO:
            return "SETTLED"
        return "PARTIAL" if self.allocated else "OPEN"

    def days_overdue(self, as_of: date) -> int:
        return (as_of - self.due_date).days


def _control_lines(entity_id: UUID, as_of: date, counterparty_id: UUID | None,
                   side: str | None) -> Iterable[JournalLine]:  # fmt: skip
    qs = JournalLine.objects.select_related("entry", "entry__journal", "account", "counterparty")
    qs = qs.filter(
        entry__legal_entity_id=entity_id,
        entry__status="POSTED",
        entry__accounting_date__lte=as_of,
        account__control_type__in=[side] if side else [RECEIVABLE, PAYABLE],
    )
    if counterparty_id:
        qs = qs.filter(counterparty_id=counterparty_id)
    return qs.order_by("entry__accounting_date", "entry__posting_seq", "line_no")


def open_items(
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    as_of: date,
    counterparty_id: UUID | None = None,
    side: str | None = None,
    include_settled: bool = False,
) -> list[OpenItem]:
    get_entity(ctx, entity_id, "registers.counterparty.read")
    lines = list(_control_lines(entity_id, as_of, counterparty_id, side))
    ids = [ln.id for ln in lines]
    allocated: dict[UUID, Decimal] = defaultdict(lambda: ZERO)
    for a in Allocation.objects.filter(legal_entity_id=entity_id, allocated_on__lte=as_of).filter(
        debit_line_id__in=ids
    ) | Allocation.objects.filter(legal_entity_id=entity_id, allocated_on__lte=as_of).filter(
        credit_line_id__in=ids
    ):
        allocated[a.debit_line_id] += a.amount
        allocated[a.credit_line_id] += a.amount
    flags = {f.line_id: f for f in OpenItemFlag.objects.filter(line_id__in=ids)}
    items = []
    for ln in lines:
        control = ln.account.control_type
        is_debit = ln.debit > 0
        invoice = is_debit if control == RECEIVABLE else not is_debit
        counterparty = ln.counterparty
        if counterparty is None:  # impossible after posting (ledger migration 0012)
            continue
        terms = timedelta(days=counterparty.payment_terms_days)
        document_date = ln.entry.document_date or ln.entry.accounting_date
        item = OpenItem(
            line_id=ln.id,
            entry_id=ln.entry_id,
            entry_ref=f"{ln.entry.journal.code}-{ln.entry.entry_no}",
            side=control,
            kind="INVOICE" if invoice else "PAYMENT",
            account_code=ln.account.code,
            counterparty_id=counterparty.id,
            counterparty_code=counterparty.code,
            accounting_date=ln.entry.accounting_date,
            due_date=ln.due_date
            or (document_date + terms if invoice else ln.entry.accounting_date),
            reference=ln.reference,
            description=ln.memo or ln.entry.description,
            amount=ln.debit if is_debit else ln.credit,
            allocated=allocated[ln.id],
        )
        flag = flags.get(ln.id)
        if flag:
            item.disputed, item.note = flag.disputed, flag.note
        if include_settled or item.open_amount:
            items.append(item)
    return items


# --- allocation -----------------------------------------------------------------------------------


def _line(entity_id: UUID, line_id: UUID) -> JournalLine:
    found: JournalLine | None = (
        JournalLine.objects.select_related("entry", "account")
        .filter(id=line_id, entry__legal_entity_id=entity_id)
        .first()
    )
    if found is None:
        raise NotFoundError("Open item not found.")
    return found


@transaction.atomic
def allocate(
    ctx: WorkspaceContext, entity_id: UUID, *, invoice_line_id: UUID, payment_line_id: UUID,
    amount: Decimal,
) -> Allocation:  # fmt: skip
    """Settle (part of) an invoice with a payment or credit note of the same counterparty."""
    entity = get_entity(ctx, entity_id, "registers.allocation.manage")
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise ValidationFailedError(
            "The amount must be positive, in whole cents.", field_errors={"amount": ["invalid"]}
        )
    invoice = _line(entity.id, invoice_line_id)
    payment = _line(entity.id, payment_line_id)
    control = invoice.account.control_type
    if not control or invoice.account_id != payment.account_id:
        raise AllocationError("Both items must be on the same control account.")
    invoice_is_debit = control == RECEIVABLE
    if (invoice.debit > 0) != invoice_is_debit or (payment.debit > 0) == invoice_is_debit:
        raise AllocationError("Choose an invoice and a payment or credit note (one of each).")
    if invoice.counterparty_id != payment.counterparty_id:
        raise AllocationError("The invoice and the payment belong to different counterparties.")
    debit, credit = (invoice, payment) if invoice_is_debit else (payment, invoice)
    try:
        with transaction.atomic():
            allocation = Allocation.objects.create(
                tenant=ctx.tenant, legal_entity=entity, debit_line=debit, credit_line=credit,
                amount=amount, allocated_on=max(debit.entry.accounting_date,
                                                credit.entry.accounting_date),
                created_by=ctx.user,
            )  # fmt: skip
    except DatabaseError as error:  # the guard trigger (posted lines, totals, same party)
        message = str(error).splitlines()[0]
        if "exceeds" in message:
            raise AllocationError(
                "The amount is more than is still open on the invoice or the payment."
            ) from None
        if "unique" in message or "duplicate" in message:
            raise AllocationError(
                "These two items are already matched; remove that match first."
            ) from None
        raise AllocationError(f"The database refused the match: {message}") from None
    _audit(ctx, "allocation", allocation.id, entity.id, "registers.allocation.created",
           {"debit_line_id": debit.id, "credit_line_id": credit.id, "amount": f"{amount:.2f}",
            "allocated_on": allocation.allocated_on})  # fmt: skip
    return allocation


@transaction.atomic
def unallocate(ctx: WorkspaceContext, entity_id: UUID, allocation_id: UUID) -> None:
    entity = get_entity(ctx, entity_id, "registers.allocation.manage")
    allocation: Allocation | None = Allocation.objects.filter(
        legal_entity=entity, id=allocation_id
    ).first()
    if allocation is None:
        raise NotFoundError("Match not found.")
    _audit(ctx, "allocation", allocation.id, entity.id, "registers.allocation.deleted",
           {"debit_line_id": allocation.debit_line_id,
            "credit_line_id": allocation.credit_line_id,
            "amount": f"{allocation.amount:.2f}"})  # fmt: skip
    allocation.delete()


def list_allocations(ctx: WorkspaceContext, entity_id: UUID, line_id: UUID) -> list[Allocation]:
    entity = get_entity(ctx, entity_id, "registers.counterparty.read")
    return list(
        (
            Allocation.objects.filter(legal_entity=entity, debit_line_id=line_id)
            | Allocation.objects.filter(legal_entity=entity, credit_line_id=line_id)
        ).order_by("allocated_on", "created_at")
    )


@transaction.atomic
def auto_allocate(
    ctx: WorkspaceContext, entity_id: UUID, counterparty_id: UUID, *, as_of: date
) -> list[Allocation]:
    """Match open payments to open invoices of one counterparty: same reference first, then the
    oldest invoices first (by due date). Disputed invoices are skipped."""
    get_entity(ctx, entity_id, "registers.allocation.manage")
    get_counterparty(ctx, entity_id, counterparty_id)
    items = open_items(ctx, entity_id, as_of=as_of, counterparty_id=counterparty_id)
    created: list[Allocation] = []
    by_account: dict[str, list[OpenItem]] = defaultdict(list)
    for item in items:
        by_account[item.account_code].append(item)
    for group in by_account.values():
        invoices = sorted(
            (i for i in group if i.kind == "INVOICE" and not i.disputed),
            key=lambda i: (i.due_date, i.accounting_date),
        )
        payments = sorted((i for i in group if i.kind == "PAYMENT"),
                          key=lambda i: i.accounting_date)  # fmt: skip
        open_amount = {i.line_id: i.open_amount for i in invoices + payments}
        pairs = [(inv, pay) for pay in payments for inv in invoices
                 if pay.reference and inv.reference == pay.reference]  # fmt: skip
        pairs += [(inv, pay) for pay in payments for inv in invoices]  # then oldest first
        for invoice, payment in pairs:
            amount = min(open_amount[invoice.line_id], open_amount[payment.line_id])
            if amount > 0:
                created.append(
                    allocate(
                        ctx,
                        entity_id,
                        invoice_line_id=invoice.line_id,
                        payment_line_id=payment.line_id,
                        amount=amount,
                    )
                )
                open_amount[invoice.line_id] -= amount
                open_amount[payment.line_id] -= amount
    return created


@transaction.atomic
def set_flag(
    ctx: WorkspaceContext, entity_id: UUID, line_id: UUID, *, disputed: bool, note: str
) -> OpenItemFlag:
    entity = get_entity(ctx, entity_id, "registers.allocation.manage")
    line = _line(entity.id, line_id)
    if not line.account.control_type or line.entry.status != "POSTED":
        raise NotFoundError("Open item not found.")
    flag, _ = OpenItemFlag.objects.update_or_create(
        line=line,
        defaults={"tenant": ctx.tenant, "disputed": disputed, "note": note.strip(),
                  "updated_by": ctx.user},
    )  # fmt: skip
    _audit(ctx, "open_item", line.id, entity.id, "registers.open_item.flagged",
           {"disputed": disputed, "note": flag.note})  # fmt: skip
    return flag


# --- ageing ---------------------------------------------------------------------------------------


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "over_90"


@dataclass
class AgeingRow:
    counterparty_id: UUID
    counterparty_code: str
    counterparty_name: str
    buckets: dict[str, Decimal] = field(default_factory=lambda: dict.fromkeys(BUCKETS, ZERO))
    unapplied: Decimal = ZERO  # open payments and credit notes not yet matched

    @property
    def total(self) -> Decimal:
        return sum(self.buckets.values(), ZERO) - self.unapplied


@dataclass
class Ageing:
    as_of: date
    side: str
    rows: list[AgeingRow]
    control_balance: Decimal

    @property
    def totals(self) -> dict[str, Decimal]:
        return {b: sum((r.buckets[b] for r in self.rows), ZERO) for b in BUCKETS}

    @property
    def unapplied(self) -> Decimal:
        return sum((r.unapplied for r in self.rows), ZERO)

    @property
    def total(self) -> Decimal:
        return sum((r.total for r in self.rows), ZERO)

    @property
    def reconciles(self) -> bool:
        return self.total == self.control_balance


def ageing(ctx: WorkspaceContext, entity_id: UUID, *, as_of: date, side: str) -> Ageing:
    """Open amounts per counterparty in overdue buckets at ``as_of``, reconciled to the control
    accounts' balance on their normal side (AC-M2-2)."""
    if side not in (RECEIVABLE, PAYABLE):
        raise ValidationFailedError("Side must be RECEIVABLE or PAYABLE.",
                                    field_errors={"side": ["invalid"]})  # fmt: skip
    items = open_items(ctx, entity_id, as_of=as_of, side=side)
    rows: dict[UUID, AgeingRow] = {}
    names = {c.id: c.name for c in Counterparty.objects.filter(
        id__in={i.counterparty_id for i in items})}  # fmt: skip
    for item in items:
        row = rows.setdefault(item.counterparty_id, AgeingRow(
            item.counterparty_id, item.counterparty_code, names[item.counterparty_id]))  # fmt: skip
        if item.kind == "INVOICE":
            row.buckets[_bucket(item.days_overdue(as_of))] += item.open_amount
        else:
            row.unapplied += item.open_amount
    balance = ZERO
    for ln in _control_lines(entity_id, as_of, None, side):
        balance += (ln.debit - ln.credit) if side == RECEIVABLE else (ln.credit - ln.debit)
    return Ageing(as_of, side, sorted(rows.values(), key=lambda r: r.counterparty_code), balance)
