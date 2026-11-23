"""Exchange rates as data (M6F-1, #80): recorded with their source, never changed, never fetched
live (doc 10 §13).

Foreign-currency transactions (V1-2h, #219; owner decision 2026-11-23) are converted into the
functional currency at the rate of the transaction's date and time, recorded on each line with
when it applied and its source (the bank, the invoice, or a stored rate suggested here). They are
switched on per entity, once an exchange-differences account is chosen; exchange differences
themselves follow in V1-2h2 (#230)."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.core.money.currency import get_currency
from fcp.core.money.errors import UnknownCurrencyError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity, set_multi_currency

from .models import Account, ExchangeRate, LedgerSettings

MAX_RATE = Decimal("1e9")


@dataclass(frozen=True)
class NewRate:
    rate_date: date
    base_currency: str
    quote_currency: str
    rate: str
    rate_type: str
    source: str
    source_hash: str = ""


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def rates(ctx: WorkspaceContext, entity_id: UUID, limit: int = 200) -> list[ExchangeRate]:
    get_entity(ctx, entity_id, "reports.read")
    return list(ExchangeRate.objects.order_by("-rate_date", "base_currency", "quote_currency")
                [: max(1, min(limit, 1000))])  # fmt: skip


@transaction.atomic
def add_rate(ctx: WorkspaceContext, entity_id: UUID, data: NewRate) -> ExchangeRate:
    entity = get_entity(ctx, entity_id, "ledger.fx.manage")
    for field in ("base_currency", "quote_currency"):
        try:
            get_currency(getattr(data, field))
        except UnknownCurrencyError:
            raise _invalid(field, "Use a supported ISO 4217 currency code.") from None
    if data.base_currency == data.quote_currency:
        raise _invalid("quote_currency", "The two currencies must differ.")
    try:
        rate = Decimal(data.rate)
    except InvalidOperation:
        rate = Decimal("NaN")
    exponent = rate.as_tuple().exponent
    if (
        not rate.is_finite()
        or not Decimal(0) < rate < MAX_RATE
        or (isinstance(exponent, int) and exponent < -10)
    ):
        raise _invalid("rate", "Enter a positive rate with at most 10 decimal places.")
    if data.rate_type not in ExchangeRate.RateType.values:
        raise _invalid("rate_type", "Choose SPOT, CLOSING or AVERAGE.")
    if not data.source.strip():
        raise _invalid("source", "Say where the rate comes from.")
    try:
        with transaction.atomic():
            made = ExchangeRate.objects.create(
                tenant=ctx.tenant, rate_date=data.rate_date, base_currency=data.base_currency,
                quote_currency=data.quote_currency, rate=rate, rate_type=data.rate_type,
                source=data.source.strip()[:200], source_hash=data.source_hash[:64],
                created_by=ctx.user,
            )  # fmt: skip
    except IntegrityError:
        raise ConflictError("This rate is already recorded from that source.") from None
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action="ledger.exchange_rate.added",
          subject_type="exchange_rate", subject_id=made.id, entity_id=entity.id,
          changes={"pair": f"{made.base_currency}/{made.quote_currency}", "rate": str(rate),
                   "date": made.rate_date.isoformat(), "type": made.rate_type,
                   "source": made.source})  # fmt: skip
    return made


# --- foreign-currency transactions (V1-2h) -------------------------------------------------------


@dataclass(frozen=True)
class SuggestedRate:
    """A stored rate turned into functional units per one unit of the currency."""

    rate: Decimal
    rate_date: date
    rate_type: str
    source: str


def suggested_rate(ctx: WorkspaceContext, entity_id: UUID, currency: str,
                   on: date) -> SuggestedRate | None:  # fmt: skip
    """The latest stored rate on or before ``on`` between the currency and the entity's functional
    currency, in either direction, spot rates first. Only a suggestion: the rate of the
    transaction itself (bank, invoice) is what the line records."""
    entity = get_entity(ctx, entity_id, "ledger.entry.read")
    functional = entity.functional_currency
    found = (
        ExchangeRate.objects.filter(rate_date__lte=on)
        .filter(base_currency__in=[functional, currency], quote_currency__in=[functional, currency])
        .order_by("-rate_date")
    )
    best = None
    for r in found[:20]:
        rank = (r.rate_date, {"SPOT": 2, "CLOSING": 1}.get(r.rate_type, 0))
        if best is None or rank > best[0]:
            best = (rank, r)
    if best is None:
        return None
    r = best[1]
    value = r.rate if r.base_currency == currency else Decimal(1) / r.rate
    return SuggestedRate(value.quantize(Decimal("1e-10"), ROUND_HALF_UP), r.rate_date,
                         r.rate_type, r.source)  # fmt: skip


def foreign_line(  # noqa: PLR0913 - the line's foreign-currency fields
    entity: Any,
    i: int,
    *,
    currency: str | None,
    amount: str | None,
    rate: str | None,
    rate_at: datetime | None,
    rate_source: str,
    functional: Decimal,
) -> dict[str, Any]:
    """The transaction-currency fields of a line, checked: the currency is not the functional one
    and the entity allows foreign currency; the amount is positive and rounded to the currency;
    the rate is positive, with its date and time and its source; and the functional amount is the
    foreign amount at that rate, rounded half up to the functional currency's minor units.
    ``functional`` is the line's signed functional amount (debit positive)."""
    field = f"lines.{i}"
    none = {"txn_currency": None, "txn_debit": None, "txn_credit": None, "exchange_rate": None,
            "rate_at": None, "rate_source": ""}  # fmt: skip
    if not currency or currency == entity.functional_currency:
        if amount or rate:
            raise _invalid(f"{field}.txn_currency", f"Line {i + 1}: choose the foreign currency.")
        return none
    if not entity.multi_currency_enabled:
        raise _invalid(f"{field}.txn_currency",
                       f"Line {i + 1}: foreign currency is off for this entity. Switch it on in "
                       "the ledger settings first.")  # fmt: skip
    try:
        unit = get_currency(currency)
        home = get_currency(entity.functional_currency)
    except UnknownCurrencyError:
        raise _invalid(f"{field}.txn_currency", "Use a supported ISO 4217 currency code.") from None
    try:
        value, factor = Decimal(amount or ""), Decimal(rate or "")
    except InvalidOperation:
        raise _invalid(f"{field}.txn_amount", f"Line {i + 1}: enter the amount and the rate as "
                       "numbers.") from None  # fmt: skip
    step = Decimal(1).scaleb(-unit.minor_units)
    if not value.is_finite() or value <= 0 or value != value.quantize(step):
        raise _invalid(f"{field}.txn_amount", f"Line {i + 1}: enter a positive amount in "
                       f"{currency} with at most {unit.minor_units} decimals.")  # fmt: skip
    exponent = factor.as_tuple().exponent
    if (not factor.is_finite() or not Decimal(0) < factor < MAX_RATE
            or (isinstance(exponent, int) and exponent < -10)):  # fmt: skip
        raise _invalid(f"{field}.exchange_rate", f"Line {i + 1}: enter a positive rate with at "
                       "most 10 decimals.")  # fmt: skip
    if rate_at is None or not rate_source.strip():
        raise _invalid(f"{field}.rate_source", f"Line {i + 1}: give the date and time the rate "
                       "applied and where it comes from (bank, invoice, stored rate).")  # fmt: skip
    converted = (value * factor).quantize(Decimal(1).scaleb(-home.minor_units), ROUND_HALF_UP)
    if converted != abs(functional):
        raise _invalid(f"{field}.txn_amount",
                       f"Line {i + 1}: {value} {currency} at {factor} is {converted} "
                       f"{entity.functional_currency}, not {abs(functional)}.")  # fmt: skip
    debit = functional > 0
    return {"txn_currency": currency, "txn_debit": value if debit else Decimal(0),
            "txn_credit": Decimal(0) if debit else value, "exchange_rate": factor,
            "rate_at": rate_at, "rate_source": rate_source.strip()[:200]}  # fmt: skip


