"""Custom KPIs and operational metrics (M4-5, doc 10 §5.2-§5.3, AC-KP4, AC-KP5).

Custom KPIs:
- written in the same formula language as the library, and checked before they are saved:
  syntax, the unit against the chosen display, every taxonomy key and metric they name, and a
  dry run on the last complete month (doc 10 §5.2);
- PERSONAL KPIs are visible only to their owner, need no approval and are never stored in a
  shared KPI set: they are evaluated on a set's pinned data when the owner asks;
- WORKSPACE KPIs need ``kpi.definition.manage`` to propose and approval by someone else with
  ``kpi.definition.approve`` (the database refuses an approval by the author). Once approved, they
  join every new KPI set with their version, so a value always names the version it used.
- A change is a new version. Earlier versions are kept and never change.

Operational metrics are entered by hand per month, versioned (a correction supersedes the earlier
value, which is kept) and audited. Every KPI value that uses one is marked as not from the ledger.
"""

import re
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from fcp.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from fcp.modules.audit_log.api import record as audit
from fcp.modules.calendar.api import add_months, month_end, month_start
from fcp.modules.metrics.api import (
    DEFAULT_TAXONOMY,
    ExpressionError,
    RunInputs,
    TaxonomyLine,
    Value,
    compile_expression,
    get_calc_run,
)
from fcp.modules.reporting.api import current_watermark
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .engine import ENGINE, KIND, reference_functions
from .models import CustomKpi, KpiDefinition, OperationalMetric, OperationalValue

READ, MANAGE, APPROVE = "planning.read", "kpi.definition.manage", "kpi.definition.approve"
OPERATIONAL = "kpi.operational.manage"
KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")
CALL = re.compile(r'([a-z_]+)\(\s*"([^"]*)"')
TAXONOMY_FUNCTIONS = {"flow", "prior_flow", "balance", "opening", "avg_balance"}
METRIC_FUNCTIONS = {"count_metric": "count", "amount_metric": "EUR"}
DISPLAY_UNITS = {
    "percent": "ratio",
    "ratio": "ratio",
    "times": "ratio",
    "months": "ratio",
    "days": "days",
    "EUR": "EUR",
}
Status, Scope = CustomKpi.Status, CustomKpi.Scope
IN_USE = (Status.ACTIVE, Status.APPROVED)


def _invalid(field: str, message: str) -> ValidationFailedError:
    return ValidationFailedError(message, field_errors={field: [message]})


def _audit(
    ctx: WorkspaceContext,
    entity_id: UUID,
    kind: str,
    subject: UUID,
    action: str,
    changes: dict[str, Any],
) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type=kind,
        subject_id=subject,
        entity_id=entity_id,
        changes=changes,
    )


# --- checking a formula ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    unit: str | None
    problems: list[str]
    dry_run_month: date | None = None
    dry_run_value: Decimal | None = None
    dry_run_reason: str = ""
    non_ledger: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems


def _matches_taxonomy(key: str, lines: list[TaxonomyLine]) -> bool:
    return any(key in (ln.code, ln.section) or ln.code.startswith(f"{key}.") for ln in lines)


