"""Public interface of the ``ledger`` module and its HTTP routes.

All routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Max, Q, Sum
from django.db.models.functions import TruncMonth
from django.http import HttpRequest, HttpResponse
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.audit_log.api import record as audit
from fcp.modules.identity.api import require_recent_auth
from fcp.modules.tenancy.api import get_entity, workspace_ctx

from . import (
    accounts,
    closing,
    corrections,
    dimensions,
    entries,
    fx,
    idempotency,
    integrity,
    periods,
    reports,
)
from .models import (
    Account,
    AccountDimensionRule,
    Dimension,
    DimensionValue,
    ExchangeRate,
    FiscalYear,
    IntegrityCheckRun,
    JournalEntry,
    JournalLine,
    LedgerSettings,
    LineDimension,
    Period,
    PeriodUnlock,
)

__all__ = [
    "Account",
    "AccountInput",
    "DimensionTotal",
    "EntryInput",
    "EntryLine",
    "FiscalYear",
    "JournalEntry",
    "JournalLine",
    "LineInput",
    "Period",
    "PostedEntry",
    "PostedLine",
    "TrialBalanceRow",
    "VatLine",
    "account_balance",
    "account_list",
    "add_account",
    "add_fiscal_year",
    "apply_account_template",
    "create_and_post",
    "create_entry_draft",
    "create_system_draft",
    "dimension_list",
    "entry_vat_lines",
    "fiscal_year_list",
    "posted_dimension_totals",
    "posted_entries",
    "posted_lines",
    "posting_watermark",
    "reverse_and_post",
    "router",
    "seed_vat_catalogue",
    "trial_balance_rows",
    "unposted_entries",
    "vat_lines",
]

EntryInput = entries.EntryInput
LineInput = entries.LineInput


@dataclass(frozen=True)
class PostedLine:
    """A posted line on one account, for sub-ledgers such as bank matching (M2-5)."""

    line_id: UUID
    entry_id: UUID
    entry_ref: str
    accounting_date: date
    net_debit: Decimal
    reference: str
    memo: str
    description: str


def posted_lines(
    ctx: Any, entity_id: UUID, account_id: UUID, *, date_from: date, date_to: date
) -> list[PostedLine]:
    """Posted lines of an account dated in the range (requires ``reports.read``)."""
    entity = get_entity(ctx, entity_id, "reports.read")
    rows = (
        JournalLine.objects.filter(
            entry__legal_entity_id=entity.id, account_id=account_id,
            entry__status=JournalEntry.Status.POSTED,
            entry__accounting_date__gte=date_from, entry__accounting_date__lte=date_to,
        )
        .select_related("entry__journal")
        .order_by("entry__accounting_date", "entry__posting_seq", "line_no")
    )  # fmt: skip
    return [
        PostedLine(
            ln.id, ln.entry_id, f"{ln.entry.journal.code}-{ln.entry.entry_no}",
            ln.entry.accounting_date, ln.debit - ln.credit, ln.reference, ln.memo,
            ln.entry.description,
        )
        for ln in rows
    ]  # fmt: skip


@dataclass(frozen=True)
class DimensionTotal:
    """Posted totals of one account in one month, for lines tagged with one dimension value."""

    account_id: UUID
    month: date
    value_id: UUID
    debit_total: Decimal
    credit_total: Decimal


def _operating(prefix: str = "") -> Q:
    """Posted entries other than year-end closing entries and reversals of them (M2-9)."""
    closing = Q(**{f"{prefix}entry_type": "CLOSING"}) | Q(
        **{f"{prefix}entry_type": "REVERSAL", f"{prefix}reverses_entry__entry_type": "CLOSING"}
    )
    return Q(**{f"{prefix}status": JournalEntry.Status.POSTED}) & ~closing


def posted_dimension_totals(  # noqa: PLR0913 (keyword-only filters)
    ctx: Any,
    entity_id: UUID,
    *,
    date_from: date,
    date_to: date,
    value_ids: list[UUID],
    watermark: int | None = None,
    permission: str = "reports.read",
) -> list[DimensionTotal]:
    """Monthly posted totals per account of lines tagged with the given dimension values, closing
    entries excluded; with ``watermark``, only postings up to it. Requires ``reports.read``, or
    ``budget.department`` for a department owner (the caller passes only the values they own)."""
    if permission not in ("reports.read", "budget.department"):
        raise ValueError(f"unsupported permission {permission!r}")
    entity = get_entity(ctx, entity_id, permission)
    rows = LineDimension.objects.filter(
        _operating("line__entry__"), line__entry__legal_entity_id=entity.id,
        value_id__in=value_ids, line__entry__accounting_date__gte=date_from,
        line__entry__accounting_date__lte=date_to,
    )  # fmt: skip
    if watermark is not None:
        rows = rows.filter(line__entry__posting_seq__lte=watermark)
    grouped = (
        rows.annotate(month=TruncMonth("line__entry__accounting_date"))
        .values("line__account_id", "month", "value_id")
        .annotate(debit=Sum("line__debit"), credit=Sum("line__credit"))
        .order_by("month", "line__account_id", "value_id")
    )
    return [
        DimensionTotal(r["line__account_id"], r["month"], r["value_id"], r["debit"], r["credit"])
        for r in grouped
    ]


def unposted_entries(ctx: Any, entity_id: UUID, *, date_from: date, date_to: date) -> int:
    """Entries dated in the range that are not posted yet (draft, submitted or approved)."""
    entity = get_entity(ctx, entity_id, "reports.read")
    return JournalEntry.objects.filter(
        legal_entity_id=entity.id, accounting_date__gte=date_from, accounting_date__lte=date_to,
        status__in=[JournalEntry.Status.DRAFT, JournalEntry.Status.SUBMITTED,
                    JournalEntry.Status.APPROVED],
    ).count()  # fmt: skip


def account_balance(ctx: Any, entity_id: UUID, account_id: UUID, *, as_of: date) -> Decimal:
    """Net debit balance of one account from all postings up to ``as_of``."""
    row = next((r for r in trial_balance_rows(ctx, entity_id, as_of=as_of)
                if r.account_id == account_id), None)  # fmt: skip
    return row.debit_total - row.credit_total if row else Decimal(0)


def create_entry_draft(ctx: Any, entity_id: UUID, data: entries.EntryInput) -> JournalEntry:
    """A draft from another module (e.g. a bank statement line), source IMPORT; it follows the
    normal workflow (doc 05 §8: sub-ledgers never write journal lines directly)."""
    return entries.create_draft(ctx, entity_id, data, source=JournalEntry.Source.IMPORT)


def create_system_draft(ctx: Any, entity_id: UUID, data: entries.EntryInput) -> JournalEntry:
    """A draft prepared by the platform (e.g. a VAT settlement, V1-2), source SYSTEM; it follows
    the normal workflow like every other entry."""
    return entries.create_draft(ctx, entity_id, data, source=JournalEntry.Source.SYSTEM)


@dataclass(frozen=True)
class VatLine:
    """A posted line that carries a VAT code or sits on a VAT account (V1-2)."""

    line_id: UUID
    entry_id: UUID
    entry_ref: str
    posting_seq: int
    accounting_date: date
    description: str
    account_code: str
    account_name: str
    account_type: str
    vat_role: str  # INPUT, OUTPUT or "" (a taxable amount on an income or expense account)
    vat_code_id: str | None
    vat_code: str
    treatment: str
    rate: Decimal | None
    verified: bool
    net_debit: Decimal
    counterparty: str
    reference: str
    # V1-2b: the code's category, the line's VAT details and the party's EU data.
    category: str = ""
    tax_point: date | None = None
    vat_recovery_percent: Decimal | None = None
    vat_blocked: Decimal | None = None
    counterparty_country: str = ""
    counterparty_vat_no: str = ""
    entry_status: str = "POSTED"


def entry_vat_lines(ctx: Any, entity_id: UUID, entry_id: UUID) -> list[VatLine]:
    """The VAT lines of one posted entry (V1-2f), as ``vat_lines`` gives them."""
    entity = get_entity(ctx, entity_id, "reports.read")
    entry = JournalEntry.objects.filter(legal_entity_id=entity.id, id=entry_id,
                                        status=JournalEntry.Status.POSTED).first()  # fmt: skip
    if entry is None:
        return []
    found = vat_lines(ctx, entity.id, date_from=entry.accounting_date,
                      date_to=entry.accounting_date)  # fmt: skip
    return [ln for ln in found if ln.entry_id == entry.id]


def vat_lines(ctx: Any, entity_id: UUID, *, date_from: date, date_to: date) -> list[VatLine]:
    """Posted lines dated in the range that carry a VAT code or sit on a VAT account, closing
    entries excluded (requires ``reports.read``).

    A line without its own customer or supplier takes its entry's (V1-2c): the party and the
    invoice number sit on the receivable or payable line, which carries no VAT code.
    """
    entity = get_entity(ctx, entity_id, "reports.read")
    rows = list(
        JournalLine.objects.filter(
            _operating("entry__"),
            Q(vat_code__isnull=False) | ~Q(account__vat_role=""),
            entry__legal_entity_id=entity.id, entry__status=JournalEntry.Status.POSTED,
            entry__accounting_date__gte=date_from, entry__accounting_date__lte=date_to,
        )
        .select_related("entry__journal", "account", "vat_code", "counterparty")
        .order_by("entry__accounting_date", "entry__posting_seq", "line_no")
    )  # fmt: skip
    parties: dict[UUID, JournalLine] = {}
    for party_line in (
        JournalLine.objects.filter(
            entry_id__in={ln.entry_id for ln in rows}, counterparty__isnull=False
        )
        .select_related("counterparty")
        .order_by("-line_no")
    ):
        parties[party_line.entry_id] = party_line  # the entry's first line with a party wins
    found = []
    for ln in rows:
        own = ln if ln.counterparty_id else parties.get(ln.entry_id)
        party = own.counterparty if own else None
        found.append(VatLine(
            ln.id, ln.entry_id, f"{ln.entry.journal.code}-{ln.entry.entry_no}",
            ln.entry.posting_seq or 0, ln.entry.accounting_date, ln.entry.description,
            ln.account.code, ln.account.name, ln.account.type, ln.account.vat_role,
            ln.vat_code_id, ln.vat_code.code if ln.vat_code else "",
            ln.vat_code.treatment if ln.vat_code else "",
            ln.vat_code.rate if ln.vat_code else None,
            bool(ln.vat_code and ln.vat_code.verified), ln.debit - ln.credit,
            party.name if party else "", ln.reference or (own.reference if own else ""),
            ln.vat_code.category if ln.vat_code else "", ln.tax_point, ln.vat_recovery_percent,
            ln.vat_blocked, party.country if party else "", party.vat_no if party else "",
        ))  # fmt: skip
    return found


def posting_watermark(ctx: Any, entity_id: UUID) -> int:
    """The entity's latest posting sequence number (0 before the first posting)."""
    entity = get_entity(ctx, entity_id, "reports.read")
    found = JournalEntry.objects.filter(
        legal_entity_id=entity.id, status=JournalEntry.Status.POSTED
    ).aggregate(m=Max("posting_seq"))["m"]
    return int(found or 0)


