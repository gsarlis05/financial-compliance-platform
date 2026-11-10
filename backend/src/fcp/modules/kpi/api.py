"""Public interface of the ``kpi`` module and its HTTP routes (M4-4: the core KPI library).

Every KPI value is ACTUAL, belongs to a stored calculation run, and names the definition version it
was computed with. Not-meaningful values have no number, only a reason (doc 10 §2.2, AC-KP2).
Drill-down: ``calc-runs/{run}/results/{result}/explain`` lists the reference calls and accounts.
"""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from fcp.core.api.permissions import requires
from fcp.modules.tenancy.api import workspace_ctx

from . import custom, services
from .engine import (
    KIND,
    Account,
    Evaluated,
    cutoffs,
    evaluate_formula,
    matches,
    period_months,
    reference_functions,
)
from .models import CustomKpi, KpiDefinition, OperationalMetric, OperationalValue
from .services import KpiFormula, KpiSet, trackable
from .services import run_refs as kpi_inputs

__all__ = [
    "KIND",
    "Account",
    "Evaluated",
    "KpiDefinition",
    "KpiFormula",
    "KpiSet",
    "cutoffs",
    "evaluate_formula",
    "kpi_inputs",
    "matches",
    "period_months",
    "reference_functions",
    "router",
    "trackable",
]

