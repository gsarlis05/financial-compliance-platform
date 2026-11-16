"""Public interface of the ``metrics`` module and its HTTP routes (M2-6: taxonomy and mapping).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import date, datetime
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import TaxonomyLine
from .services import Completeness, completeness, current_mapping
from .taxonomy import DEFAULT_TAXONOMY

__all__ = ["DEFAULT_TAXONOMY", "Completeness", "TaxonomyLine", "completeness", "current_mapping",
           "router"]  # fmt: skip

router = Router(tags=["metrics"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class LineOut(Schema):
    code: str
    name: str
    name_el: str
    statement: str
    section: str
    account_types: list[str]
    direction: str
    order: int


def _line_out(line: TaxonomyLine) -> LineOut:
    return LineOut(code=line.code, name=line.name, name_el=line.name_el,
                   statement=line.statement, section=line.section,
                   account_types=line.account_types.split(","), direction=line.direction,
                   order=line.order)  # fmt: skip


@router.get(f"{BASE}/taxonomy", response=list[LineOut])
@requires("ledger.account.read")
def taxonomy(request: HttpRequest, slug: str, entity_id: UUID) -> list[LineOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_line_out(ln) for ln in services.taxonomy_lines(ctx, entity_id)]


class AsOf(Schema):
    as_of: date


class MappingRowOut(Schema):
    account_id: UUID
    account_code: str
    account_name: str
    account_type: str
    line_code: str | None
    balance: str = Field(description="Posted debits minus credits up to as_of")
    has_activity: bool


def _row_out(r: services.MappingRow) -> MappingRowOut:
    return MappingRowOut(account_id=r.account.id, account_code=r.account.code,
                         account_name=r.account.name, account_type=r.account.type,
                         line_code=r.line.code if r.line else None,
                         balance=f"{r.net_debit:.2f}", has_activity=r.has_activity)  # fmt: skip


@router.get(f"{BASE}/account-mapping", response=list[MappingRowOut])
@requires("ledger.account.read")
def mapping(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[AsOf]
) -> list[MappingRowOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_row_out(r) for r in services.mapping_rows(ctx, entity_id, as_of=q.as_of)]


class CompletenessOut(Schema):
    as_of: date
    taxonomy: str
    complete: bool
    mapped: int
    unmapped_blocking: list[MappingRowOut]
    unmapped_warning: list[MappingRowOut]
    unmapped_idle: int


@router.get(f"{BASE}/account-mapping/completeness", response=CompletenessOut)
@requires("ledger.account.read")
def mapping_completeness(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[AsOf]
) -> CompletenessOut:
    ctx = workspace_ctx(request, slug, entity_id)
    result = completeness(ctx, entity_id, as_of=q.as_of)
    return CompletenessOut(
        as_of=result.as_of, taxonomy=result.version, complete=result.complete,
        mapped=result.mapped,
        unmapped_blocking=[_row_out(r) for r in result.unmapped_blocking],
        unmapped_warning=[_row_out(r) for r in result.unmapped_warning],
        unmapped_idle=result.unmapped_idle,
    )  # fmt: skip


class MappingIn(Schema):
    line_code: str | None = Field(default=None, max_length=40, description="None: unmap")


class MappingOut(Schema):
    account_id: UUID
    line_code: str | None


@router.put(f"{BASE}/account-mapping/{{uuid:account_id}}", response=MappingOut)
@requires("ledger.account.manage")
def set_mapping(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID, payload: MappingIn
) -> MappingOut:
    ctx = workspace_ctx(request, slug, entity_id)
    line = services.set_mapping(ctx, entity_id, account_id, payload.line_code)
    return MappingOut(account_id=account_id, line_code=line.code if line else None)


class DefaultsIn(Schema):
    template: str = Field(default="cy_business", max_length=40)


class DefaultsOut(Schema):
    mapped: int


@router.post(f"{BASE}/account-mapping/apply-defaults", response=DefaultsOut)
@requires("ledger.account.manage")
def apply_defaults(
    request: HttpRequest, slug: str, entity_id: UUID, payload: DefaultsIn
) -> DefaultsOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return DefaultsOut(mapped=services.apply_defaults(ctx, entity_id, payload.template))


class HistoryOut(Schema):
    line_code: str
    created_at: datetime
    superseded_at: datetime | None
    created_by_id: UUID


@router.get(f"{BASE}/account-mapping/{{uuid:account_id}}/history", response=list[HistoryOut])
@requires("ledger.account.read")
def mapping_history(
    request: HttpRequest, slug: str, entity_id: UUID, account_id: UUID
) -> list[HistoryOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        HistoryOut(
            line_code=r.line.code,
            created_at=r.created_at,
            superseded_at=r.superseded_at,
            created_by_id=r.created_by_id,
        )
        for r in services.mapping_history(ctx, entity_id, account_id)
    ]