@dataclass(frozen=True)
class EntryLine:
    account_id: UUID
    debit: Decimal
    credit: Decimal


@dataclass(frozen=True)
class PostedEntry:
    """A posted entry and its lines, for modules with their own simplified screens (M5-1)."""

    id: UUID
    ref: str
    accounting_date: date
    description: str
    entry_type: str
    reverses_entry_id: UUID | None
    reversed_by_entry_id: UUID | None
    lines: tuple[EntryLine, ...]


def _posted(entry: JournalEntry) -> PostedEntry:
    return PostedEntry(
        entry.id, f"{entry.journal.code}-{entry.entry_no}", entry.accounting_date,
        entry.description, entry.entry_type, entry.reverses_entry_id, entry.reversed_by_entry_id,
        tuple(EntryLine(ln.account_id, ln.debit, ln.credit) for ln in entry.lines.all()),
    )  # fmt: skip


def create_and_post(ctx: Any, entity_id: UUID, data: entries.EntryInput) -> PostedEntry:
    """Create an entry and post it in one step (simplified personal screens, M5-1). Every
    ledger rule applies: balance, open period, approval policy (a household has none), gapless
    numbering and the audit trail."""
    with transaction.atomic():
        draft = entries.create_draft(ctx, entity_id, data)
        return _posted(entries.post(ctx, entity_id, draft.id))


