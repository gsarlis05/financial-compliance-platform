"""Public interface of the ``budgeting`` module and its HTTP routes (M4-1: budgets and versions).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``. Every budget amount has
nature BUDGET (doc 10 P2); quarter and year totals are always sums of months.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from ninja import Field, File, Query, Router, Schema, Status
from ninja.files import UploadedFile

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import excel, services, variance
from .models import Budget, BudgetEvent, BudgetVersion
from .services import (
    ApprovedPlan,
    BudgetInput,
    BudgetView,
    LineInput,
    VersionView,
    approved_plan,
    fiscal_months,
)

__all__ = [
    "ApprovedPlan",
    "Budget",
    "BudgetVersion",
    "BudgetView",
    "VersionView",
    "approved_plan",
    "fiscal_months",
    "router",
]

router = Router(tags=["budgeting"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
SIGNED = r"^-?\d{1,15}(\.\d{1,2})?$"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


class BudgetSettingsIO(Schema):
    sod_required: bool = Field(description="The submitter of a version cannot approve it")
    explain_above_amount: str = Field(description="Explain variances of at least this amount")
    explain_above_percent: str = Field(description="... and at least this percentage")


class BudgetSettingsIn(Schema):
    """Fields left out keep their value."""

    sod_required: bool | None = None
    explain_above_amount: Annotated[str, Field(pattern=r"^\d{1,15}(\.\d{1,2})?$")] | None = None
    explain_above_percent: Annotated[str, Field(pattern=r"^\d{1,5}(\.\d{1,2})?$")] | None = None


def _settings_out(s: services.Settings) -> BudgetSettingsIO:
    return BudgetSettingsIO(
        sod_required=s.sod_required,
        explain_above_amount=_money(s.explain_above_amount),
        explain_above_percent=_money(s.explain_above_percent),
    )


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
    phasing_note: str = Field("", description="How the phasing was done, e.g. a fallback")
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
                phasing_note=str(ln.method_params.get("note", "")),
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


Number = Annotated[str, Field(pattern=r"^-?\d{1,15}(\.\d{1,6})?$")]


class BudgetPhasingParams(Schema):
    """EVEN and SEASONAL: ``annual``. PROFILE: ``annual`` and ``weights`` (one per month).
    DRIVER: ``quantity`` and ``rate`` (one value, or one per month)."""

    annual: Annotated[str, Field(pattern=SIGNED)] | None = None
    weights: list[Number] | None = Field(None, max_length=13)
    quantity: Number | list[Number] | None = None
    rate: Number | list[Number] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.dict().items() if v is not None}


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
    params: BudgetPhasingParams | None = Field(None, description="For methods other than MANUAL")
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
    return _settings_out(services.get_settings(workspace_ctx(request, slug, entity_id), entity_id))


@router.put(f"{BASE}/budget-settings", response=BudgetSettingsIO)
@requires("budget.settings.manage")
def put_settings(
    request: HttpRequest, slug: str, entity_id: UUID, payload: BudgetSettingsIn
) -> BudgetSettingsIO:
    ctx = workspace_ctx(request, slug, entity_id)
    old = services.get_settings(ctx, entity_id)
    new = services.Settings(
        old.sod_required if payload.sod_required is None else payload.sod_required,
        old.explain_above_amount
        if payload.explain_above_amount is None
        else Decimal(payload.explain_above_amount),
        old.explain_above_percent
        if payload.explain_above_percent is None
        else Decimal(payload.explain_above_percent),
    )
    return _settings_out(services.set_settings(ctx, entity_id, new))


@router.get(f"{BASE}/budgets", response=list[BudgetOut])
@requires("budget.department")
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
@requires("budget.department")
def get_budget(request: HttpRequest, slug: str, entity_id: UUID, budget_id: UUID) -> BudgetOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _budget_out(services.get_budget(ctx, entity_id, budget_id))


@router.get(f"{BASE}/budgets/{{uuid:budget_id}}/events", response=list[BudgetEventOut])
@requires("budget.department")
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
@requires("budget.department")
def get_version(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID
) -> BudgetVersionDetailOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _detail_out(services.get_version(ctx, entity_id, version_id))


@router.put(f"{BASE}/budget-versions/{{uuid:version_id}}/lines", response=BudgetVersionDetailOut)
@requires("budget.department")
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
            method_params=ln.params.as_dict() if ln.params else {},
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


class BudgetPhasePreviewIn(Schema):
    taxonomy_code: str | None = Field(None, max_length=40)
    account_id: UUID | None = None
    method: Literal["EVEN", "SEASONAL", "PROFILE", "DRIVER"]
    params: BudgetPhasingParams


class BudgetPhasePreviewOut(Schema):
    months: list[date]
    amounts: list[str]
    total: str
    note: str
    nature: Literal["BUDGET"] = "BUDGET"


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/phase", response=BudgetPhasePreviewOut)
@requires("budget.department")
def preview_phasing(
    request: HttpRequest,
    slug: str,
    entity_id: UUID,
    version_id: UUID,
    payload: BudgetPhasePreviewIn,
) -> BudgetPhasePreviewOut:
    """What a phasing method gives for one line; nothing is saved."""
    ctx = workspace_ctx(request, slug, entity_id)
    line = LineInput(
        taxonomy_code=payload.taxonomy_code,
        account_id=payload.account_id,
        method=payload.method,
        method_params=payload.params.as_dict(),
    )
    months, amounts, note = services.preview_phasing(ctx, entity_id, version_id, line)
    return BudgetPhasePreviewOut(
        months=months,
        amounts=[_money(a) for a in amounts],
        total=_money(sum(amounts, Decimal(0))),
        note=note,
    )


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get(f"{BASE}/budget-versions/{{uuid:version_id}}/export")
@requires("budget.department")
def export_version(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID
) -> HttpResponse:
    """The version as an .xlsx workbook, which is also the import template."""
    ctx = workspace_ctx(request, slug, entity_id)
    name, content = services.export_version(ctx, entity_id, version_id)
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{name}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


class BudgetImportProblemOut(Schema):
    row: int
    column: str
    message: str


class BudgetImportChangeOut(Schema):
    line: str
    kind: Literal["ADDED", "REMOVED", "CHANGED"]
    before: str
    after: str
    months_changed: int


class BudgetImportOut(Schema):
    applied: bool
    problems: list[BudgetImportProblemOut]
    changes: list[BudgetImportChangeOut]
    unchanged: int
    draft_hash: str = Field(description="Send it back with apply=true to save this preview")


class BudgetImportQuery(Schema):
    apply: bool = False
    expected_hash: str = Field("", max_length=64)


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/import", response=BudgetImportOut)
@requires("budget.department")
def import_version(
    request: HttpRequest,
    slug: str,
    entity_id: UUID,
    version_id: UUID,
    q: Query[BudgetImportQuery],
    file: File[UploadedFile],
) -> BudgetImportOut:
    """Check a workbook and preview the changes; with ``apply=true`` and the preview's hash,
    replace the draft's lines. Nothing is saved while any problem remains."""
    ctx = workspace_ctx(request, slug, entity_id)
    data = file.read(excel.MAX_BYTES + 1)
    result = services.import_lines(
        ctx, entity_id, version_id, data, apply=q.apply, expected_hash=q.expected_hash
    )
    return BudgetImportOut(
        applied=result.applied,
        problems=[
            BudgetImportProblemOut(row=p.row, column=p.column, message=p.message)
            for p in result.problems[:200]
        ],
        changes=[
            BudgetImportChangeOut(
                line=c.key,
                kind=c.kind,
                before=_money(c.before),
                after=_money(c.after),
                months_changed=c.months_changed,
            )
            for c in result.changes
        ],
        unchanged=result.unchanged,
        draft_hash=result.draft_hash,
    )


