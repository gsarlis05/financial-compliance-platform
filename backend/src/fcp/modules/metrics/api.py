"""Public interface of the ``metrics`` module and its HTTP routes (M2-6: taxonomy and mapping;
M2-8: statements; M3-2: natures, series and calculation runs).

Routes are entity-scoped: ``/api/w/{slug}/entities/{entity_id}/...``.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from ninja import Field, Query, Router, Schema

from fcp.core.api.permissions import requires
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, workspace_ctx

from . import calc, exports, services, statements
from .calc import (
    Engine,
    Output,
    Reproduction,
    RunInputs,
    Source,
    Value,
    execute,
    formula_value,
    mark_stale,
)
from .calc import register as register_engine
from .expr import (
    EvaluationError,
    ExpressionError,
    Function,
    NotMeaningful,
    Param,
    compile_expression,
    evaluate,
)
from .hashing import canonical_decimal
from .models import CalcResult, CalcRun, TaxonomyLine
from .nature import ActualSeries, BlendedSeries, Nature, NatureMixError, PlanSeries, Point, blend
from .services import Completeness, completeness, current_mapping
from .taxonomy import DEFAULT_TAXONOMY

__all__ = [
    "DEFAULT_TAXONOMY",
    "ActualSeries",
    "BlendedSeries",
    "CalcRun",
    "Completeness",
    "Engine",
    "EvaluationError",
    "ExpressionError",
    "Function",
    "Nature",
    "NatureMixError",
    "NotMeaningful",
    "Output",
    "Param",
    "PlanSeries",
    "Point",
    "Reproduction",
    "RunInputs",
    "Source",
    "TaxonomyLine",
    "Value",
    "blend",
    "compile_expression",
    "completeness",
    "current_mapping",
    "evaluate",
    "execute",
    "formula_value",
    "mark_stale",
    "register_engine",
    "router",
]  # fmt: skip

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


# --- statements (M2-8) ----------------------------------------------------------------------------


class StatementsQuery(Schema):
    date_from: date
    date_to: date
    comparative: Literal["prior_year", "none"] = "prior_year"


class AccountAmountOut(Schema):
    account_id: UUID | None = Field(description="None for a computed part (e.g. depreciation)")
    code: str
    name: str
    name_el: str
    current: str
    comparative: str | None


class RowOut(Schema):
    kind: Literal["heading", "line", "subtotal", "total"]
    code: str
    name: str
    name_el: str
    current: str | None
    comparative: str | None
    accounts: list[AccountAmountOut]


class CheckOut(Schema):
    code: str
    column: Literal["current", "comparative"]
    ok: bool
    values: dict[str, str]


class StatementOut(Schema):
    kind: Literal["PL", "BS", "CF"]
    name: str
    name_el: str
    rows: list[RowOut]
    checks: list[CheckOut]


class StatementsOut(Schema):
    entity_name: str
    taxonomy: str
    watermark: int = Field(description="The statements include every posting up to this number")
    date_from: date
    date_to: date
    comparative_from: date | None
    comparative_to: date | None
    ok: bool = Field(description="Every check passed (a failure is a defect and is logged)")
    profit_and_loss: StatementOut
    balance_sheet: StatementOut
    cash_flow: StatementOut


def _money(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _statement_out(st: statements.Statement) -> StatementOut:
    return StatementOut(
        kind=st.kind,
        name=st.name,
        name_el=st.name_el,
        rows=[
            RowOut(
                kind=r.kind,
                code=r.code,
                name=r.name,
                name_el=r.name_el,
                current=_money(r.current),
                comparative=_money(r.comparative),
                accounts=[
                    AccountAmountOut(
                        account_id=a.account_id,
                        code=a.code,
                        name=a.name,
                        name_el=a.name_el,
                        current=f"{a.current:.2f}",
                        comparative=_money(a.comparative),
                    )
                    for a in r.accounts
                ],
            )
            for r in st.rows
        ],
        checks=[
            CheckOut(
                code=c.code,
                column=c.column,
                ok=c.ok,
                values={k: f"{v:.2f}" for k, v in c.values.items()},
            )
            for c in st.checks
        ],
    )


def _build(
    request: HttpRequest, slug: str, entity_id: UUID, q: StatementsQuery
) -> tuple[WorkspaceContext, statements.Statements]:
    ctx = workspace_ctx(request, slug, entity_id)
    return ctx, statements.build(
        ctx, entity_id, date_from=q.date_from, date_to=q.date_to, comparative=q.comparative
    )


@router.get(f"{BASE}/statements", response=StatementsOut)
@requires("reports.read")
def financial_statements(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[StatementsQuery]
) -> StatementsOut:
    """P&L, balance sheet and indirect cash flow for a period, with prior-year comparatives.
    Blocked (409 ``metrics.statements.mapping_incomplete``) while an account with a balance is
    unmapped; the problem's field errors list those accounts by code."""
    _, result = _build(request, slug, entity_id, q)
    return StatementsOut(
        entity_name=result.entity_name,
        taxonomy=result.taxonomy,
        watermark=result.watermark,
        date_from=result.current.date_from,
        date_to=result.current.date_to,
        comparative_from=result.comparative.date_from if result.comparative else None,
        comparative_to=result.comparative.date_to if result.comparative else None,
        ok=result.ok,
        profit_and_loss=_statement_out(result.profit_and_loss),
        balance_sheet=_statement_out(result.balance_sheet),
        cash_flow=_statement_out(result.cash_flow),
    )


class ExportQuery(StatementsQuery):
    format: Literal["csv", "xlsx", "pdf"]
    lang: Literal["en", "el"] = "en"


_CONTENT_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}