def reverse_and_post(ctx: Any, entity_id: UUID, entry_id: UUID, *, reason: str,
                     reversal_date: date | None = None) -> PostedEntry:  # fmt: skip
    """Reverse a posted entry with a reason and post the reversal in one step."""
    with transaction.atomic():
        draft = corrections.reverse(ctx, entity_id, entry_id, reason=reason,
                                    reversal_date=reversal_date)  # fmt: skip
        return _posted(entries.post(ctx, entity_id, draft.id))


def posted_entries(ctx: Any, entity_id: UUID, *, date_from: date | None = None,
                   date_to: date | None = None, limit: int = 200) -> list[PostedEntry]:  # fmt: skip
    """Posted entries with their lines, newest first."""
    found = entries.list_entries(ctx, entity_id, status=JournalEntry.Status.POSTED,
                                 date_from=date_from, date_to=date_to, limit=limit)  # fmt: skip
    return [_posted(e) for e in found]


AccountInput = accounts.AccountInput
apply_account_template = accounts.apply_template
add_account = accounts.create_account
add_fiscal_year = periods.create_fiscal_year


# Read functions for other modules (the reporting gateway, M2-6 onwards).
account_list = accounts.list_accounts
fiscal_year_list = periods.list_fiscal_years
dimension_list = dimensions.list_dimensions
TrialBalanceRow = reports.TrialBalanceRow


def trial_balance_rows(
    ctx: Any, entity_id: UUID, *, as_of: date, date_from: date | None = None
) -> list[reports.TrialBalanceRow]:
    """Every postable account with its debit and credit totals up to ``as_of`` (zeros included)."""
    tb = reports.trial_balance(ctx, entity_id, as_of=as_of, date_from=date_from, include_zero=True)
    return tb.rows


def seed_vat_catalogue() -> int:
    from .models import VatCode  # noqa: PLC0415
    from .vat import seed_catalogue  # noqa: PLC0415

    return seed_catalogue(VatCode)


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
    control_type: Literal["", "RECEIVABLE", "PAYABLE"] = ""
    vat_role: Literal["", "INPUT", "OUTPUT"] = ""


class AccountPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    name_el: str | None = Field(default=None, max_length=200)
    status: Account.Status | None = None
    control_type: Literal["", "RECEIVABLE", "PAYABLE"] | None = None
    vat_role: Literal["", "INPUT", "OUTPUT"] | None = None


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
    control_type: str
    vat_role: str


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