def check(ctx: WorkspaceContext, entity_id: UUID, formula: str, display: str) -> Check:
    """Check a formula and try it on the last complete month (nothing is saved)."""
    entity = get_entity(ctx, entity_id, READ)
    if display not in DISPLAY_UNITS:
        raise _invalid("display", "Choose how the KPI is shown.")
    try:
        compiled = compile_expression(formula, functions=reference_functions())
    except ExpressionError as exc:
        return Check(None, [str(exc)])
    problems = []
    if compiled.type.kind != "scalar":
        problems.append("A KPI gives a number, not true or false.")
    elif compiled.unit != DISPLAY_UNITS[display]:
        problems.append(
            f"The formula gives {compiled.unit}, but {display} needs {DISPLAY_UNITS[display]}."
        )
    lines = list(TaxonomyLine.objects.filter(version_id=DEFAULT_TAXONOMY))
    metrics = {m.key: m.unit for m in OperationalMetric.objects.filter(legal_entity=entity)}
    for function, key in CALL.findall(formula):
        if function in TAXONOMY_FUNCTIONS and not _matches_taxonomy(key, lines):
            problems.append(f'"{key}" is not a taxonomy line or section.')
        elif function in METRIC_FUNCTIONS and metrics.get(key) != METRIC_FUNCTIONS[function]:
            problems.append(f'"{key}" is not a {METRIC_FUNCTIONS[function]} operational metric.')
    if problems:
        return Check(compiled.unit, problems)
    month = add_months(month_start(timezone.localdate()), -1)
    value = _evaluate(
        ctx,
        entity.id,
        (month, month_end(month)),
        [{"id": "DRY_RUN", "key": "DRY_RUN", "formula": formula, "nm_reason": ""}],
    )[0]
    return Check(
        compiled.unit, [], month, value.value, value.nm_reason, "NON_LEDGER" in value.dimensions
    )


def _evaluate(
    ctx: WorkspaceContext,
    entity_id: UUID,
    period: tuple[date, date],
    definitions: list[dict[str, str]],
    *,
    pinned: tuple[dict[str, Any], int] | None = None,
) -> list[Value]:
    """Evaluate formulas on pinned data without storing anything."""
    from .services import run_refs  # noqa: PLC0415 (services imports this module)

    date_from, date_to = period
    if pinned is None:
        refs, watermark = run_refs(ctx, entity_id, date_from, date_to), None
    else:
        refs, watermark = pinned
    inputs = RunInputs(
        KIND,
        ENGINE.version,
        entity_id,
        date_to,
        current_watermark(ctx, entity_id) if watermark is None else watermark,
        {**refs, "custom": []},
    )
    data = ENGINE.load(ctx, inputs)
    return list(ENGINE.compute(inputs, replace(data, definitions=definitions)).values)


# --- custom KPIs ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class KpiInput:
    key: str
    name: str
    formula: str
    display: str
    direction: str
    convention: str = ""


def _validated(ctx: WorkspaceContext, entity_id: UUID, data: KpiInput) -> Check:
    if not KEY.match(data.key):
        raise _invalid(
            "key",
            "Keys are 2 to 40 capital letters, digits or _ starting with a "
            "letter, e.g. REVENUE_PER_EMPLOYEE.",
        )
    if KpiDefinition.objects.filter(key=data.key).exists():
        raise _invalid("key", "This key belongs to a standard KPI.")
    if not data.name.strip() or len(data.name) > 120 or len(data.convention) > 500:
        raise _invalid("name", "Give a name (up to 120 characters).")
    if data.direction not in ("HIGHER_BETTER", "LOWER_BETTER"):
        raise _invalid("direction", "Say whether higher or lower is better.")
    if len(data.formula) > 2000:
        raise _invalid("formula", "Formulas have at most 2,000 characters.")
    found = check(ctx, entity_id, data.formula, data.display)
    if not found.ok:
        raise ValidationFailedError(
            "The formula cannot be used yet.", field_errors={"formula": found.problems}
        )
    return found


def visible(ctx: WorkspaceContext, entity_id: UUID) -> list[CustomKpi]:
    """Every workspace KPI version, and the user's own personal ones."""
    entity = get_entity(ctx, entity_id, READ)
    rows = CustomKpi.objects.filter(legal_entity=entity).select_related("owner", "decided_by")
    return [
        k
        for k in rows.order_by("key", "version")
        if k.scope == Scope.WORKSPACE or k.owner_id == ctx.user.id
    ]


def _get(ctx: WorkspaceContext, entity_id: UUID, kpi_id: UUID, *, lock: bool = False) -> CustomKpi:
    entity = get_entity(ctx, entity_id, READ)
    rows = CustomKpi.objects.filter(legal_entity=entity, id=kpi_id)
    found: CustomKpi | None = (rows.select_for_update() if lock else rows).first()
    if found is None or (found.scope == Scope.PERSONAL and found.owner_id != ctx.user.id):
        raise NotFoundError("KPI not found.")
    return found


