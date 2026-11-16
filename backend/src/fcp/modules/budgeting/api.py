"""Public interface of the ``budgeting`` module and its HTTP routes (M4-1: budgets and versions).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``. Every budget amount has
nature BUDGET (doc 10 P2); quarter and year totals are always sums of months.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import services
from .models import Budget, BudgetEvent, BudgetVersion
from .services import BudgetInput, BudgetView, LineInput, VersionView, fiscal_months

__all__ = ["Budget", "BudgetVersion", "BudgetView", "VersionView", "fiscal_months", "router"]

router = Router(tags=["budgeting"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
SIGNED = r"^-?\d{1,15}(\.\d{1,2})?$"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class BudgetSettingsIO(Schema):
    sod_required: bool = Field(description="The submitter of a version cannot approve it")


class BudgetVersionOut(Schema):
    id: UUID
    number: int
    status: str
    reason: str
    supersedes_id: UUID | None
    content_hash: str
    created_by_id: UUID
    submitted_by_id: UUID | None
    submitted_at: datetime | None
    approved_by_id: UUID | None
    approved_at: datetime | None
    sod_applied: bool | None
    locked_at: datetime | None
    superseded_at: datetime | None


class BudgetOut(Schema):
    id: UUID
    name: str
    kind: str
    fiscal_year_id: UUID
    fiscal_year_start: date
    fiscal_year_end: date
    dimension_value_id: UUID | None
    original_version_id: UUID | None = Field(description="The first version ever approved")
    current_version_id: UUID | None = Field(description="The approved or locked version in force")
    open_version_id: UUID | None = Field(description="The draft or submitted version, if any")
    versions: list[BudgetVersionOut]


def _version_out(v: BudgetVersion) -> BudgetVersionOut:
    return BudgetVersionOut(
        id=v.id,
        number=v.number,
        status=v.status,
        reason=v.reason,
        supersedes_id=v.supersedes_id,
        content_hash=v.content_hash,
        created_by_id=v.created_by_id,
        submitted_by_id=v.submitted_by_id,
        submitted_at=v.submitted_at,
        approved_by_id=v.approved_by_id,
        approved_at=v.approved_at,
        sod_applied=v.sod_applied,
        locked_at=v.locked_at,
        superseded_at=v.superseded_at,
    )


def _budget_out(view: BudgetView) -> BudgetOut:
    b = view.budget
    return BudgetOut(
        id=b.id,
        name=b.name,
        kind=b.kind,
        fiscal_year_id=b.fiscal_year_id,
        fiscal_year_start=b.fiscal_year_start,
        fiscal_year_end=b.fiscal_year_end,
        dimension_value_id=b.dimension_value_id,
        original_version_id=view.original.id if view.original else None,
        current_version_id=view.current.id if view.current else None,
        open_version_id=view.open.id if view.open else None,
        versions=[_version_out(v) for v in view.versions],
    )


class BudgetLineOut(Schema):
    id: UUID
    seq: int
    taxonomy_code: str | None
    taxonomy_name: str | None
    direction: str | None = Field(description="HIGHER_BETTER or LOWER_BETTER (taxonomy lines)")
    account_id: UUID | None
    dimension_value_id: UUID | None
    method: str
    method_params: dict[str, Any]
    note: str
    nature: Literal["BUDGET"] = "BUDGET"
    amounts: list[str] = Field(description="One per month of the fiscal year, in order")
    quarters: list[str] = Field(description="Sums of the months, by fiscal quarter")
    total: str


class BudgetVersionDetailOut(BudgetVersionOut):
    budget_id: UUID
    months: list[date]
    lines: list[BudgetLineOut]
    month_totals: list[str]
    total: str


def _detail_out(view: VersionView) -> BudgetVersionDetailOut:
    lines, month_totals = [], [Decimal(0)] * len(view.months)
    for ln in view.lines:
        amounts = view.line_amounts(ln)
        month_totals = [a + b for a, b in zip(month_totals, amounts, strict=True)]
        tax = ln.taxonomy_line
        lines.append(
            BudgetLineOut(
                id=ln.id,
                seq=ln.seq,
                taxonomy_code=tax.code if tax else None,
                taxonomy_name=tax.name if tax else None,
                direction=tax.direction if tax else None,
                account_id=ln.account_id,
                dimension_value_id=ln.dimension_value_id,
                method=ln.method,
                method_params=ln.method_params,
                note=ln.note,
                amounts=[_money(a) for a in amounts],
                quarters=[_money(q) for q in services.quarters(view.months, amounts)],
                total=_money(sum(amounts, Decimal(0))),
            )
        )
    base = _version_out(view.version).dict()
    return BudgetVersionDetailOut(
        **base,
        budget_id=view.budget.id,
        months=view.months,
        lines=lines,
        month_totals=[_money(t) for t in month_totals],
        total=_money(sum(month_totals, Decimal(0))),
    )


class BudgetIn(Schema):
    name: str = Field(max_length=120)
    fiscal_year_id: UUID
    kind: Literal["ANNUAL", "DEPARTMENTAL", "PROJECT"] = "ANNUAL"
    dimension_value_id: UUID | None = None


class BudgetLineIn(Schema):
    taxonomy_code: str | None = Field(None, max_length=40)
    account_id: UUID | None = None
    dimension_value_id: UUID | None = None
    amounts: dict[date, Annotated[str, Field(pattern=SIGNED)]] = Field(
        default_factory=dict, description="Month (first day) → amount; missing months are 0"
    )
    method: Literal["MANUAL", "EVEN", "SEASONAL", "PROFILE", "DRIVER"] = "MANUAL"
    note: str = Field("", max_length=300)


class BudgetLinesIn(Schema):
    lines: list[BudgetLineIn] = Field(max_length=services.MAX_LINES)


class BudgetCommentIn(Schema):
    comment: str = Field("", max_length=500)


class BudgetReasonIn(Schema):
    reason: str = Field(max_length=500)


class BudgetsQuery(Schema):
    fiscal_year_id: UUID | None = None


class BudgetEventOut(Schema):
    version_number: int
    seq: int
    action: str
    actor_id: UUID
    actor_name: str
    comment: str
    at: datetime


@router.get(f"{BASE}/budget-settings", response=BudgetSettingsIO)
@requires("budget.read")
def get_settings(request: HttpRequest, slug: str, entity_id: UUID) -> BudgetSettingsIO:
    s = services.get_settings(workspace_ctx(request, slug, entity_id), entity_id)
    return BudgetSettingsIO(sod_required=s.sod_required)


@router.put(f"{BASE}/budget-settings", response=BudgetSettingsIO)
@requires("budget.settings.manage")
def put_settings(
    request: HttpRequest, slug: str, entity_id: UUID, payload: BudgetSettingsIO
) -> BudgetSettingsIO:
    ctx = workspace_ctx(request, slug, entity_id)
    s = services.set_settings(ctx, entity_id, sod_required=payload.sod_required)
    return BudgetSettingsIO(sod_required=s.sod_required)


@router.get(f"{BASE}/budgets", response=list[BudgetOut])
@requires("budget.read")
def list_budgets(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[BudgetsQuery]
) -> list[BudgetOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_budget_out(v) for v in services.list_budgets(ctx, entity_id, q.fiscal_year_id)]


@router.post(f"{BASE}/budgets", response={201: BudgetOut})
@requires("budget.edit")
def create_budget(
    request: HttpRequest, slug: str, entity_id: UUID, payload: BudgetIn
) -> Status[BudgetOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    view = services.create_budget(
        ctx,
        entity_id,
        BudgetInput(payload.name, payload.fiscal_year_id, payload.kind, payload.dimension_value_id),
    )
    return Status(201, _budget_out(view))


@router.get(f"{BASE}/budgets/{{uuid:budget_id}}", response=BudgetOut)
@requires("budget.read")
def get_budget(request: HttpRequest, slug: str, entity_id: UUID, budget_id: UUID) -> BudgetOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _budget_out(services.get_budget(ctx, entity_id, budget_id))


@router.get(f"{BASE}/budgets/{{uuid:budget_id}}/events", response=list[BudgetEventOut])
@requires("budget.read")
def budget_events(
    request: HttpRequest, slug: str, entity_id: UUID, budget_id: UUID
) -> list[BudgetEventOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    rows: list[BudgetEvent] = services.events(ctx, entity_id, budget_id)
    return [
        BudgetEventOut(
            version_number=e.version.number,
            seq=e.seq,
            action=e.action,
            actor_id=e.actor_id,
            actor_name=e.actor.display_name or e.actor.email,
            comment=e.comment,
            at=e.created_at,
        )
        for e in rows
    ]


@router.get(f"{BASE}/budget-versions/{{uuid:version_id}}", response=BudgetVersionDetailOut)
@requires("budget.read")
def get_version(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID
) -> BudgetVersionDetailOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail_out(services.get_version(ctx, entity_id, version_id))


@router.put(f"{BASE}/budget-versions/{{uuid:version_id}}/lines", response=BudgetVersionDetailOut)
@requires("budget.edit")
def save_lines(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: BudgetLinesIn
) -> BudgetVersionDetailOut:
    """Replace every line of a draft version."""
    ctx = workspace_ctx(request, slug, entity_id)
    lines = [
        LineInput(
            taxonomy_code=ln.taxonomy_code,
            account_id=ln.account_id,
            dimension_value_id=ln.dimension_value_id,
            amounts={m: Decimal(a) for m, a in ln.amounts.items()},
            method=ln.method,
            note=ln.note,
        )
        for ln in payload.lines
    ]
    return _detail_out(services.save_lines(ctx, entity_id, version_id, lines))


@router.put(f"{BASE}/budget-versions/{{uuid:version_id}}/reason", response=BudgetVersionOut)
@requires("budget.edit")
def set_reason(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: BudgetReasonIn
) -> BudgetVersionOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _version_out(services.set_reason(ctx, entity_id, version_id, payload.reason))


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/submit", response=BudgetVersionOut)
@requires("budget.edit")
def submit(request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID) -> BudgetVersionOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _version_out(services.submit(ctx, entity_id, version_id))


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/return", response=BudgetVersionOut)
@requires("budget.approve")
def return_to_draft(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: BudgetCommentIn
) -> BudgetVersionOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _version_out(services.return_to_draft(ctx, entity_id, version_id, payload.comment))


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/approve", response=BudgetVersionOut)
@requires("budget.approve")
def approve(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: BudgetCommentIn
) -> BudgetVersionOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _version_out(services.approve(ctx, entity_id, version_id, payload.comment))


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/lock", response=BudgetVersionOut)
@requires("budget.approve")
def lock(request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID) -> BudgetVersionOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _version_out(services.lock(ctx, entity_id, version_id))


@router.post(
    f"{BASE}/budget-versions/{{uuid:version_id}}/revise", response={201: BudgetVersionDetailOut}
)
@requires("budget.edit")
def revise(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: BudgetReasonIn
) -> Status[BudgetVersionDetailOut]:
    """Start a revision of the current version (a new draft with its lines and a reason)."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _detail_out(services.revise(ctx, entity_id, version_id, payload.reason)))