# --- VAT codes (M2-3) -----------------------------------------------------------------------


class VatCodeOut(Schema):
    id: str
    code: str
    name: str
    name_el: str
    treatment: str
    category: str = Field(description="The VAT return's category of the code (V1-2b)")
    rate: str | None
    valid_from: date | None
    valid_to: date | None
    verified: bool
    verification_note: str


class VatCodeQuery(Schema):
    on: date | None = Field(default=None, description="Only codes valid on this date")


@router.get(f"{BASE}/vat-codes", response=list[VatCodeOut])
@requires("ledger.account.read")
def list_vat_codes(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[VatCodeQuery]
) -> list[VatCodeOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        VatCodeOut(
            id=v.id,
            code=v.code,
            name=v.name,
            name_el=v.name_el,
            treatment=v.treatment,
            category=v.category,
            rate=f"{v.rate:.4f}" if v.rate is not None else None,
            valid_from=v.valid_from,
            valid_to=v.valid_to,
            verified=v.verified,
            verification_note=v.verification_note,
        )
        for v in accounts.vat_codes(ctx, entity_id, on=q.on)
    ]


# --- dimensions (M2-1) -----------------------------------------------------------------------


class DimensionValueOut(Schema):
    id: UUID
    code: str
    name: str
    parent_id: UUID | None
    status: str


class DimensionOut(Schema):
    id: UUID
    code: str
    name: str
    kind: str
    status: str
    values: list[DimensionValueOut]


class DimensionIn(Schema):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    kind: Dimension.Kind


class DimensionPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    status: Dimension.Status | None = None


class DimensionValueIn(Schema):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    parent_code: str | None = Field(default=None, max_length=30)


class DimensionValuePatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    status: Dimension.Status | None = None


class DimensionRuleIO(Schema):
    dimension_id: UUID
    rule: AccountDimensionRule.Rule


def _dimension_out(d: Dimension) -> DimensionOut:
    return DimensionOut(
        id=d.id,
        code=d.code,
        name=d.name,
        kind=d.kind,
        status=d.status,
        values=[
            DimensionValueOut.from_orm(v) for v in sorted(d.values.all(), key=lambda v: v.code)
        ],
    )


@router.get(f"{BASE}/dimensions", response=list[DimensionOut])
@requires("ledger.account.read")
def list_dimensions(request: HttpRequest, slug: str, entity_id: UUID) -> list[DimensionOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_dimension_out(d) for d in dimensions.list_dimensions(ctx, entity_id)]


@router.post(f"{BASE}/dimensions", response={201: DimensionOut})
@requires("ledger.account.manage")
def create_dimension(
    request: HttpRequest, slug: str, entity_id: UUID, payload: DimensionIn
) -> Status[DimensionOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    created = dimensions.create_dimension(ctx, entity_id, **payload.dict())
    return Status(201, _dimension_out(created))


@router.patch(f"{BASE}/dimensions/{{uuid:dimension_id}}", response=DimensionOut)
@requires("ledger.account.manage")
def update_dimension(
    request: HttpRequest, slug: str, entity_id: UUID, dimension_id: UUID, payload: DimensionPatch
) -> DimensionOut:
    ctx = workspace_ctx(request, slug, entity_id)
    updated = dimensions.update_dimension(
        ctx, entity_id, dimension_id, **payload.dict(exclude_unset=True)
    )
    return _dimension_out(updated)


@router.post(f"{BASE}/dimensions/{{uuid:dimension_id}}/values", response={201: DimensionValueOut})
@requires("ledger.account.manage")
def create_dimension_value(
    request: HttpRequest,
    slug: str,
    entity_id: UUID,
    dimension_id: UUID,
    payload: DimensionValueIn,
) -> Status[DimensionValue]:
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, dimensions.create_value(ctx, entity_id, dimension_id, **payload.dict()))


@router.patch(f"{BASE}/dimension-values/{{uuid:value_id}}", response=DimensionValueOut)
@requires("ledger.account.manage")
def update_dimension_value(
    request: HttpRequest, slug: str, entity_id: UUID, value_id: UUID, payload: DimensionValuePatch
) -> DimensionValue:
    ctx = workspace_ctx(request, slug, entity_id)
    return dimensions.update_value(ctx, entity_id, value_id, **payload.dict(exclude_unset=True))


@router.get(f"{BASE}/accounts/{{uuid:account_id}}/dimension-rules", response=list[DimensionRuleIO])
@requires("ledger.account.read")
def get_dimension_rules(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID
) -> list[DimensionRuleIO]:
    ctx = workspace_ctx(request, slug, entity_id)
    account = accounts.get_account(ctx, entity_id, account_id)
    rules = dimensions.account_rules(entity_id, [account.id]).get(account.id, {})
    return [
        DimensionRuleIO(dimension_id=d, rule=AccountDimensionRule.Rule(r)) for d, r in rules.items()
    ]