@transaction.atomic
def set_currency_settings(ctx: WorkspaceContext, entity_id: UUID, *, enabled: bool,
                          fx_account_id: UUID | None) -> LedgerSettings:  # fmt: skip
    """Switch foreign currency on or off, with the account exchange differences go to (an income
    or expense account, postable and active). Switching off keeps every posted line."""
    from .entries import ledger_settings  # noqa: PLC0415 (entries imports this module)

    entity = get_entity(ctx, entity_id, "ledger.settings.manage")
    current = ledger_settings(ctx, entity.id)
    account = None
    if fx_account_id is not None:
        account = Account.objects.filter(legal_entity=entity, id=fx_account_id).first()
        if (account is None or not account.is_postable or account.status != "ACTIVE"
                or account.type not in ("INCOME", "EXPENSE")):  # fmt: skip
            raise _invalid("fx_account_id", "Choose an active income or expense account for "
                           "exchange differences.")  # fmt: skip
    if enabled and account is None:
        raise _invalid("fx_account_id", "Choose the account for exchange differences first.")
    previous = str(current.fx_account_id) if current.fx_account_id else None
    before = {"enabled": entity.multi_currency_enabled, "fx_account": previous}
    current.fx_account = account
    current.updated_by = ctx.user
    current.save(update_fields=["fx_account", "updated_by"])
    set_multi_currency(ctx, entity, enabled)
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
          action="ledger.currency_settings.updated", subject_type="ledger_settings",
          subject_id=current.id, entity_id=entity.id,
          changes={"before": before, "after": {"enabled": enabled, "fx_account": str(
              account.id) if account else None}})  # fmt: skip
    return current