def _may_manage(ctx: WorkspaceContext, entity_id: UUID, scope: str) -> None:
    if scope == Scope.WORKSPACE and not ctx.can(MANAGE, entity_id):
        raise PermissionDeniedError("You do not have permission to propose workspace KPIs.")


@transaction.atomic
def create(ctx: WorkspaceContext, entity_id: UUID, scope: str, data: KpiInput) -> CustomKpi:
    entity = get_entity(ctx, entity_id, READ)
    if scope not in Scope.values:
        raise _invalid("scope", "Choose personal or workspace.")
    _may_manage(ctx, entity.id, scope)
    found = _validated(ctx, entity.id, data)
    if CustomKpi.objects.filter(legal_entity=entity, key=data.key).exists():
        raise ConflictError("A KPI with this key exists; change it with a new version.")
    return _save(ctx, entity.id, scope, data, found, version=1, supersedes=None)


def _save(  # noqa: PLR0913 (the new version and what it follows)
    ctx: WorkspaceContext,
    entity_id: UUID,
    scope: str,
    data: KpiInput,
    found: Check,
    *,
    version: int,
    supersedes: CustomKpi | None,
) -> CustomKpi:
    try:
        with transaction.atomic():
            made = CustomKpi.objects.create(
                tenant_id=ctx.tenant.id,
                legal_entity_id=entity_id,
                key=data.key,
                version=version,
                scope=scope,
                owner_id=ctx.user.id,
                name=data.name.strip(),
                formula=data.formula,
                unit=found.unit or "",
                display=data.display,
                direction=data.direction,
                convention=data.convention.strip(),
                status=Status.ACTIVE if scope == Scope.PERSONAL else Status.SUBMITTED,
                supersedes=supersedes,
            )
    except IntegrityError as exc:  # pragma: no cover (two versions saved at the same moment)
        raise ConflictError("Another version was saved at the same time; reload.") from exc
    _audit(
        ctx,
        entity_id,
        "custom_kpi",
        made.id,
        "kpi.custom.saved",
        {"key": made.key, "version": version, "scope": scope, "status": made.status},
    )
    return made


@transaction.atomic
def revise(ctx: WorkspaceContext, entity_id: UUID, kpi_id: UUID, data: KpiInput) -> CustomKpi:
    """A new version of a KPI in use (personal: in use at once; workspace: to approve)."""
    current = _get(ctx, entity_id, kpi_id, lock=True)
    if current.status not in IN_USE or current.key != data.key:
        raise ConflictError("Only the version in use can be revised, under the same key.")
    _may_manage(ctx, entity_id, current.scope)
    if CustomKpi.objects.filter(
        legal_entity_id=current.legal_entity_id, key=current.key, status=Status.SUBMITTED
    ).exists():
        raise ConflictError("A new version is already waiting for approval.")
    found = _validated(ctx, entity_id, data)
    latest = CustomKpi.objects.filter(
        legal_entity_id=current.legal_entity_id, key=current.key
    ).aggregate(m=Max("version"))["m"]
    made = _save(ctx, entity_id, current.scope, data, found, version=latest + 1, supersedes=current)
    if current.scope == Scope.PERSONAL:
        _set_status(current, Status.SUPERSEDED)
    return made


def _set_status(kpi: CustomKpi, status: str, by: UUID | None = None, comment: str = "") -> None:
    kpi.status = status
    fields = ["status"]
    if by is not None:
        kpi.decided_by_id, kpi.decided_at, kpi.decision_comment = by, timezone.now(), comment
        fields += ["decided_by", "decided_at", "decision_comment"]
    kpi.save(update_fields=fields)