@router.put(f"{BASE}/accounts/{{uuid:account_id}}/dimension-rules", response=list[DimensionRuleIO])
@requires("ledger.account.manage")
def set_dimension_rules(
    request: HttpRequest,
    slug: str,
    entity_id: UUID,
    account_id: UUID,
    payload: list[DimensionRuleIO],
) -> list[DimensionRuleIO]:
    ctx = workspace_ctx(request, slug, entity_id)
    created = dimensions.set_account_rules(
        ctx, entity_id, account_id, [(r.dimension_id, r.rule) for r in payload]
    )
    return [
        DimensionRuleIO(dimension_id=r.dimension_id, rule=AccountDimensionRule.Rule(r.rule))
        for r in created
    ]


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
    dimension_value_ids: list[UUID] = Field(
        default_factory=list, max_length=10, description="At most one value per dimension"
    )
    counterparty_id: UUID | None = Field(
        default=None, description="Customer or supplier; required on control-account lines"
    )
    reference: str = Field(default="", max_length=50, description="Invoice or document number")
    due_date: date | None = None
    vat_code_id: str | None = Field(
        default=None, max_length=40, description="VAT code id; required on VAT-account lines"
    )
    tax_point: date | None = Field(default=None, description="When it differs from the date")
    vat_recovery_percent: str | None = Field(
        default=None, description="Input VAT lines: the deductible share, 0 to 100"
    )
    vat_blocked: str | None = Field(
        default=None, description="Input VAT lines: the VAT that may not be deducted"
    )
    txn_currency: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$", description="Foreign currency of the line (V1-2h)"
    )
    txn_amount: str | None = Field(default=None, description="The amount in that currency")
    exchange_rate: str | None = Field(
        default=None, description="Functional units per unit, at the transaction's date and time"
    )
    rate_at: datetime | None = Field(default=None, description="When that rate applied")
    rate_source: str = Field(default="", max_length=200, description="Bank, invoice, stored rate")


class EntryIn(Schema):
    accounting_date: date
    document_date: date | None = None
    description: str = Field(min_length=1, max_length=500)
    journal: str = Field(default="GJ", max_length=10)
    use_adjustment_period: bool = False
    currency: str | None = Field(
        default=None, pattern=r"^[A-Z]{3}$",
        description="ISO 4217; omitted means the functional currency, the only one accepted while "
        "multi-currency is disabled",
    )  # fmt: skip
    lines: list[LineIn] = Field(min_length=1, max_length=500)


class LineDimensionOut(Schema):
    dimension_id: UUID
    dimension_code: str
    value_id: UUID
    value_code: str
    value_name: str


class LineOut(Schema):
    line_no: int
    account_id: UUID
    account_code: str
    debit: str
    credit: str
    memo: str
    dimensions: list[LineDimensionOut]
    counterparty_id: UUID | None
    counterparty_code: str | None
    reference: str
    due_date: date | None
    vat_code_id: str | None
    vat_code: str | None
    tax_point: date | None = None
    vat_recovery_percent: str | None = None
    vat_blocked: str | None = None
    txn_currency: str | None = None
    txn_amount: str | None = None
    exchange_rate: str | None = None
    rate_at: datetime | None = None
    rate_source: str = ""


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
    self_approved: bool = Field(description="Approved by its preparer (one-person workspace)")
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


class CurrencySettingsIn(Schema):
    multi_currency_enabled: bool
    fx_account_id: UUID | None = Field(default=None, description="Where exchange differences go")


class CurrencySettingsOut(Schema):
    functional_currency: str
    multi_currency_enabled: bool
    fx_account_id: UUID | None


class SuggestedRateOut(Schema):
    currency: str
    rate: str = Field(description="Functional units per one unit of the currency")
    rate_date: date
    rate_type: str
    source: str


