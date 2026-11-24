"""Counterpart hints between a business and the owner's personal books (M5-3, doc 11 §4.2).

Nothing moves between workspaces automatically. A person who belongs to both a business and a
personal workspace can **opt in** by linking, in the personal workspace, one business account
(e.g. the director's loan account) to a personal money account and income category.

- The link stores only references. Business figures are read by the person in the business
  workspace, with their own permissions there (that account's general ledger, ``reports.read``),
  so each request stays in exactly one workspace and no query crosses workspaces.
- Each payment to the person (a debit on the linked account) is offered as a **suggestion**. It is
  recorded in the personal books only when the person confirms it here, as a "received"
  transaction; or it can be dismissed. Either decision is kept, once per business entry.
- The business workspace never sees the personal workspace, the link or the decisions.
"""

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from django.db import IntegrityError, transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, NotFoundError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext

from .models import CounterpartDecision, CounterpartLink

__all__ = ["CounterpartDecision", "CounterpartLink"]
from .services import (
    MONEY,
    READ,
    RECEIVED,
    WRITE,
    TransactionInput,
    _account,
    _amount,
    _entity,
    _invalid,
    record,
)

MAX_LABEL, MAX_REF = 200, 64


@dataclass(frozen=True)
class LinkInput:
    business_slug: str
    business_entity_id: UUID
    business_account_id: UUID
    label: str
    account_id: UUID
    category_id: UUID
    since: date


def _text(value: str, name: str, limit: int) -> str:
    text = value.strip()
    if not text or len(text) > limit:
        raise _invalid(name, f"Enter 1 to {limit} characters.")
    return text


@transaction.atomic
def create_link(ctx: WorkspaceContext, entity_id: UUID, data: LinkInput) -> CounterpartLink:
    """Opt in: link a business account to a personal money account and income category."""
    entity = _entity(ctx, entity_id, WRITE)
    if data.business_slug == ctx.tenant.slug:
        raise _invalid("business_slug", "Choose one of your business workspaces.")
    money = _account(ctx, entity, data.account_id, MONEY, "account_id")
    category = _account(ctx, entity, data.category_id, ("INCOME",), "category_id")
    link = CounterpartLink.objects.create(
        tenant_id=ctx.tenant.id,
        legal_entity_id=entity,
        business_slug=_text(data.business_slug, "business_slug", MAX_REF),
        business_entity_id=data.business_entity_id,
        business_account_id=data.business_account_id,
        label=_text(data.label, "label", MAX_LABEL),
        account_id=money.id,
        category_id=category.id,
        since=data.since,
        created_by=ctx.user,
    )
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="personal.counterpart.linked",
        subject_type="counterpart_link",
        subject_id=link.id,
        entity_id=entity,
        changes={"label": link.label, "account": money.code, "category": category.code,
                 "since": data.since.isoformat()},
    )  # fmt: skip
    return link


def links(ctx: WorkspaceContext, entity_id: UUID) -> list[CounterpartLink]:
    """Active links, oldest first."""
    entity = _entity(ctx, entity_id, READ)
    rows = CounterpartLink.objects.filter(legal_entity_id=entity, revoked_at__isnull=True)
    return list(rows.order_by("created_at"))


def _link(
    ctx: WorkspaceContext, entity_id: UUID, link_id: UUID, permission: str
) -> CounterpartLink:
    entity = _entity(ctx, entity_id, permission)
    link = CounterpartLink.objects.filter(
        id=link_id, legal_entity_id=entity, revoked_at__isnull=True
    ).first()
    if link is None:
        raise NotFoundError("Link not found.")
    return link


@transaction.atomic
def revoke_link(ctx: WorkspaceContext, entity_id: UUID, link_id: UUID) -> None:
    """Opt out. Earlier decisions and recorded transactions are kept."""
    link = _link(ctx, entity_id, link_id, WRITE)
    link.revoked_at = timezone.now()
    link.save(update_fields=["revoked_at"])
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="personal.counterpart.revoked",
        subject_type="counterpart_link",
        subject_id=link.id,
        entity_id=link.legal_entity_id,
        changes={"label": link.label},
    )


def decided(ctx: WorkspaceContext, entity_id: UUID, link_id: UUID) -> list[CounterpartDecision]:
    """Decisions taken for a link, so the suggestions already handled are not offered again."""
    link = _link(ctx, entity_id, link_id, READ)
    return list(CounterpartDecision.objects.filter(link=link).order_by("created_at"))


@dataclass(frozen=True)
class DecisionInput:
    business_entry_id: UUID
    day: date
    amount: str
    description: str


def _decide(
    ctx: WorkspaceContext,
    link: CounterpartLink,
    data: DecisionInput,
    decision: str,
    personal_entry_id: UUID | None,
) -> CounterpartDecision:
    amount = _amount(data.amount)
    try:
        with transaction.atomic():
            made = CounterpartDecision.objects.create(
                tenant_id=ctx.tenant.id,
                link=link,
                business_entry_id=data.business_entry_id,
                decision=decision,
                amount=amount,
                entry_date=data.day,
                personal_entry_id=personal_entry_id,
                decided_by=ctx.user,
            )
    except IntegrityError:
        raise ConflictError("This payment was already confirmed or dismissed.") from None
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=f"personal.counterpart.{decision.lower()}",
        subject_type="counterpart_decision",
        subject_id=made.id,
        entity_id=link.legal_entity_id,
        changes={"link": str(link.id), "business_entry": str(data.business_entry_id),
                 "amount": f"{amount:.2f}", "date": data.day.isoformat()},
    )  # fmt: skip
    return made


@transaction.atomic
def confirm(
    ctx: WorkspaceContext, entity_id: UUID, link_id: UUID, data: DecisionInput
) -> CounterpartDecision:
    """Record a suggested payment in the personal books: money received into the link's account
    from its income category. The person confirms the date, amount and description."""
    link = _link(ctx, entity_id, link_id, WRITE)
    if CounterpartDecision.objects.filter(
        link=link, business_entry_id=data.business_entry_id
    ).exists():
        raise ConflictError("This payment was already confirmed or dismissed.")
    entry = record(
        ctx,
        link.legal_entity_id,
        TransactionInput(
            kind=RECEIVED,
            day=data.day,
            amount=data.amount,
            description=data.description,
            account_id=link.account_id,
            category_id=link.category_id,
        ),
    )
    return _decide(ctx, link, data, CounterpartDecision.Decision.CONFIRMED, entry.id)


@transaction.atomic
def dismiss(
    ctx: WorkspaceContext, entity_id: UUID, link_id: UUID, data: DecisionInput
) -> CounterpartDecision:
    """Not for the personal books (e.g. a payment on the person's behalf). Nothing is posted."""
    link = _link(ctx, entity_id, link_id, WRITE)
    return _decide(ctx, link, data, CounterpartDecision.Decision.DISMISSED, None)
