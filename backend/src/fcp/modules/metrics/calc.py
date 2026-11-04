"""Calculation runs: pinned inputs, hashed outputs, lineage, reproducibility (M3-2, doc 10 §2.3).

An engine (the 13-week cash forecast, KPIs, ...) has two parts:
- ``load(ctx, inputs)`` reads what it needs, **pinned** to ``inputs``. Actuals come from
  ``reporting`` at ``inputs.actuals_watermark``, and other data only from immutable versions named
  in ``inputs.refs``.
- ``compute(inputs, data)`` is a pure function: no clock, no randomness, no floats, no database.

``execute`` records the run with its input hash, every value with its nature and lineage, and the
output hash. ``reproduce`` loads and computes again from the stored inputs and compares the
hashes. Because posted entries are append-only, actuals at a watermark never change, so a run that
does not reproduce means the engine or its pinning is wrong.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import ConflictError, DomainError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.reporting.api import current_watermark
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .hashing import digest, jsonable
from .models import VALUE_DIGITS, VALUE_PLACES, CalcLineage, CalcResult, CalcRun
from .nature import Nature

GRANULARITIES = frozenset(CalcResult.Granularity.values)
INPUT_KINDS = frozenset(CalcLineage.InputKind.values)


@dataclass(frozen=True)
class RunInputs:
    """Everything a run depends on. ``refs`` is plain JSON data (as stored), e.g. the IDs of the
    assumption-set and plan versions used, or the forecast settings."""

    kind: str
    engine_version: str
    legal_entity_id: UUID
    as_of: date
    actuals_watermark: int
    refs: Mapping[str, Any] = field(default_factory=dict)

    def digest(self) -> str:
        return digest({
            "kind": self.kind, "engine_version": self.engine_version,
            "legal_entity_id": self.legal_entity_id, "as_of": self.as_of,
            "actuals_watermark": self.actuals_watermark, "refs": self.refs,
        })  # fmt: skip


@dataclass(frozen=True)
class Source:
    """One input that contributed to a value (doc 10 P6)."""

    kind: str  # CalcLineage.InputKind
    ref: str  # e.g. "account:<id>:2026-11", "open_item:<id>", "assumption:<id>"
    amount: Decimal | None = None
    note: str = ""


@dataclass(frozen=True)
class Value:
    series_key: str
    period_start: date
    nature: Nature
    value: Decimal | None
    unit: str  # EUR, ratio, percent, days, count, times
    period_end: date | None = None  # defaults to period_start
    granularity: str = "POINT"
    nm_reason: str = ""  # set, with value None, when the value is not meaningful
    dimensions: tuple[str, ...] = ()
    lineage: tuple[Source, ...] = ()

    @property
    def end(self) -> date:
        return self.period_end or self.period_start


@dataclass(frozen=True)
class Output:
    values: tuple[Value, ...]
    invariants: Mapping[str, bool] = field(default_factory=dict)

    def digest(self) -> str:
        return digest({
            "values": [_value_form(v) for v in self.values],
            "invariants": dict(self.invariants),
        })  # fmt: skip


def _value_form(v: Value) -> dict[str, object]:
    return {
        "series_key": v.series_key, "dimensions": list(v.dimensions),
        "period_start": v.period_start, "period_end": v.end, "granularity": v.granularity,
        "nature": v.nature, "value": v.value, "unit": v.unit, "nm_reason": v.nm_reason,
        "lineage": [{"kind": s.kind, "ref": s.ref, "amount": s.amount, "note": s.note}
                    for s in v.lineage],
    }  # fmt: skip


class Engine(Protocol):
    kind: str
    version: str

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> Any: ...

    def compute(self, inputs: RunInputs, data: Any) -> Output: ...


_ENGINES: dict[str, Engine] = {}


def register(engine: Engine) -> Engine:
    """Make an engine available by its kind (one engine per kind)."""
    existing = _ENGINES.get(engine.kind)
    if existing is not None and existing is not engine:
        raise ValueError(f"an engine for {engine.kind} is already registered")
    _ENGINES[engine.kind] = engine
    return engine


def engine_for(kind: str) -> Engine:
    try:
        return _ENGINES[kind]
    except KeyError:
        raise NotFoundError(f"No calculation engine for {kind}.") from None


# --- checking an engine's output ------------------------------------------------------------------


class EngineOutputError(ValueError):
    """The engine produced something the framework does not store (a bug in the engine)."""


def _fits(amount: Decimal) -> bool:
    if not amount.is_finite():
        return False
    exponent = cast(int, amount.as_tuple().exponent)  # an int for every finite Decimal
    integer_digits = max(amount.adjusted() + 1, 0)
    return exponent >= -VALUE_PLACES and integer_digits <= VALUE_DIGITS - VALUE_PLACES


def _check(output: Output) -> None:  # noqa: PLR0912 (one check per rule)
    if not isinstance(output, Output):
        raise EngineOutputError("an engine returns an Output")
    for name, passed in output.invariants.items():
        if not isinstance(name, str) or not isinstance(passed, bool):
            raise EngineOutputError("invariants map names to True or False")
    for v in output.values:
        if not isinstance(v.nature, Nature):
            raise EngineOutputError(f"{v.series_key}: every value has a Nature")
        if not v.series_key or len(v.series_key) > 120:
            raise EngineOutputError("series keys are 1 to 120 characters")
        if not v.unit or len(v.unit) > 10:
            raise EngineOutputError(f"{v.series_key}: units are 1 to 10 characters")
        if v.granularity not in GRANULARITIES:
            raise EngineOutputError(f"{v.series_key}: unknown granularity {v.granularity}")
        if v.end < v.period_start:
            raise EngineOutputError(f"{v.series_key}: the period ends before it starts")
        if (v.value is None) == (not v.nm_reason) or len(v.nm_reason) > 200:
            raise EngineOutputError(f"{v.series_key}: a value, or a not-meaningful reason")
        if v.value is not None and (not isinstance(v.value, Decimal) or not _fits(v.value)):
            raise EngineOutputError(f"{v.series_key}: values are Decimals that fit the store")
        for s in v.lineage:
            if s.kind not in INPUT_KINDS or not s.ref or len(s.ref) > 200 or len(s.note) > 200:
                raise EngineOutputError(f"{v.series_key}: invalid lineage {s.kind}:{s.ref}")
            if s.amount is not None and (not isinstance(s.amount, Decimal) or not _fits(s.amount)):
                raise EngineOutputError(f"{v.series_key}: lineage amounts are Decimals")


# --- running --------------------------------------------------------------------------------------


def _audit(ctx: WorkspaceContext, run: CalcRun, action: str, changes: dict[str, object]) -> None:
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=action,
          subject_type="calc_run", subject_id=run.id, entity_id=run.legal_entity_id,
          changes=changes)  # fmt: skip


def _compute(ctx: WorkspaceContext, engine: Engine, inputs: RunInputs) -> Output:
    # A savepoint: an engine failure must not poison the transaction that records the failure.
    with transaction.atomic():
        data = engine.load(ctx, inputs)
    output = engine.compute(inputs, data)
    _check(output)
    return output


def _plain_refs(refs: Mapping[str, Any] | None) -> dict[str, Any]:
    """Refs as stored: plain JSON data, so a run and its re-run see exactly the same."""
    try:
        plain = jsonable(dict(refs or {}))
    except (TypeError, ValueError) as error:
        raise ValidationFailedError(f"Run references are invalid: {error}.",
                                    field_errors={"refs": ["invalid"]}) from None  # fmt: skip
    if len(text := str(plain)) > 10_000:
        raise ValidationFailedError(f"Run references are too large ({len(text)} chars).",
                                    field_errors={"refs": ["too large"]})  # fmt: skip
    return cast(dict[str, Any], plain)


@transaction.atomic
def execute(
    ctx: WorkspaceContext,
    entity_id: UUID,
    kind: str,
    *,
    as_of: date,
    refs: Mapping[str, Any] | None = None,
    trigger: str = CalcRun.Trigger.USER,
) -> CalcRun:
    """Run the engine for ``kind`` on the current actuals and record the run and its values.
    User errors (permissions, validation) propagate; an engine failure is recorded as FAILED."""
    entity = get_entity(ctx, entity_id, "planning.run")
    engine = engine_for(kind)
    inputs = RunInputs(kind, engine.version, entity.id, as_of,
                       current_watermark(ctx, entity.id), _plain_refs(refs))  # fmt: skip
    run = CalcRun(
        tenant=ctx.tenant, legal_entity=entity, kind=kind, engine_version=engine.version,
        actuals_watermark=inputs.actuals_watermark, as_of_date=as_of, input_refs=inputs.refs,
        input_hash=inputs.digest(), trigger=trigger,
        created_by=ctx.user if trigger == CalcRun.Trigger.USER else None,
    )  # fmt: skip
    try:
        output = _compute(ctx, engine, inputs)
    except DomainError:
        raise
    except Exception as failure:  # noqa: BLE001 (any engine bug becomes a FAILED run, kept)
        run.status = CalcRun.Status.FAILED
        run.error = f"{type(failure).__name__}: {failure}"[:500]
        run.finished_at = timezone.now()
        run.save(force_insert=True)
        _audit(ctx, run, "metrics.calc_run.failed", {"kind": kind, "error": run.error})
        return run
    run.status = CalcRun.Status.RUNNING
    run.save(force_insert=True)
    _store(run, output)
    run.output_hash = output.digest()
    run.invariant_results = dict(output.invariants)
    run.status = (CalcRun.Status.VALID if all(output.invariants.values())
                  else CalcRun.Status.INVALID)  # fmt: skip
    run.finished_at = timezone.now()
    run.save(update_fields=["output_hash", "invariant_results", "status", "finished_at"])
    _audit(ctx, run, "metrics.calc_run.created", {
        "kind": kind, "status": run.status, "as_of": as_of.isoformat(),
        "actuals_watermark": run.actuals_watermark, "input_hash": run.input_hash,
        "output_hash": run.output_hash, "values": len(output.values),
    })  # fmt: skip
    return run


def _store(run: CalcRun, output: Output) -> None:
    results = [
        CalcResult(
            tenant_id=run.tenant_id, run=run, seq=i, series_key=v.series_key,
            dimensions=list(v.dimensions), period_start=v.period_start, period_end=v.end,
            granularity=v.granularity, nature=v.nature.value, value=v.value, unit=v.unit,
            nm_reason=v.nm_reason,
        )
        for i, v in enumerate(output.values)
    ]  # fmt: skip
    CalcResult.objects.bulk_create(results)
    CalcLineage.objects.bulk_create(
        CalcLineage(tenant_id=run.tenant_id, result=r, seq=j, input_kind=s.kind,
                    input_ref=s.ref, amount=s.amount, note=s.note)
        for r, v in zip(results, output.values, strict=True)
        for j, s in enumerate(v.lineage)
    )  # fmt: skip


# --- reading, explaining, reproducing -------------------------------------------------------------


def list_runs(ctx: WorkspaceContext, entity_id: UUID, kind: str | None = None,
              limit: int = 50) -> list[CalcRun]:  # fmt: skip
    entity = get_entity(ctx, entity_id, "planning.read")
    runs = CalcRun.objects.filter(legal_entity=entity)
    if kind:
        runs = runs.filter(kind=kind)
    return list(runs.order_by("-created_at", "-id")[: max(1, min(limit, 200))])


def get_run(ctx: WorkspaceContext, entity_id: UUID, run_id: UUID) -> CalcRun:
    entity = get_entity(ctx, entity_id, "planning.read")
    run = CalcRun.objects.filter(legal_entity=entity, id=run_id).first()
    if run is None:
        raise NotFoundError("Calculation run not found.")
    return run


def results(run: CalcRun) -> list[CalcResult]:
    return list(CalcResult.objects.filter(run=run).order_by("seq"))


def explain(ctx: WorkspaceContext, entity_id: UUID, run_id: UUID,
            result_id: UUID) -> tuple[CalcResult, list[CalcLineage]]:  # fmt: skip
    """A value and what it was computed from (doc 10 §2.3 "Explain this number")."""
    run = get_run(ctx, entity_id, run_id)
    result = CalcResult.objects.filter(run=run, id=result_id).first()
    if result is None:
        raise NotFoundError("Result not found.")
    return result, list(CalcLineage.objects.filter(result=result).order_by("seq"))


def stored_output(run: CalcRun) -> Output:
    """The run's output as stored, to check it still hashes to ``output_hash``."""
    lineage: dict[UUID, list[Source]] = {}
    for item in CalcLineage.objects.filter(result__run=run).order_by("result__seq", "seq"):
        lineage.setdefault(item.result_id, []).append(
            Source(item.input_kind, item.input_ref, item.amount, item.note)
        )
    values = tuple(
        Value(r.series_key, r.period_start, Nature(r.nature), r.value, r.unit, r.period_end,
              r.granularity, r.nm_reason, tuple(r.dimensions), tuple(lineage.get(r.id, ())))
        for r in results(run)
    )  # fmt: skip
    return Output(values, run.invariant_results)