class RateQuery(Schema):
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    on: date


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
        self_approved=entry.self_approved,
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
                dimensions=[
                    LineDimensionOut(
                        dimension_id=t.dimension_id,
                        dimension_code=t.dimension.code,
                        value_id=t.value_id,
                        value_code=t.value.code,
                        value_name=t.value.name,
                    )
                    for t in sorted(ln.dimension_tags.all(), key=lambda t: t.dimension.code)
                ],
                counterparty_id=ln.counterparty_id,
                counterparty_code=ln.counterparty.code if ln.counterparty else None,
                reference=ln.reference,
                due_date=ln.due_date,
                vat_code_id=ln.vat_code_id,
                vat_code=ln.vat_code.code if ln.vat_code else None,
                txn_currency=ln.txn_currency,
                txn_amount=None
                if ln.txn_currency is None
                else f"{(ln.txn_debit or ln.txn_credit):f}",
                exchange_rate=None if ln.exchange_rate is None else f"{ln.exchange_rate:f}",
                rate_at=ln.rate_at,
                rate_source=ln.rate_source,
                tax_point=ln.tax_point,
                vat_recovery_percent=None
                if ln.vat_recovery_percent is None
                else f"{ln.vat_recovery_percent:.2f}",
                vat_blocked=None if ln.vat_blocked is None else f"{ln.vat_blocked:.2f}",
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
        currency=payload.currency,
        lines=[
            entries.LineInput(
                ln.account_id,
                ln.debit,
                ln.credit,
                ln.memo,
                tuple(ln.dimension_value_ids),
                ln.counterparty_id,
                ln.reference,
                ln.due_date,
                ln.vat_code_id,
                ln.tax_point,
                ln.vat_recovery_percent,
                ln.vat_blocked,
                ln.txn_currency,
                ln.txn_amount,
                ln.exchange_rate,
                ln.rate_at,
                ln.rate_source,
            )
            for ln in payload.lines
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
    self_approved: bool = Field(description="Opened on the requester's own approval (one-person)")
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


# --- year-end close (M2-9) ------------------------------------------------------------------------


class ClosingLineOut(Schema):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    dimension_value_ids: list[UUID]
    balance: str = Field(description="Net debit balance at the year-end that the close moves")


class YearEndCheckOut(Schema):
    code: str
    ok: bool
    details: list[str]


class CloseStatusOut(Schema):
    fiscal_year_id: UUID
    name: str
    status: str
    end_date: date
    result: str = Field(description="Profit (positive) or loss (negative) still to be closed")
    lines: list[ClosingLineOut]
    blockers: list[str]
    closing_entry_id: UUID | None
    closing_entry_status: str | None
    reopen_entry_id: UUID | None
    checks: list[YearEndCheckOut]


@router.get(f"{BASE}/fiscal-years/{{uuid:fiscal_year_id}}/close", response=CloseStatusOut)
@requires("ledger.period.read")
def close_status(
    request: HttpRequest, slug: str, entity_id: UUID, fiscal_year_id: UUID
) -> CloseStatusOut:
    """What closing the year would move, what blocks it, and the AC-M2-9 checks once closed."""
    ctx = workspace_ctx(request, slug, entity_id)
    st = closing.status(ctx, entity_id, fiscal_year_id)
    return CloseStatusOut(
        fiscal_year_id=st.fiscal_year.id, name=st.fiscal_year.name, status=st.fiscal_year.status,
        end_date=st.fiscal_year.end_date, result=f"{st.result:.2f}",
        lines=[ClosingLineOut(account_id=ln.account.id, account_code=ln.account.code,
                              account_name=ln.account.name, account_type=ln.account.type,
                              dimension_value_ids=list(ln.value_ids),
                              balance=f"{ln.net_debit:.2f}") for ln in st.lines],
        blockers=st.blockers,
        closing_entry_id=st.closing_entry.id if st.closing_entry else None,
        closing_entry_status=st.closing_entry.status if st.closing_entry else None,
        reopen_entry_id=st.reopen_entry.id if st.reopen_entry else None,
        checks=[YearEndCheckOut(code=c.code, ok=c.ok, details=c.details) for c in st.checks],
    )  # fmt: skip


class CloseIn(Schema):
    retained_earnings_account_id: UUID


@router.post(f"{BASE}/fiscal-years/{{uuid:fiscal_year_id}}/close", response={201: EntryOut})
@requires("ledger.period.lock")
def close_fiscal_year(
    request: HttpRequest, slug: str, entity_id: UUID, fiscal_year_id: UUID, payload: CloseIn
) -> Status[EntryOut]:
    """Generate the closing entry (submitted). Posting it, after approval, closes the year."""
    ctx = workspace_ctx(request, slug, entity_id)
    entry = closing.generate(ctx, entity_id, fiscal_year_id, payload.retained_earnings_account_id)
    return Status(201, entry_out(entry))


class ReopenIn(Schema):
    reason: str = Field(min_length=1, max_length=500)


@router.post(f"{BASE}/fiscal-years/{{uuid:fiscal_year_id}}/reopen", response={201: EntryOut})
@requires("ledger.period.lock")
def reopen_fiscal_year(
    request: HttpRequest, slug: str, entity_id: UUID, fiscal_year_id: UUID, payload: ReopenIn
) -> Status[EntryOut]:
    """Reverse the closing entry on its own date (submitted). Posting it re-opens the year."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, entry_out(closing.reopen(ctx, entity_id, fiscal_year_id, payload.reason)))


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


# --- reports (M1-10) ---------------------------------------------------------------------------


class TrialBalanceQuery(Schema):
    as_of: date
    date_from: date | None = None
    include_zero: bool = False
    dimension_value_id: UUID | None = Field(
        default=None, description="Only lines tagged with this value (the result need not balance)"
    )


class TrialBalanceRowOut(Schema):
    account_id: UUID
    code: str
    name: str
    type: str
    debit: str
    credit: str
    balance: str


class TrialBalanceOut(Schema):
    as_of: date
    date_from: date | None
    rows: list[TrialBalanceRowOut]
    total_debit: str
    total_credit: str
    unposted_entries: int
    restated_after_lock: int


class LedgerQuery(Schema):
    date_from: date
    date_to: date
    dimension_value_id: UUID | None = None


class LedgerLineOut(Schema):
    entry_id: UUID
    entry_ref: str
    accounting_date: date
    description: str
    memo: str
    debit: str
    credit: str
    running_balance: str
    restated_after_lock: bool


class AccountLedgerOut(Schema):
    account_id: UUID
    code: str
    name: str
    date_from: date
    date_to: date
    opening_balance: str
    lines: list[LedgerLineOut]
    closing_balance: str


def _tb(request: HttpRequest, slug: str, entity_id: UUID, q: TrialBalanceQuery) -> Any:
    ctx = workspace_ctx(request, slug, entity_id)
    return ctx, reports.trial_balance(
        ctx,
        entity_id,
        as_of=q.as_of,
        date_from=q.date_from,
        include_zero=q.include_zero,
        dimension_value_id=q.dimension_value_id,
    )


@router.get(f"{BASE}/reports/trial-balance", response=TrialBalanceOut)
@requires("reports.read")
def trial_balance(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[TrialBalanceQuery]
) -> TrialBalanceOut:
    _, tb = _tb(request, slug, entity_id, q)
    return TrialBalanceOut(
        as_of=tb.as_of,
        date_from=tb.date_from,
        rows=[
            TrialBalanceRowOut(
                account_id=r.account_id,
                code=r.code,
                name=r.name,
                type=r.type,
                debit=f"{r.balance_debit:.2f}",
                credit=f"{r.balance_credit:.2f}",
                balance=f"{r.balance:.2f}",
            )
            for r in tb.rows
        ],
        total_debit=f"{tb.total_debit:.2f}",
        total_credit=f"{tb.total_credit:.2f}",
        unposted_entries=tb.unposted_entries,
        restated_after_lock=tb.restated_after_lock,
    )


def _csv(ctx: Any, entity_id: UUID, content: str, filename: str, report: str) -> HttpResponse:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="reports.exported",
        subject_type="report",
        subject_id=report,
        entity_id=entity_id,
        changes={"format": "csv", "filename": filename},
    )
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@router.get(f"{BASE}/reports/trial-balance.csv")
@requires("reports.export")
def trial_balance_csv(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[TrialBalanceQuery]
) -> HttpResponse:
    ctx, tb = _tb(request, slug, entity_id, q)
    return _csv(
        ctx,
        entity_id,
        reports.trial_balance_csv(tb),
        f"trial-balance-{tb.as_of.isoformat()}.csv",
        "trial_balance",
    )


def _gl(request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, q: LedgerQuery) -> Any:
    ctx = workspace_ctx(request, slug, entity_id)
    return ctx, reports.general_ledger(
        ctx,
        entity_id,
        account_id,
        date_from=q.date_from,
        date_to=q.date_to,
        dimension_value_id=q.dimension_value_id,
    )


@router.get(f"{BASE}/reports/general-ledger/{{uuid:account_id}}", response=AccountLedgerOut)
@requires("reports.read")
def general_ledger(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, q: Query[LedgerQuery]
) -> AccountLedgerOut:
    _, gl = _gl(request, slug, entity_id, account_id, q)
    return AccountLedgerOut(
        account_id=gl.account.id,
        code=gl.account.code,
        name=gl.account.name,
        date_from=gl.date_from,
        date_to=gl.date_to,
        opening_balance=f"{gl.opening_balance:.2f}",
        lines=[
            LedgerLineOut(
                entry_id=ln.entry_id,
                entry_ref=f"{ln.journal}-{ln.entry_no}",
                accounting_date=ln.accounting_date,
                description=ln.description,
                memo=ln.memo,
                debit=f"{ln.debit:.2f}",
                credit=f"{ln.credit:.2f}",
                running_balance=f"{ln.running_balance:.2f}",
                restated_after_lock=ln.restated_after_lock,
            )
            for ln in gl.lines
        ],
        closing_balance=f"{gl.closing_balance:.2f}",
    )


@router.get(f"{BASE}/reports/general-ledger/{{uuid:account_id}}.csv")
@requires("reports.export")
def general_ledger_csv(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, q: Query[LedgerQuery]
) -> HttpResponse:
    ctx, gl = _gl(request, slug, entity_id, account_id, q)
    return _csv(
        ctx,
        entity_id,
        reports.general_ledger_csv(gl),
        f"general-ledger-{gl.account.code}-{gl.date_to.isoformat()}.csv",
        "general_ledger",
    )


# --- integrity checks (M1-11) --------------------------------------------------------------------


class IntegrityCheckOut(Schema):
    id: UUID
    status: str
    trigger: str
    created_at: datetime
    finished_at: datetime
    results: list[dict[str, Any]]


@router.get("/w/{slug}/integrity-checks", response=list[IntegrityCheckOut])
@requires("admin.integrity.read")
def list_integrity_checks(request: HttpRequest, slug: str) -> list[IntegrityCheckRun]:
    ctx = workspace_ctx(request, slug)
    return list(IntegrityCheckRun.objects.filter(tenant=ctx.tenant).order_by("-created_at")[:30])


@router.post("/w/{slug}/integrity-checks", response={201: IntegrityCheckOut})
@requires("admin.integrity.read")
def run_integrity_check(request: HttpRequest, slug: str) -> Status[IntegrityCheckRun]:
    ctx = workspace_ctx(request, slug)
    return Status(201, integrity.run_checks(ctx.tenant.id, trigger="ON_DEMAND"))


# --- exchange rates (M6F-1, #80) ------------------------------------------------------------------


class ExchangeRateIn(Schema):
    rate_date: date
    base_currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217")
    quote_currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217")
    rate: str = Field(pattern=r"^\d{1,9}(\.\d{1,10})?$", description="Quote units per base unit")
    rate_type: Literal["SPOT", "CLOSING", "AVERAGE"]
    source: str = Field(min_length=1, max_length=200, description="e.g. ECB reference rate")
    source_hash: str = Field(default="", max_length=64, description="SHA-256 of the source file")


class ExchangeRateOut(Schema):
    id: UUID
    rate_date: date
    base_currency: str
    quote_currency: str
    rate: str
    rate_type: str
    source: str
    source_hash: str
    created_at: datetime


def _rate_out(r: ExchangeRate) -> ExchangeRateOut:
    return ExchangeRateOut(id=r.id, rate_date=r.rate_date, base_currency=r.base_currency,
                           quote_currency=r.quote_currency, rate=f"{r.rate.normalize():f}",
                           rate_type=r.rate_type, source=r.source, source_hash=r.source_hash,
                           created_at=r.created_at)  # fmt: skip


@router.get(f"{BASE}/exchange-rates", response=list[ExchangeRateOut])
@requires("reports.read")
def list_exchange_rates(request: HttpRequest, slug: str, entity_id: UUID) -> list[ExchangeRateOut]:
    """Recorded exchange rates (the workspace's), newest first."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_rate_out(r) for r in fx.rates(ctx, entity_id)]


@router.get(
    f"{BASE}/exchange-rates/suggestion", response={200: SuggestedRateOut, 404: dict[str, str]}
)
@requires("ledger.entry.read")
def suggest_rate(request: HttpRequest, slug: str, entity_id: UUID,
                 query: Query[RateQuery]) -> Any:  # fmt: skip
    """The stored rate to suggest for a currency on a date (latest on or before it, spot rates
    first), in functional units per unit. Only a suggestion: record the rate of the transaction
    itself (bank, invoice) on the line."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = fx.suggested_rate(ctx, entity_id, query.currency, query.on)
    if found is None:
        return Status(404, {"detail": f"No stored rate for {query.currency} on or before "
                                      f"{query.on.isoformat()}."})  # fmt: skip
    return SuggestedRateOut(currency=query.currency, rate=f"{found.rate:f}",
                            rate_date=found.rate_date, rate_type=found.rate_type,
                            source=found.source)  # fmt: skip


@router.get(f"{BASE}/currency-settings", response=CurrencySettingsOut)
@requires("ledger.entry.read")
def get_currency_settings(request: HttpRequest, slug: str, entity_id: UUID) -> CurrencySettingsOut:
    ctx = workspace_ctx(request, slug, entity_id)
    entity = get_entity(ctx, entity_id, "ledger.entry.read")
    found = entries.ledger_settings(ctx, entity_id)
    return CurrencySettingsOut(functional_currency=entity.functional_currency,
                               multi_currency_enabled=entity.multi_currency_enabled,
                               fx_account_id=found.fx_account_id)  # fmt: skip


@router.put(f"{BASE}/currency-settings", response=CurrencySettingsOut)
@requires("ledger.settings.manage")
def put_currency_settings(request: HttpRequest, slug: str, entity_id: UUID,
                          payload: CurrencySettingsIn) -> CurrencySettingsOut:  # fmt: skip
    """Switch foreign currency on (with the account exchange differences go to) or off."""
    ctx = workspace_ctx(request, slug, entity_id)
    found = fx.set_currency_settings(ctx, entity_id, enabled=payload.multi_currency_enabled,
                                     fx_account_id=payload.fx_account_id)  # fmt: skip
    entity = get_entity(ctx, entity_id, "ledger.entry.read")
    return CurrencySettingsOut(functional_currency=entity.functional_currency,
                               multi_currency_enabled=entity.multi_currency_enabled,
                               fx_account_id=found.fx_account_id)  # fmt: skip


@router.post(f"{BASE}/exchange-rates", response={201: ExchangeRateOut})
@requires("ledger.fx.manage")
def add_exchange_rate(request: HttpRequest, slug: str, entity_id: UUID,
                      payload: ExchangeRateIn) -> Status[ExchangeRateOut]:  # fmt: skip
    """Record a rate with its source; rates are never changed (a correction is a new source)."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = fx.add_rate(ctx, entity_id, fx.NewRate(**payload.model_dump()))
    return Status(201, _rate_out(made))