@transaction.atomic
def decide(
    ctx: WorkspaceContext, entity_id: UUID, kpi_id: UUID, *, approve: bool, comment: str = ""
) -> CustomKpi:
    entity = get_entity(ctx, entity_id, APPROVE)
    kpi = _get(ctx, entity.id, kpi_id, lock=True)
    if kpi.status != Status.SUBMITTED:
        raise ConflictError("Only a KPI waiting for approval can be approved or rejected.")
    if kpi.owner_id == ctx.user.id:
        raise ConflictError("Someone other than the author must decide (segregation of duties).")
    comment = comment.strip()[:500]
    if not approve and not comment:
        raise _invalid("comment", "Say why the KPI is rejected.")
    if approve:
        for old in CustomKpi.objects.select_for_update().filter(
            legal_entity=entity, key=kpi.key, status=Status.APPROVED
        ):
            _set_status(old, Status.SUPERSEDED)
    _set_status(kpi, Status.APPROVED if approve else Status.REJECTED, ctx.user.id, comment)
    _audit(
        ctx,
        entity.id,
        "custom_kpi",
        kpi.id,
        "kpi.custom.decided",
        {"key": kpi.key, "version": kpi.version, "status": kpi.status},
    )
    return kpi


@transaction.atomic
def retire(ctx: WorkspaceContext, entity_id: UUID, kpi_id: UUID) -> CustomKpi:
    kpi = _get(ctx, entity_id, kpi_id, lock=True)
    _may_manage(ctx, entity_id, kpi.scope)
    if kpi.status not in IN_USE:
        raise ConflictError("Only a KPI in use can be retired.")
    _set_status(kpi, Status.RETIRED)
    _audit(
        ctx,
        entity_id,
        "custom_kpi",
        kpi.id,
        "kpi.custom.retired",
        {"key": kpi.key, "version": kpi.version},
    )
    return kpi


def workspace_snapshot(entity_id: UUID) -> list[dict[str, str]]:
    """The approved workspace KPIs, as stored in a KPI set's inputs (their exact version)."""
    return [
        {
            "id": f"WORKSPACE:{k.key}@{k.version}",
            "key": k.key,
            "formula": k.formula,
            "name": k.name,
            "display": k.display,
            "direction": k.direction,
            "convention": k.convention,
        }
        for k in CustomKpi.objects.filter(
            legal_entity_id=entity_id, scope=Scope.WORKSPACE, status=Status.APPROVED
        ).order_by("key")
    ]


def personal_values(
    ctx: WorkspaceContext, entity_id: UUID, run_id: UUID
) -> tuple[list[CustomKpi], list[Value]]:
    """The user's personal KPIs on a stored KPI set's pinned data (watermark, mapping and
    operational values of the run). Nothing is stored: only the owner ever sees them."""
    run = get_calc_run(ctx, entity_id, run_id)
    if run.kind != KIND:
        raise NotFoundError("KPI set not found.")
    mine = [
        k
        for k in visible(ctx, entity_id)
        if k.scope == Scope.PERSONAL and k.status == Status.ACTIVE
    ]
    if not mine:
        return [], []
    refs = run.input_refs
    values = _evaluate(
        ctx,
        entity_id,
        (date.fromisoformat(refs["date_from"]), date.fromisoformat(refs["date_to"])),
        [
            {
                "id": f"PERSONAL:{k.key}@{k.version}",
                "key": k.key,
                "formula": k.formula,
                "nm_reason": "",
            }
            for k in mine
        ],
        pinned=(refs, run.actuals_watermark),
    )
    return mine, values


# --- operational metrics --------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricInput:
    key: str
    name: str
    unit: str
    aggregation: str


def metrics(ctx: WorkspaceContext, entity_id: UUID) -> list[OperationalMetric]:
    entity = get_entity(ctx, entity_id, READ)
    return list(OperationalMetric.objects.filter(legal_entity=entity).order_by("key"))


