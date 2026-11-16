"""Exchange rates as data (M6F-1, #80): recorded with their source, never changed, never fetched
live (doc 10 §13). Nothing converts amounts yet: multi-currency transactions stay disabled until
their full accounting treatment (IAS 21: translation, revaluation, FX gains and losses, rounding)
is implemented and tested."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.db import IntegrityError, transaction

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.core.money.currency import get_currency
from fcp.core.money.errors import UnknownCurrencyError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import ExchangeRate

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