@dataclass(frozen=True)
class Reproduction:
    run_id: UUID
    reproduced: bool
    stored_intact: bool
    output_hash: str
    recomputed_hash: str
    reason: str = ""


def reproduce(ctx: WorkspaceContext, entity_id: UUID, run_id: UUID) -> Reproduction:
    """Load and compute again from the stored inputs; the output hash must be identical
    (AC-CF3). Nothing new is stored except the audit event."""
    get_entity(ctx, entity_id, "planning.run")
    run = get_run(ctx, entity_id, run_id)
    if run.status == CalcRun.Status.FAILED:
        raise ConflictError("A failed run has no output to reproduce.")
    stored_intact = stored_output(run).digest() == run.output_hash
    engine = engine_for(run.kind)
    inputs = RunInputs(run.kind, run.engine_version, run.legal_entity_id, run.as_of_date,
                       run.actuals_watermark, run.input_refs)  # fmt: skip
    reason, recomputed = "", ""
    if inputs.digest() != run.input_hash:
        reason = "the stored inputs no longer match their hash"
    elif engine.version != run.engine_version:
        reason = f"the engine changed from {run.engine_version} to {engine.version}"
    else:
        recomputed = _compute(ctx, engine, inputs).digest()
        if recomputed != run.output_hash:
            reason = "the output differs"
    if not reason and not stored_intact:
        reason = "the stored values no longer match the output hash"
    result = Reproduction(run.id, not reason, stored_intact, run.output_hash, recomputed, reason)
    _audit(ctx, run, "metrics.calc_run.reproduced",
           {"reproduced": result.reproduced, "reason": result.reason})  # fmt: skip
    return result


