"""Loans of an assumption set (M6F-4, #149): add one, bring in the debt register's loans as they
stand at the cut-over, or remove one, while the set is a draft."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import IntegrityError, transaction

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import month_start
from fcp.modules.registers.api import debt_positions
from fcp.modules.tenancy.api import WorkspaceContext

from .assumptions import READ, RUN, _set, horizon
from .models import AssumptionLoan, AssumptionSet, AssumptionValue

CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,19}$")
MAX_AMOUNT = Decimal("1e12")


@dataclass(frozen=True)
class NewLoan:
    code: str
    name: str
    kind: str  # EXISTING or NEW
    structure: str
    term_months: int
    annual_rate: str  # percent a year
    opening_balance: str = "0"
    amount: str = "0"
    drawdown_month: date | None = None
    interest_only_months: int = 0
    note: str = ""


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def _amount(raw: str, field: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation:
        value = Decimal("NaN")
    if not value.is_finite() or not Decimal(0) <= value < MAX_AMOUNT or value != value.quantize(
            Decimal("0.01")):  # fmt: skip
        raise _invalid(field, "Enter an amount in cents, such as 25000.00.")
    return value


def _draft(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> AssumptionSet:
    made = _set(ctx, entity_id, set_id, RUN)
    if made.status != AssumptionSet.Status.DRAFT:
        raise ConflictError("This set is approved and never changes. Revise it as a new version.")
    return made


def loans(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> list[AssumptionLoan]:
    made = _set(ctx, entity_id, set_id, READ)
    return list(AssumptionLoan.objects.filter(assumption_set=made).order_by("code"))


def _create(ctx: WorkspaceContext, made: AssumptionSet, data: NewLoan,
            series_id: UUID | None = None) -> AssumptionLoan:  # fmt: skip
    code, name = data.code.strip().upper(), data.name.strip()
    if not CODE.match(code):
        raise _invalid("code", "Use 1 to 20 letters, digits, - or _ for the loan's code.")
    if not name or len(name) > 120:
        raise _invalid("name", "Give the loan a name of 1 to 120 characters.")
    if data.kind not in AssumptionLoan.Kind.values:
        raise _invalid("kind", "Choose an existing loan or a new one.")
    if data.structure not in AssumptionLoan.Structure.values:
        raise _invalid("structure", "Choose annuity, equal principal or bullet repayment.")
    if not 1 <= data.term_months <= 600 or not 0 <= data.interest_only_months < data.term_months:
        raise _invalid("term_months", "Enter a term of 1 to 600 months, longer than any "
                       "interest-only months.")  # fmt: skip
    try:
        rate = Decimal(data.annual_rate)
    except InvalidOperation:
        rate = Decimal("NaN")
    if not rate.is_finite() or not Decimal(0) <= rate <= 100:
        raise _invalid("annual_rate", "Enter a rate from 0 to 100% a year.")
    months = horizon(made.cutover, made.months)
    opening, amount, drawdown = Decimal(0), Decimal(0), None
    if data.kind == AssumptionLoan.Kind.EXISTING:
        opening = _amount(data.opening_balance, "opening_balance")
        if opening <= 0:
            raise _invalid("opening_balance", "Enter the balance owed at the cut-over.")
    else:
        amount = _amount(data.amount, "amount")
        drawdown = month_start(data.drawdown_month) if data.drawdown_month else None
        if amount <= 0 or drawdown not in months:
            raise _invalid("drawdown_month", "A new loan needs an amount and a drawdown month "
                           "within the set's horizon.")  # fmt: skip
    try:
        with transaction.atomic():
            loan = AssumptionLoan.objects.create(
                tenant=ctx.tenant, assumption_set=made, code=code, name=name, kind=data.kind,
                opening_balance=opening, amount=amount, drawdown_month=drawdown,
                structure=data.structure, term_months=data.term_months,
                interest_only_months=data.interest_only_months, annual_rate=rate,
                register_series_id=series_id, note=data.note.strip()[:500],
            )  # fmt: skip
    except IntegrityError:
        raise _invalid("code", f"The set already has a loan {code}.") from None
    AssumptionValue.objects.bulk_create(
        AssumptionValue(tenant=ctx.tenant, assumption_set=made, driver="loan_rate", line=code,
                        month=m, value=rate, source=AssumptionValue.Source.DEFAULT)
        for m in months
    )  # fmt: skip
    return loan


def _audit(ctx: WorkspaceContext, made: AssumptionSet, action: str, **changes: object) -> None:
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
          action=f"projections.assumption_loan.{action}", subject_type="assumption_set",
          subject_id=made.id, entity_id=made.legal_entity_id,
          changes={k: str(v) for k, v in changes.items()})  # fmt: skip


@transaction.atomic
def add_loan(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID,
             data: NewLoan) -> AssumptionLoan:  # fmt: skip
    made = _draft(ctx, entity_id, set_id)
    loan = _create(ctx, made, data)
    _audit(ctx, made, "added", code=loan.code, kind=loan.kind, structure=loan.structure)
    return loan


@transaction.atomic
def add_from_register(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> list[AssumptionLoan]:
    """Every drawn loan of the debt register, with its balance at the set's cut-over."""
    made = _draft(ctx, entity_id, set_id)
    taken = set(AssumptionLoan.objects.filter(assumption_set=made)
                .values_list("register_series_id", flat=True))  # fmt: skip
    added = []
    for n, p in enumerate(debt_positions(ctx, made.legal_entity_id, made.cutover), start=1):
        if p.series_id in taken:
            continue
        note = f"From the debt register ({p.kind.lower().replace('_', ' ')}"
        note += f", {p.rate_type.lower()} rate)."
        if p.frequency_months != 1:
            note += (f" The register pays every {p.frequency_months} months; the projection pays "
                     "monthly.")  # fmt: skip
        number = n
        code = f"REG-{number}"
        while AssumptionLoan.objects.filter(assumption_set=made, code=code).exists():
            number += 100
            code = f"REG-{number}"
        added.append(_create(ctx, made, NewLoan(
            code=code, name=p.name[:120], kind="EXISTING", structure=p.structure,
            term_months=min(p.remaining_months, 600), annual_rate=f"{p.annual_rate:.4f}",
            opening_balance=f"{p.balance:.2f}", interest_only_months=p.interest_only_months,
            note=note), series_id=p.series_id))  # fmt: skip
    _audit(ctx, made, "added_from_register", count=len(added))
    return added


@transaction.atomic
def remove_loan(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID, code: str) -> None:
    made = _draft(ctx, entity_id, set_id)
    loan = AssumptionLoan.objects.filter(assumption_set=made, code=code).first()
    if loan is None:
        raise NotFoundError("Loan not found.")
    AssumptionValue.objects.filter(assumption_set=made, line=code,
                                   driver__in=("loan_rate", "loan_prepayment",
                                               "loan_drawdown")).delete()  # fmt: skip
    loan.delete()
    _audit(ctx, made, "removed", code=code)
