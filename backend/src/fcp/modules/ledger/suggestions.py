"""Help for data entry (V1-2i, #231; the owner's request of 2026-11-23).

- **Favourite VAT codes**: each user stars the codes they use for a legal entity; the picker lists
  them first.
- **Usage**: how often each VAT code was used, and the code most used with each account.
- **Typing suggestions** for descriptions, memos and references, ranked by how often and how
  recently each was used, like a search box that remembers what you typed.

Everything comes from this legal entity's own entries (row-level security keeps each workspace
apart; every query is also limited to the entity). Nothing is decided for the user: a suggestion
is only offered, and the VAT code stays the user's choice. No AI and no outside service.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Case, Count, IntegerField, Max, Q, QuerySet, Value, When

from fcp.core.errors import NotFoundError
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import JournalEntry, JournalLine, VatCode, VatFavourite

READ = "ledger.entry.read"
MAX_SUGGESTIONS = 20
MAX_QUERY = 100
Field = Literal["description", "memo", "reference"]


@dataclass(frozen=True)
class Suggestion:
    value: str
    uses: int
    last_used: datetime


@dataclass(frozen=True)
class CodeUse:
    vat_code_id: str
    uses: int


@dataclass(frozen=True)
class AccountCode:
    account_id: UUID
    vat_code_id: str
    uses: int


@dataclass(frozen=True)
class Usage:
    codes: list[CodeUse]
    accounts: list[AccountCode]


def favourites(ctx: WorkspaceContext, entity_id: UUID) -> list[str]:
    """The VAT codes this user starred for the entity, in the order they were starred."""
    get_entity(ctx, entity_id, READ)
    return list(VatFavourite.objects.filter(legal_entity_id=entity_id, user=ctx.user)
                .order_by("created_at").values_list("vat_code_id", flat=True))  # fmt: skip


@transaction.atomic
def set_favourite(ctx: WorkspaceContext, entity_id: UUID, vat_code_id: str, *, on: bool) -> None:
    """Star or unstar a VAT code; doing it twice changes nothing."""
    get_entity(ctx, entity_id, READ)
    if not VatCode.objects.filter(id=vat_code_id).exists():
        raise NotFoundError("VAT code not found.")
    if on:
        VatFavourite.objects.get_or_create(tenant=ctx.tenant, legal_entity_id=entity_id,
                                           user=ctx.user, vat_code_id=vat_code_id)  # fmt: skip
    else:
        VatFavourite.objects.filter(legal_entity_id=entity_id, user=ctx.user,
                                    vat_code_id=vat_code_id).delete()  # fmt: skip


def _lines(entity_id: UUID) -> QuerySet[JournalLine]:
    return JournalLine.objects.filter(entry__legal_entity_id=entity_id).exclude(
        entry__status=JournalEntry.Status.VOID
    )


def usage(ctx: WorkspaceContext, entity_id: UUID) -> Usage:
    """How often each VAT code was used, and each account's most used code (ties: the code used
    most recently)."""
    get_entity(ctx, entity_id, READ)
    coded = _lines(entity_id).filter(vat_code__isnull=False)
    codes = [CodeUse(vat_code_id=r["vat_code_id"], uses=r["uses"])
             for r in coded.values("vat_code_id").annotate(uses=Count("id"))
             .order_by("-uses", "vat_code_id")]  # fmt: skip
    best: dict[UUID, AccountCode] = {}
    rows = (coded.values("account_id", "vat_code_id")
            .annotate(uses=Count("id"), last=Max("created_at"))
            .order_by("account_id", "-uses", "-last"))  # fmt: skip
    for r in rows:
        best.setdefault(r["account_id"], AccountCode(account_id=r["account_id"],
                                                     vat_code_id=r["vat_code_id"],
                                                     uses=r["uses"]))  # fmt: skip
    return Usage(codes=codes, accounts=list(best.values()))


def suggest(ctx: WorkspaceContext, entity_id: UUID, field: Field, text: str,
            limit: int = 8) -> list[Suggestion]:  # fmt: skip
    """Values used before in this entity's entries that contain ``text`` (any case): those that
    start with it first, then the most used, then the most recent."""
    get_entity(ctx, entity_id, READ)
    text = text.strip()[:MAX_QUERY]
    limit = max(1, min(limit, MAX_SUGGESTIONS))
    rows: QuerySet[Any]
    if field == "description":
        rows = JournalEntry.objects.filter(legal_entity_id=entity_id).exclude(
            Q(status=JournalEntry.Status.VOID) | Q(entry_type=JournalEntry.EntryType.REVERSAL)
        )
    else:
        rows = _lines(entity_id)
    rows = rows.exclude(**{field: ""})
    if text:
        rows = rows.filter(**{f"{field}__icontains": text})
    ranked = (rows.values(field)
              .annotate(uses=Count("id"), last=Max("created_at"),
                        starts=Case(When(**{f"{field}__istartswith": text}, then=Value(1)),
                                    default=Value(0), output_field=IntegerField()))
              .order_by("-starts", "-uses", "-last", field)[:limit])  # fmt: skip
    return [Suggestion(value=r[field], uses=r["uses"], last_used=r["last"]) for r in ranked]
