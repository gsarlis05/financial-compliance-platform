"""Sensitivity and tornado as a service (M7-3): the base, a cache by input hash, quotas and a
time limit (doc 02: "Sensitivity/scenario sandbox runs are cached (keyed by input hash) and not
persisted"; threat T34: per-user and per-tenant quotas, input-hash caching, run timeouts).

- **Base:** an approved assumption set, or a shared scenario (its overrides applied first),
  projected on the current books (the ledger watermark is part of the input hash).
- **Cache:** the same request on the same inputs returns the cached result (``cached`` true) for
  ``SENSITIVITY_CACHE_SECONDS``; a cached answer costs no quota. Nothing is stored in the database.
- **Quotas:** each engine run counts; at most ``SENSITIVITY_RUNS_PER_MINUTE_USER`` runs a minute
  per user and ``SENSITIVITY_RUNS_PER_MINUTE_TENANT`` per workspace (HTTP 429 beyond them).
- **Time limit:** ``SENSITIVITY_TIME_LIMIT_SECONDS`` per request (HTTP 409 beyond it).
The cache and the quota counters use Django's cache; with more than one server process, production
needs a shared cache for them to be exact (a known limitation until the pilot's cache exists).
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache

from fcp.core.errors import ConflictError, DomainError, ValidationFailedError
from fcp.modules.metrics.api import canonical_digest
from fcp.modules.projections.api import EngineInput, load_input, pin
from fcp.modules.reporting.api import current_watermark
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import sensitivity as sens
from . import services
from .apply import apply
from .models import Scenario
from .runs import _refs, items_of

RUN = services.RUN
ENGINE_STATUS = "PENDING_PROFESSIONAL_REVIEW"


class QuotaExceededError(DomainError):
    code = "quota_exceeded"
    status = 429
    title = "Too many analyses"


def _setting(name: str, default: int) -> int:
    return int(getattr(settings, name, default))


@dataclass(frozen=True)
class Base:
    inp: EngineInput
    refs: dict[str, Any]
    label: str
    watermark: int


def base(ctx: WorkspaceContext, entity_id: UUID, *, set_id: UUID | None,
         scenario_id: UUID | None) -> Base:  # fmt: skip
    """The engine input to shock: an approved set, or a shared scenario with its overrides."""
    get_entity(ctx, entity_id, RUN)
    if (set_id is None) == (scenario_id is None):
        message = "Name either an approved assumption set or a shared scenario as the base."
        raise ValidationFailedError(message, field_errors={"base": [message]})
    watermark = current_watermark(ctx, entity_id)
    if set_id is not None:
        refs = pin(ctx, entity_id, set_id)
        inp = load_input(ctx, entity_id, refs, watermark)
        return Base(inp, {"set": refs}, f"Assumption set {set_id}", watermark)
    assert scenario_id is not None  # noqa: S101 (checked above)
    s = services.get(ctx, entity_id, scenario_id, RUN)
    if s.status != Scenario.Status.SHARED:
        raise ConflictError("Share the scenario before analysing its sensitivity.")
    refs = _refs(ctx, entity_id, s)
    inp = apply(load_input(ctx, entity_id, refs["base"], watermark), items_of(refs)).inp
    return Base(inp, {"scenario": refs}, f"Scenario {s.name}", watermark)


def _charge(ctx: WorkspaceContext, runs: int) -> None:
    """Count ``runs`` engine runs against the user's and the workspace's quota for the minute."""
    minute = int(time.time() // 60)
    limits = (
        (f"sens:user:{ctx.user.id}:{minute}", _setting("SENSITIVITY_RUNS_PER_MINUTE_USER", 300)),
        (f"sens:tenant:{ctx.tenant.id}:{minute}",
         _setting("SENSITIVITY_RUNS_PER_MINUTE_TENANT", 1200)),
    )  # fmt: skip
    for key, limit in limits:
        cache.add(key, 0, timeout=120)
        try:
            used = cache.incr(key, runs)
        except ValueError:  # expired between add and incr
            cache.set(key, runs, timeout=120)
            used = runs
        if used > limit:
            raise QuotaExceededError(
                f"Too many analyses this minute (at most {limit} projection runs). "
                "Wait a minute, or analyse fewer drivers or steps."
            )


@dataclass(frozen=True)
class Analysis:
    kind: str  # ONE_VARIABLE or TORNADO
    output: str
    year: int | None
    base_label: str
    base_value: sens.Measure
    points: list[sens.Point]
    bars: list[sens.Bar]
    input_hash: str
    watermark: int
    cached: bool


def _cached(ctx: WorkspaceContext, b: Base, request: dict[str, Any],
            runs: int, compute: Any) -> Analysis:  # fmt: skip
    digest = canonical_digest({"tenant": str(ctx.tenant.id), "base": b.refs,
                               "watermark": b.watermark, "request": request})  # fmt: skip
    key = f"sens:result:{digest}"
    found = cache.get(key)
    if isinstance(found, Analysis):
        return Analysis(**{**found.__dict__, "cached": True})
    _charge(ctx, runs)
    deadline = time.monotonic_ns() + _setting("SENSITIVITY_TIME_LIMIT_SECONDS", 30) * 10**9
    made: Analysis = compute(deadline, digest)
    cache.set(key, made, timeout=_setting("SENSITIVITY_CACHE_SECONDS", 600))
    return made


def one_variable(  # noqa: PLR0913 (keyword-only request)
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    set_id: UUID | None,
    scenario_id: UUID | None,
    driver: str,
    unit: str,
    low: Decimal,
    high: Decimal,
    steps: int,
    output: str,
    year: int | None,
) -> Analysis:
    b = base(ctx, entity_id, set_id=set_id, scenario_id=scenario_id)
    values = sens.steps_of(low, high, steps)
    sens.shock(b.inp, driver)  # checks the driver
    request = {"kind": "ONE_VARIABLE", "driver": driver, "unit": unit, "values": values,
               "output": output, "year": year}  # fmt: skip

    def compute(deadline: int, digest: str) -> Analysis:
        base_value = sens.run(b.inp, output, year, deadline)
        points = sens.one_variable(b.inp, driver, values, unit=unit, output=output, year=year,
                                   deadline=deadline)  # fmt: skip
        return Analysis("ONE_VARIABLE", output, year, b.label, base_value, points, [], digest,
                        b.watermark, cached=False)  # fmt: skip

    return _cached(ctx, b, request, len(values) + 1, compute)


def tornado(  # noqa: PLR0913 (keyword-only request)
    ctx: WorkspaceContext,
    entity_id: UUID,
    *,
    set_id: UUID | None,
    scenario_id: UUID | None,
    drivers: list[str],
    percent: Decimal,
    output: str,
    year: int | None,
) -> Analysis:
    b = base(ctx, entity_id, set_id=set_id, scenario_id=scenario_id)
    if not Decimal(0) < percent <= Decimal(100):
        message = "percent: from more than 0 to 100."
        raise ValidationFailedError(message, field_errors={"percent": [message]})
    chosen = drivers or _default_drivers(b.inp)
    request = {"kind": "TORNADO", "drivers": chosen, "percent": percent, "output": output,
               "year": year}  # fmt: skip

    def compute(deadline: int, digest: str) -> Analysis:
        base_value = sens.run(b.inp, output, year, deadline)
        bars = sens.tornado(b.inp, chosen, percent=percent, output=output, year=year,
                            deadline=deadline)  # fmt: skip
        return Analysis("TORNADO", output, year, b.label, base_value, [], bars, digest,
                        b.watermark, cached=False)  # fmt: skip

    return _cached(ctx, b, request, 2 * len(chosen) + 1, compute)


def _default_drivers(inp: EngineInput) -> list[str]:
    """The drivers the base actually uses: every line with an amount, and the ratios and days."""
    used = []
    for d in sens.DRIVERS:
        if d in ("revenue", "opex"):
            continue  # the lines are listed one by one
        keys = sens.keys_of(d)
        if any(v for k in keys for v in inp.drivers.get(k, {}).values()) or (
                d == "interest_rate" and inp.loans):  # fmt: skip
            used.append(d)
    return used[: sens.MAX_DRIVERS]