router = Router(tags=["kpi"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"


class KpiDefinitionOut(Schema):
    id: str = Field(description="Library version and key, e.g. CORE@1.0:DSO")
    key: str
    name: str
    name_el: str
    category: str
    formula: str
    display: str
    direction: str
    convention: str
    nm_note: str
    example: str


@router.get(f"{BASE}/kpi-definitions", response=list[KpiDefinitionOut])
@requires("planning.read")
def list_definitions(request: HttpRequest, slug: str, entity_id: UUID) -> list[KpiDefinition]:
    workspace_ctx(request, slug, entity_id)
    return services.definitions()


class KpiValueOut(Schema):
    result_id: UUID = Field(description="For calc-runs/{run}/results/{result}/explain")
    definition_id: str
    key: str
    name: str
    name_el: str
    category: str
    display: str
    direction: str
    convention: str
    nature: Literal["ACTUAL"] = "ACTUAL"
    value: str | None = Field(description="Unrounded (up to 20 places); None if not meaningful")
    unit: str
    nm_reason: str
    non_ledger: bool = Field(False, description="Uses operational metrics entered by hand")


class KpiSetOut(Schema):
    run_id: UUID
    status: str
    stale: bool = Field(description="Entries were posted after this set was calculated")
    library: str
    date_from: date
    date_to: date
    actuals_watermark: int
    created_at: datetime
    unmapped_accounts: int = Field(description="Accounts with activity but no taxonomy line")
    values: list[KpiValueOut]


def _out(kpis: KpiSet) -> KpiSetOut:
    run = kpis.run
    library = run.input_refs["library"]
    values = []
    for r in kpis.values:
        definition = kpis.definitions.get(r.series_key)
        if definition is None:  # pragma: no cover (library versions are never edited)
            continue
        values.append(
            KpiValueOut(
                result_id=r.id,
                definition_id=definition.id,
                key=definition.key,
                name=definition.name,
                name_el=definition.name_el,
                category=definition.category,
                display=definition.display,
                direction=definition.direction,
                convention=definition.convention,
                value=None if r.value is None else format(r.value.normalize(), "f"),
                unit=r.unit,
                nm_reason=r.nm_reason,
                non_ledger="NON_LEDGER" in r.dimensions,
            )
        )
    return KpiSetOut(
        run_id=run.id,
        status=run.status,
        stale=kpis.out_of_date,
        library=library,
        date_from=date.fromisoformat(run.input_refs["date_from"]),
        date_to=date.fromisoformat(run.input_refs["date_to"]),
        actuals_watermark=run.actuals_watermark,
        created_at=run.created_at,
        unmapped_accounts=kpis.unmapped_accounts,
        values=values,
    )


class PeriodIn(Schema):
    date_from: date = Field(description="First day of a month")
    date_to: date = Field(description="Last day of a month; at most 12 months")


@router.post(f"{BASE}/kpi-sets", response={201: KpiSetOut})
@requires("planning.run")
def run_kpis(
    request: HttpRequest, slug: str, entity_id: UUID, payload: PeriodIn
) -> Status[KpiSetOut]:
    """Compute the core KPIs for a period, as a stored and reproducible calculation run."""
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(
        201,
        _out(services.run(ctx, entity_id, date_from=payload.date_from, date_to=payload.date_to)),
    )


@router.get(f"{BASE}/kpi-sets/latest", response=KpiSetOut)
@requires("planning.read")
def latest_kpis(request: HttpRequest, slug: str, entity_id: UUID, q: Query[PeriodIn]) -> KpiSetOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.latest(ctx, entity_id, date_from=q.date_from, date_to=q.date_to))


# --- custom KPIs and operational metrics (M4-5) ---------------------------------------------------

Display = Literal["percent", "ratio", "times", "days", "months", "EUR"]
Direction = Literal["HIGHER_BETTER", "LOWER_BETTER"]


class CustomKpiIn(Schema):
    key: str = Field(max_length=40, description="e.g. REVENUE_PER_EMPLOYEE")
    name: str = Field(max_length=120)
    formula: str = Field(max_length=2000)
    display: Display
    direction: Direction
    convention: str = Field("", max_length=500)


class CustomKpiCreateIn(CustomKpiIn):
    scope: Literal["PERSONAL", "WORKSPACE"]


class CustomKpiOut(Schema):
    id: UUID
    key: str
    version: int
    scope: str
    status: str
    name: str
    formula: str
    unit: str
    display: str
    direction: str
    convention: str
    owner_name: str
    supersedes_id: UUID | None
    decided_by_name: str
    decided_at: datetime | None
    decision_comment: str
    created_at: datetime


def _kpi_out(k: CustomKpi) -> CustomKpiOut:
    return CustomKpiOut(
        id=k.id,
        key=k.key,
        version=k.version,
        scope=k.scope,
        status=k.status,
        name=k.name,
        formula=k.formula,
        unit=k.unit,
        display=k.display,
        direction=k.direction,
        convention=k.convention,
        owner_name=k.owner.display_name or k.owner.email,
        supersedes_id=k.supersedes_id,
        decided_by_name=(k.decided_by.display_name or k.decided_by.email) if k.decided_by else "",
        decided_at=k.decided_at,
        decision_comment=k.decision_comment,
        created_at=k.created_at,
    )


def _input(p: CustomKpiIn) -> custom.KpiInput:
    return custom.KpiInput(p.key.strip(), p.name, p.formula, p.display, p.direction, p.convention)


class FormulaIn(Schema):
    formula: str = Field(max_length=2000)
    display: Display


class FormulaCheckOut(Schema):
    ok: bool
    unit: str | None
    problems: list[str]
    dry_run_month: date | None
    dry_run_value: str | None = Field(description="None: not meaningful (see the reason)")
    dry_run_reason: str
    non_ledger: bool


@router.post(f"{BASE}/custom-kpis/check", response=FormulaCheckOut)
@requires("planning.read")
def check_formula(
    request: HttpRequest, slug: str, entity_id: UUID, payload: FormulaIn
) -> FormulaCheckOut:
    """Check a formula and try it on the last complete month; nothing is saved."""
    ctx = workspace_ctx(request, slug, entity_id)
    c = custom.check(ctx, entity_id, payload.formula, payload.display)
    return FormulaCheckOut(
        ok=c.ok,
        unit=c.unit,
        problems=c.problems,
        dry_run_month=c.dry_run_month,
        dry_run_value=None if c.dry_run_value is None else format(c.dry_run_value.normalize(), "f"),
        dry_run_reason=c.dry_run_reason,
        non_ledger=c.non_ledger,
    )


@router.get(f"{BASE}/custom-kpis", response=list[CustomKpiOut])
@requires("planning.read")
def list_custom(request: HttpRequest, slug: str, entity_id: UUID) -> list[CustomKpiOut]:
    """Every version of the workspace KPIs, and your own personal KPIs."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_kpi_out(k) for k in custom.visible(ctx, entity_id)]


@router.post(f"{BASE}/custom-kpis", response={201: CustomKpiOut})
@requires("planning.read")
def create_custom(
    request: HttpRequest, slug: str, entity_id: UUID, payload: CustomKpiCreateIn
) -> Status[CustomKpiOut]:
    """A personal KPI (in use at once) or a workspace KPI (needs ``kpi.definition.manage``, and
    approval by someone else)."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = custom.create(ctx, entity_id, payload.scope, _input(payload))
    return Status(201, _kpi_out(made))


@router.post(f"{BASE}/custom-kpis/{{uuid:kpi_id}}/revise", response={201: CustomKpiOut})
@requires("planning.read")
def revise_custom(
    request: HttpRequest, slug: str, entity_id: UUID, kpi_id: UUID, payload: CustomKpiIn
) -> Status[CustomKpiOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return Status(201, _kpi_out(custom.revise(ctx, entity_id, kpi_id, _input(payload))))


class DecisionIn(Schema):
    comment: str = Field("", max_length=500)


@router.post(f"{BASE}/custom-kpis/{{uuid:kpi_id}}/approve", response=CustomKpiOut)
@requires("kpi.definition.approve")
def approve_custom(
    request: HttpRequest, slug: str, entity_id: UUID, kpi_id: UUID, payload: DecisionIn
) -> CustomKpiOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _kpi_out(custom.decide(ctx, entity_id, kpi_id, approve=True, comment=payload.comment))


@router.post(f"{BASE}/custom-kpis/{{uuid:kpi_id}}/reject", response=CustomKpiOut)
@requires("kpi.definition.approve")
def reject_custom(
    request: HttpRequest, slug: str, entity_id: UUID, kpi_id: UUID, payload: DecisionIn
) -> CustomKpiOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _kpi_out(custom.decide(ctx, entity_id, kpi_id, approve=False, comment=payload.comment))


@router.post(f"{BASE}/custom-kpis/{{uuid:kpi_id}}/retire", response=CustomKpiOut)
@requires("planning.read")
def retire_custom(request: HttpRequest, slug: str, entity_id: UUID, kpi_id: UUID) -> CustomKpiOut:
    ctx = workspace_ctx(request, slug, entity_id)
    return _kpi_out(custom.retire(ctx, entity_id, kpi_id))


class PersonalValueOut(Schema):
    key: str
    definition_id: str
    name: str
    display: str
    direction: str
    nature: Literal["ACTUAL"] = "ACTUAL"
    value: str | None
    unit: str
    nm_reason: str
    non_ledger: bool


@router.get(f"{BASE}/kpi-sets/{{uuid:run_id}}/personal", response=list[PersonalValueOut])
@requires("planning.read")
def personal_kpis(
    request: HttpRequest, slug: str, entity_id: UUID, run_id: UUID
) -> list[PersonalValueOut]:
    """Your personal KPIs on this set's pinned data. They are not stored and only you see them."""
    ctx = workspace_ctx(request, slug, entity_id)
    mine, values = custom.personal_values(ctx, entity_id, run_id)
    return [
        PersonalValueOut(
            key=k.key,
            definition_id=f"PERSONAL:{k.key}@{k.version}",
            name=k.name,
            display=k.display,
            direction=k.direction,
            value=None if v.value is None else format(v.value.normalize(), "f"),
            unit=v.unit,
            nm_reason=v.nm_reason,
            non_ledger="NON_LEDGER" in v.dimensions,
        )
        for k, v in zip(mine, values, strict=True)
    ]


class MetricIn(Schema):
    key: str = Field(max_length=40, description="e.g. HEADCOUNT")
    name: str = Field(max_length=120)
    unit: Literal["count", "EUR"]
    aggregation: Literal["LAST", "SUM"] = Field(
        description="LAST: a point in time (headcount); SUM: a total (units sold)"
    )


class MetricValueOut(Schema):
    month: date
    value: str
    version: int
    note: str
    entered_by: str
    entered_at: datetime


class MetricOut(Schema):
    id: UUID
    key: str
    name: str
    unit: str
    aggregation: str
    source: Literal["MANUAL"] = "MANUAL"
    nature: Literal["ACTUAL"] = "ACTUAL"
    non_ledger: Literal[True] = True
    values: list[MetricValueOut]


def _value_out(v: OperationalValue) -> MetricValueOut:
    return MetricValueOut(
        month=v.month,
        value=format(v.value.normalize(), "f"),
        version=v.version,
        note=v.note,
        entered_by=v.created_by.display_name or v.created_by.email,
        entered_at=v.created_at,
    )


def _metric_out(m: OperationalMetric) -> MetricOut:
    values = sorted(custom.current_values(m).values(), key=lambda v: v.month)
    return MetricOut(
        id=m.id,
        key=m.key,
        name=m.name,
        unit=m.unit,
        aggregation=m.aggregation,
        values=[_value_out(v) for v in values],
    )


@router.get(f"{BASE}/operational-metrics", response=list[MetricOut])
@requires("planning.read")
def list_metrics(request: HttpRequest, slug: str, entity_id: UUID) -> list[MetricOut]:
    """Operational (non-ledger) metrics with their current monthly values."""
    ctx = workspace_ctx(request, slug, entity_id)
    return [_metric_out(m) for m in custom.metrics(ctx, entity_id)]


@router.post(f"{BASE}/operational-metrics", response={201: MetricOut})
@requires("kpi.operational.manage")
def create_metric(
    request: HttpRequest, slug: str, entity_id: UUID, payload: MetricIn
) -> Status[MetricOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    made = custom.create_metric(
        ctx,
        entity_id,
        custom.MetricInput(payload.key.strip(), payload.name, payload.unit, payload.aggregation),
    )
    return Status(201, _metric_out(made))


class MetricValueIn(Schema):
    month: date = Field(description="First day of the month")
    value: str = Field(pattern=r"^-?\d{1,15}(\.\d{1,4})?$")
    note: str = Field("", max_length=300)


@router.put(f"{BASE}/operational-metrics/{{uuid:metric_id}}/values", response=MetricValueOut)
@requires("kpi.operational.manage")
def set_metric_value(
    request: HttpRequest, slug: str, entity_id: UUID, metric_id: UUID, payload: MetricValueIn
) -> MetricValueOut:
    """Enter or correct a month's value; a correction keeps the earlier value as history."""
    ctx = workspace_ctx(request, slug, entity_id)
    made = custom.set_value(ctx, entity_id, metric_id, payload.month, payload.value, payload.note)
    return _value_out(made)


class MetricHistoryQuery(Schema):
    month: date


@router.get(f"{BASE}/operational-metrics/{{uuid:metric_id}}/history", response=list[MetricValueOut])
@requires("planning.read")
def metric_history(
    request: HttpRequest, slug: str, entity_id: UUID, metric_id: UUID, q: Query[MetricHistoryQuery]
) -> list[MetricValueOut]:
    ctx = workspace_ctx(request, slug, entity_id)
    return [_value_out(v) for v in custom.value_history(ctx, entity_id, metric_id, q.month)]