@router.get(f"{BASE}/statements/export")
@requires("reports.export")
def export_statements(
    request: HttpRequest, slug: str, entity_id: UUID, q: Query[ExportQuery]
) -> HttpResponse:
    """The three statements as CSV, XLSX (one sheet each) or PDF (one page each); audited."""
    ctx, result = _build(request, slug, entity_id, q)
    generated = timezone.now()
    content: str | bytes
    if q.format == "csv":
        content = exports.to_csv(result, q.lang)
    elif q.format == "xlsx":
        content = exports.to_xlsx(result, q.lang, generated=generated)
    else:
        content = exports.to_pdf(result, q.lang, generated=generated)
    filename = f"statements-{q.date_from.isoformat()}-{q.date_to.isoformat()}.{q.format}"
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action="reports.exported",
        subject_type="report",
        subject_id="statements",
        entity_id=entity_id,
        changes={"format": q.format, "filename": filename, "watermark": result.watermark},
    )
    response = HttpResponse(content, content_type=_CONTENT_TYPES[q.format])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# --- calculation runs (M3-2) ----------------------------------------------------------------------


def _amount(value: Decimal | None) -> str | None:
    """Exact, as computed (values are not rounded here; displays round them)."""
    return None if value is None else canonical_decimal(value)


class RunOut(Schema):
    id: UUID
    kind: str
    engine_version: str
    status: str
    as_of_date: date
    actuals_watermark: int
    input_refs: dict[str, Any]
    input_hash: str
    output_hash: str
    invariant_results: dict[str, bool]
    error: str
    stale: bool
    is_published: bool
    trigger: str
    supersedes_id: UUID | None
    created_at: datetime
    finished_at: datetime | None


class ResultOut(Schema):
    id: UUID
    series_key: str
    dimensions: list[str]
    period_start: date
    period_end: date
    granularity: str
    nature: Nature = Field(description="Every value has a nature (doc 10 P2)")
    value: str | None
    unit: str
    nm_reason: str


class RunDetailOut(RunOut):
    results: list[ResultOut]


class LineageOut(Schema):
    input_kind: str
    input_ref: str
    amount: str | None
    note: str


class ExplainOut(Schema):
    result: ResultOut
    lineage: list[LineageOut]


class ReproductionOut(Schema):
    run_id: UUID
    reproduced: bool
    stored_intact: bool
    output_hash: str
    recomputed_hash: str
    reason: str


def _run_out(run: CalcRun) -> dict[str, Any]:
    return {f: getattr(run, f) for f in RunOut.model_fields}


def _result_out(r: CalcResult) -> ResultOut:
    return ResultOut(id=r.id, series_key=r.series_key, dimensions=r.dimensions,
                     period_start=r.period_start, period_end=r.period_end,
                     granularity=r.granularity, nature=Nature(r.nature), value=_amount(r.value),
                     unit=r.unit, nm_reason=r.nm_reason)  # fmt: skip


class RunsQuery(Schema):
    kind: str | None = Field(None, max_length=30)
    limit: int = Field(50, ge=1, le=200)


@router.get(f"{BASE}/calc-runs", response=list[RunOut])
@requires("planning.read")
def calc_runs(request: HttpRequest, slug: str, entity_id: UUID,
              q: Query[RunsQuery]) -> list[RunOut]:  # fmt: skip
    ctx = workspace_ctx(request, slug, entity_id)
    return [RunOut(**_run_out(r)) for r in calc.list_runs(ctx, entity_id, q.kind, q.limit)]


@router.get(f"{BASE}/calc-runs/{{uuid:run_id}}", response=RunDetailOut)
@requires("planning.read")
def calc_run(request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID) -> RunDetailOut:
    ctx = workspace_ctx(request, slug, entity_id)
    run = calc.get_run(ctx, entity_id, run_id)
    return RunDetailOut(**_run_out(run), results=[_result_out(r) for r in calc.results(run)])


@router.get(f"{BASE}/calc-runs/{{uuid:run_id}}/results/{{uuid:result_id}}/explain",
            response=ExplainOut)  # fmt: skip
@requires("planning.read")
def explain_result(request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID,
                   result_id: UUID) -> ExplainOut:  # fmt: skip
    """What a value was computed from: actuals, open items, assumptions, ... (AC-CF4)."""
    ctx = workspace_ctx(request, slug, entity_id)
    result, lineage = calc.explain(ctx, entity_id, run_id, result_id)
    return ExplainOut(result=_result_out(result), lineage=[
        LineageOut(input_kind=x.input_kind, input_ref=x.input_ref, amount=_amount(x.amount),
                   note=x.note)
        for x in lineage
    ])  # fmt: skip


@router.post(f"{BASE}/calc-runs/{{uuid:run_id}}/reproduce", response=ReproductionOut)
@requires("planning.run")
def reproduce_run(request: HttpRequest, slug: str, entity_id: UUID,
                  run_id: UUID) -> ReproductionOut:  # fmt: skip
    """Compute the run again from its stored inputs and compare the output hash (AC-CF3)."""
    ctx = workspace_ctx(request, slug, entity_id)
    r = calc.reproduce(ctx, entity_id, run_id)
    return ReproductionOut(run_id=r.run_id, reproduced=r.reproduced, stored_intact=r.stored_intact,
                           output_hash=r.output_hash, recomputed_hash=r.recomputed_hash,
                           reason=r.reason)  # fmt: skip


@router.post(f"{BASE}/calc-runs/{{uuid:run_id}}/publish", response=RunOut)
@requires("planning.publish")
def publish_run(request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID) -> RunOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return RunOut(**_run_out(calc.publish(ctx, entity_id, run_id)))