# --- lifecycle ------------------------------------------------------------------------------------


@transaction.atomic
def publish(ctx: WorkspaceContext, entity_id: UUID, run_id: UUID) -> CalcRun:
    """Publish a valid, current run. Published runs are immutable (P5)."""
    get_entity(ctx, entity_id, "planning.publish")
    run = get_run(ctx, entity_id, run_id)
    if run.is_published:
        return run
    if run.status != CalcRun.Status.VALID:
        raise ConflictError(f"Only a valid run can be published; this one is {run.status}.")
    if run.stale:
        raise ConflictError("The data changed after this run. Run it again, then publish.")
    run.is_published = True
    run.save(update_fields=["is_published"])
    _audit(ctx, run, "metrics.calc_run.published", {"kind": run.kind})
    return run


def mark_stale(entity_id: UUID, kinds: list[str] | None = None) -> int:
    """Mark the entity's finished runs stale (newer data exists); returns how many changed. Called
    on events such as a posting or a reconciliation (M3-8), within the caller's tenant context."""
    runs = CalcRun.objects.filter(legal_entity_id=entity_id, stale=False).exclude(
        status=CalcRun.Status.RUNNING
    )
    if kinds is not None:
        runs = runs.filter(kind__in=kinds)
    return runs.update(stale=True)