@transaction.atomic
def create_metric(ctx: WorkspaceContext, entity_id: UUID, data: MetricInput) -> OperationalMetric:
    entity = get_entity(ctx, entity_id, OPERATIONAL)
    if not KEY.match(data.key):
        raise _invalid("key", "Keys are 2 to 40 capital letters, digits or _, e.g. HEADCOUNT.")
    if not data.name.strip() or len(data.name) > 120:
        raise _invalid("name", "Give a name (up to 120 characters).")
    if data.unit not in OperationalMetric.Unit.values:
        raise _invalid("unit", "Choose a count or an amount in EUR.")
    if data.aggregation not in OperationalMetric.Aggregation.values:
        raise _invalid("aggregation", "Choose point in time (last month) or a total.")
    try:
        with transaction.atomic():
            made = OperationalMetric.objects.create(
                tenant_id=ctx.tenant.id,
                legal_entity=entity,
                key=data.key,
                name=data.name.strip(),
                unit=data.unit,
                aggregation=data.aggregation,
                created_by_id=ctx.user.id,
            )
    except IntegrityError as exc:
        raise ConflictError("A metric with this key exists.") from exc
    _audit(
        ctx,
        entity.id,
        "operational_metric",
        made.id,
        "kpi.operational.created",
        {"key": made.key, "unit": made.unit, "aggregation": made.aggregation},
    )
    return made


def current_values(metric: OperationalMetric) -> dict[date, OperationalValue]:
    rows = OperationalValue.objects.filter(metric=metric, superseded_at__isnull=True)
    return {v.month: v for v in rows.order_by("month")}


@transaction.atomic
def set_value(
    ctx: WorkspaceContext, entity_id: UUID, metric_id: UUID, month: date, value: str, note: str = ""
) -> OperationalValue:
    """Enter or correct one month's value; a correction keeps the earlier value."""
    entity = get_entity(ctx, entity_id, OPERATIONAL)
    metric = OperationalMetric.objects.filter(legal_entity=entity, id=metric_id).first()
    if metric is None:
        raise NotFoundError("Metric not found.")
    if month.day != 1:
        raise _invalid("month", "Give the first day of the month.")
    try:
        amount = Decimal(value.strip())
    except InvalidOperation as exc:
        raise _invalid("value", "Enter a number.") from exc
    if (
        not amount.is_finite()
        or amount != amount.quantize(Decimal("0.0001"))
        or abs(amount) >= 10**15
    ):
        raise _invalid("value", "Enter a number with at most 4 decimals.")
    if metric.unit == OperationalMetric.Unit.COUNT and amount < 0:
        raise _invalid("value", "A count cannot be negative.")
    previous = (
        OperationalValue.objects.select_for_update()
        .filter(metric=metric, month=month, superseded_at__isnull=True)
        .first()
    )
    version = 1
    if previous is not None:
        previous.superseded_at = timezone.now()
        previous.save(update_fields=["superseded_at"])
        version = previous.version + 1
    made = OperationalValue.objects.create(
        tenant_id=ctx.tenant.id,
        legal_entity=entity,
        metric=metric,
        month=month,
        value=amount,
        version=version,
        note=note.strip()[:300],
        created_by_id=ctx.user.id,
    )
    _audit(
        ctx,
        entity.id,
        "operational_metric",
        metric.id,
        "kpi.operational.value_set",
        {
            "month": month.isoformat(),
            "value": str(amount),
            "version": version,
            "previous": str(previous.value) if previous else None,
        },
    )
    return made


def value_history(
    ctx: WorkspaceContext, entity_id: UUID, metric_id: UUID, month: date
) -> list[OperationalValue]:
    entity = get_entity(ctx, entity_id, READ)
    return list(
        OperationalValue.objects.filter(legal_entity=entity, metric_id=metric_id, month=month)
        .select_related("created_by")
        .order_by("version")
    )


def operational_snapshot(entity_id: UUID, date_from: date, date_to: date) -> dict[str, Any]:
    """Current operational values for the period and the year before, as stored in a run."""
    first = add_months(date_from, -12)
    out: dict[str, Any] = {}
    for metric in OperationalMetric.objects.filter(legal_entity_id=entity_id):
        values = {
            m.isoformat(): format(v.value.normalize(), "f")
            for m, v in current_values(metric).items()
            if first <= m <= date_to
        }
        out[metric.key] = {
            "name": metric.name,
            "unit": metric.unit,
            "aggregation": metric.aggregation,
            "values": values,
        }
    return out