class BudgetOwnerIO(Schema):
    dimension_value_id: UUID
    user_id: UUID


class BudgetOwnerOut(BudgetOwnerIO):
    user_name: str


class BudgetOwnersIn(Schema):
    owners: list[BudgetOwnerIO] = Field(max_length=500)


class BudgetMemberOut(Schema):
    user_id: UUID
    name: str


def _owners_out(rows: list[Any]) -> list[BudgetOwnerOut]:
    return [
        BudgetOwnerOut(
            dimension_value_id=o.dimension_value_id,
            user_id=o.user_id,
            user_name=o.user.display_name or o.user.email,
        )
        for o in rows
    ]


@router.get(f"{BASE}/budgets/{{uuid:budget_id}}/owners", response=list[BudgetOwnerOut])
@requires("budget.read")
def list_owners(
    request: HttpRequest, slug: str, entity_id: UUID, budget_id: UUID
) -> list[BudgetOwnerOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return _owners_out(services.owners(ctx, entity_id, budget_id))


@router.put(f"{BASE}/budgets/{{uuid:budget_id}}/owners", response=list[BudgetOwnerOut])
@requires("budget.edit")
def set_owners(
    request: HttpRequest, slug: str, entity_id: UUID, budget_id: UUID, payload: BudgetOwnersIn
) -> list[BudgetOwnerOut]:
    """Name the owner of each department (or project) of a budget."""
    ctx = workspace_ctx(request, slug, entity_id)
    rows = [services.OwnerInput(o.dimension_value_id, o.user_id) for o in payload.owners]
    return _owners_out(services.set_owners(ctx, entity_id, budget_id, rows))


@router.get(f"{BASE}/budget-members", response=list[BudgetMemberOut])
@requires("budget.edit")
def budget_members(request: HttpRequest, slug: str, entity_id: UUID) -> list[BudgetMemberOut]:
    """People who can be named as department owners."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [
        BudgetMemberOut(user_id=m.user_id, name=m.display_name or m.email)
        for m in services.members(ctx, entity_id)
    ]


# --- variance (M4-3) ------------------------------------------------------------------------------

ViewName = Literal["MONTH", "QTD", "YTD", "FULL_YEAR"]
ComparisonName = Literal["ACTUAL_VS_BUDGET", "ACTUAL_VS_PRIOR_YEAR", "CURRENT_VS_ORIGINAL"]


class VarianceQuery(Schema):
    month: date = Field(description="First day of the month the view ends in")
    view: ViewName = "MONTH"
    comparison: ComparisonName = "ACTUAL_VS_BUDGET"


class VarianceExplanationOut(Schema):
    line_id: UUID
    month: date
    view: str
    comparison: str
    comment: str
    seq: int
    author_name: str
    at: datetime


def _explanation_out(e: Any) -> VarianceExplanationOut:
    return VarianceExplanationOut(
        line_id=e.line_id,
        month=e.month,
        view=e.view,
        comparison=e.comparison,
        comment=e.comment,
        seq=e.seq,
        author_name=e.author.display_name or e.author.email,
        at=e.created_at,
    )


class VarianceRowOut(Schema):
    line_id: UUID | None = Field(description="None for a line only in the original budget")
    taxonomy_code: str | None
    account_id: UUID | None
    dimension_value_id: UUID | None
    direction: str
    subject: str
    subject_nature: Literal["ACTUAL", "BLENDED", "BUDGET"]
    comparison: str
    comparison_nature: Literal["ACTUAL", "BUDGET"]
    variance: str
    percent: str | None = Field(description="None: not meaningful (the comparison is zero)")
    favourable: bool | None = Field(description="None when there is no variance")
    requires_explanation: bool
    explanation: VarianceExplanationOut | None


class PeriodReviewOut(Schema):
    month: date
    actuals_watermark: int
    completed_by_name: str
    at: datetime


class VarianceOut(Schema):
    version_id: UUID
    month: date
    view: str
    comparison: str
    window: list[date]
    cutover: date | None = Field(description="Blended views: actuals up to this month")
    actuals_watermark: int
    unposted_entries: int | None = Field(description="Entries in the period not yet posted")
    explain_above_amount: str
    explain_above_percent: str
    rows: list[VarianceRowOut]
    review: PeriodReviewOut | None


@router.get(f"{BASE}/budget-versions/{{uuid:version_id}}/variance", response=VarianceOut)
@requires("budget.department")
def get_variance(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, q: Query[VarianceQuery]
) -> VarianceOut:
    """Actual vs budget (or prior year, or current vs original budget) for every visible line;
    actuals from posted entries only, pinned to one ledger watermark."""
    ctx = workspace_ctx(request, slug, entity_id)
    v = variance.compute(
        ctx, entity_id, version_id, month=q.month, view=q.view, comparison=q.comparison
    )
    review = None
    if v.review is not None:
        by = v.review.completed_by
        review = PeriodReviewOut(
            month=v.review.month,
            actuals_watermark=v.review.actuals_watermark,
            completed_by_name=by.display_name or by.email,
            at=v.review.created_at,
        )
    return VarianceOut(
        version_id=v.version.id,
        month=v.month,
        view=v.view,
        comparison=v.comparison,
        window=v.window,
        cutover=v.cutover,
        actuals_watermark=v.watermark,
        unposted_entries=v.unposted,
        explain_above_amount=_money(v.thresholds.amount),
        explain_above_percent=_money(v.thresholds.percent),
        rows=[
            VarianceRowOut(
                line_id=r.line_id,
                taxonomy_code=r.taxonomy_code,
                account_id=r.account_id,
                dimension_value_id=r.dimension_value_id,
                direction=r.direction,
                subject=_money(r.subject),
                subject_nature=r.subject_nature,  # type: ignore[arg-type]
                comparison=_money(r.comparison),
                comparison_nature=r.comparison_nature,  # type: ignore[arg-type]
                variance=_money(r.variance),
                percent=None if r.percent is None else _money(r.percent),
                favourable=r.favourable,
                requires_explanation=r.requires_explanation,
                explanation=_explanation_out(r.explanation) if r.explanation else None,
            )
            for r in v.rows
        ],
        review=review,
    )


class VarianceExplainIn(Schema):
    line_id: UUID
    month: date
    view: ViewName = "MONTH"
    comparison: ComparisonName = "ACTUAL_VS_BUDGET"
    comment: str = Field(max_length=1000)


@router.post(
    f"{BASE}/budget-versions/{{uuid:version_id}}/explanations",
    response={201: VarianceExplanationOut},
)
@requires("budget.department")
def explain_variance(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: VarianceExplainIn
) -> Status[VarianceExplanationOut]:
    """Explain (or re-explain) a line's variance; earlier explanations are kept."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = variance.explain(
        ctx,
        entity_id,
        version_id,
        payload.line_id,
        month=payload.month,
        view=payload.view,
        comparison=payload.comparison,
        comment=payload.comment,
    )
    return Status(201, _explanation_out(made))


@router.get(
    f"{BASE}/budget-versions/{{uuid:version_id}}/lines/{{uuid:line_id}}/explanations",
    response=list[VarianceExplanationOut],
)
@requires("budget.department")
def explanation_history(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, line_id: UUID
) -> list[VarianceExplanationOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_explanation_out(e) for e in variance.history(ctx, entity_id, version_id, line_id)]


class PeriodReviewIn(Schema):
    month: date


@router.post(f"{BASE}/budget-versions/{{uuid:version_id}}/reviews", response={201: PeriodReviewOut})
@requires("budget.approve")
def complete_review(
    request: HttpRequest, slug: str, entity_id: UUID, version_id: UUID, payload: PeriodReviewIn
) -> Status[PeriodReviewOut]:
    """Mark a month's budget review complete (refused while explanations are missing)."""
    ctx = workspace_ctx(request, slug, entity_id)
    review = variance.complete_review(ctx, entity_id, version_id, payload.month)
    return Status(
        201,
        PeriodReviewOut(
            month=review.month,
            actuals_watermark=review.actuals_watermark,
            completed_by_name=ctx.user.display_name or ctx.user.email,
            at=review.created_at,
        ),
    )
