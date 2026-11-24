"""Scenario runs, the comparison with the base, and promotion (M7-2, doc 10 §8, brief 21 §3).

- **A scenario run** projects the scenario's approved base with its overrides applied in order
  (``apply.py``), through the unchanged projection engine, so it is checked by the same eight
  invariants. Every projected value is ``HYPOTHETICAL``; the opening balance sheet stays
  ``ACTUAL``.
- **Lineage by override:** the run is computed step by step (the base, then the first override,
  then the first two, ...). A value's change at each step is the effect of that override; it is
  listed in the value's lineage with the override's id and the amount. The "what changed and why"
  table sums these effects, and by construction they add up exactly to the total difference.
- **In memory or saved:** the comparison is computed on demand and not stored. Saving records a
  calculation run of kind ``SCENARIO`` (inputs pinned: the base's projection inputs, the overrides
  as they were, the ledger watermark), which reproduces like any run and is never published.
- **Promotion** creates an assumption-set **draft** from the base with the overrides written into
  its values and loans; it then needs the normal approval. Overrides a set cannot hold (a
  liability settlement, capex with another life in a month that already has capex) are refused.
"""

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.metrics.api import (
    CalcRun,
    Nature,
    Output,
    RunInputs,
    Source,
    Value,
    execute,
    list_calc_runs,
    register_engine,
)
from fcp.modules.projections.api import (
    EngineInput,
    Projection,
    SetInfo,
    derive_set,
    load_input,
    pin,
    project,
    set_info,
)
from fcp.modules.reporting.api import current_watermark
from fcp.modules.tenancy.api import WorkspaceContext

from . import services
from .apply import Applied, Item, apply
from .models import Scenario

KIND = "SCENARIO"
ZERO = Decimal("0.00")
RUN, READ = services.RUN, services.READ
HEADLINES = ("PL.REVENUE", "PL.EBITDA", "PL.NET_INCOME", "CF.NET_CHANGE")  # flows: summed
BALANCES = ("BS.CASH", "BS.DEBT")  # at the end of the horizon (BS.DEBT: current + non-current)
STATEMENTS = ("PL.", "BS.", "CF.")
PREFIX = "scenario_override:"
Key = tuple[str, date, date, str]  # series, start, end, granularity


def _key(v: Value) -> Key:
    return (v.series_key, v.period_start, v.end, v.granularity)


def items_of(refs: dict[str, Any]) -> list[Item]:
    return [Item(o["id"], int(o["seq"]), o["type"], o["params"]) for o in refs["overrides"]]


@dataclass(frozen=True)
class Steps:
    """The base and each cumulative step: ``outputs[0]`` is the base, ``outputs[k]`` the base
    with the first k overrides."""

    items: list[Item]
    outputs: list[Output]
    base: Projection
    final: Projection
    applied: Applied


def steps(base: EngineInput, items: list[Item]) -> Steps:
    items = sorted(items, key=lambda x: x.seq)
    base_projection, base_output = project(base)
    outputs, final, applied = [base_output], base_projection, apply(base, [])
    for k in range(1, len(items) + 1):
        applied = apply(base, items[:k])
        final, out = project(applied.inp)
        outputs.append(out)
    return Steps(items, outputs, base_projection, final, applied)


def hypothetical(s: Steps) -> Output:
    """The scenario's output: the last step's values as HYPOTHETICAL (the opening balance sheet
    stays ACTUAL), each with the overrides that changed it in its lineage."""
    by_step = [{_key(v): v.value for v in o.values} for o in s.outputs]
    values = []
    for v in s.outputs[-1].values:
        key = _key(v)
        effects = []
        for k, item in enumerate(s.items, start=1):
            before, after = by_step[k - 1].get(key) or ZERO, by_step[k].get(key) or ZERO
            if after != before:
                effects.append(Source("ASSUMPTION", f"{PREFIX}{item.id}",
                                      after - before, item.label))  # fmt: skip
        nature = Nature.ACTUAL if v.nature == Nature.ACTUAL else Nature.HYPOTHETICAL
        values.append(replace(v, nature=nature, lineage=(*v.lineage, *effects)))
    return Output(values=tuple(values), invariants=s.outputs[-1].invariants)


class ScenarioEngine:
    kind = KIND
    version = "1"
    publishable = False  # a scenario is hypothetical; it is promoted, never published

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> EngineInput:
        return load_input(ctx, inputs.legal_entity_id, dict(inputs.refs["base"]),
                          inputs.actuals_watermark)  # fmt: skip

    def compute(self, inputs: RunInputs, data: EngineInput) -> Output:
        return hypothetical(steps(data, items_of(dict(inputs.refs))))


ENGINE = register_engine(ScenarioEngine())


def _refs(ctx: WorkspaceContext, entity_id: UUID, s: Scenario) -> dict[str, Any]:
    return {
        "scenario_id": str(s.id),
        "scenario_name": s.name,
        "base_set_id": str(s.base_set_id),
        "base": pin(ctx, entity_id, s.base_set_id),
        "overrides": [{"id": str(o.id), "seq": o.seq, "type": o.type, "params": o.params}
                      for o in services.overrides(s)],
    }  # fmt: skip


# --- the comparison ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Column:
    start: date
    end: date
    nature: str  # of the scenario's figures: ACTUAL (the opening) or HYPOTHETICAL


@dataclass(frozen=True)
class Row:
    key: str
    base: list[Decimal | None]
    scenario: list[Decimal | None]
    overrides: list[list[str]]  # per column: the overrides (ids) that changed the value


@dataclass(frozen=True)
class Effect:
    override_id: str | None  # None: the total
    seq: int | None
    type: str
    label: str
    changes: dict[str, Decimal]  # headline -> change


@dataclass(frozen=True)
class Liquidity:
    lowest_cash: Decimal
    lowest_cash_month: date | None
    first_negative_month: date | None
    months_below_minimum: int
    peak_facility: Decimal
    closing_debt: Decimal


@dataclass(frozen=True)
class Comparison:
    scenario: Scenario
    base: SetInfo
    watermark: int
    columns: list[Column]
    rows: list[Row]
    effects: list[Effect]
    liquidity: dict[str, Liquidity]  # "base", "scenario"
    valid: bool
    failures: list[str]
    notes: list[str]


def _headlines(o: Output, months: list[date]) -> dict[str, Decimal]:
    monthly = [v for v in o.values if v.granularity == "MONTH" and v.nature != Nature.ACTUAL]
    sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
    last = months[-1]
    for v in monthly:
        if v.series_key in HEADLINES:
            sums[v.series_key] += v.value or ZERO
        elif v.period_start == last and v.series_key in ("BS.CASH", "BS.DEBT.CURRENT",
                                                         "BS.DEBT.NONCURRENT"):  # fmt: skip
            name = "BS.CASH" if v.series_key == "BS.CASH" else "BS.DEBT"
            sums[name] += v.value or ZERO
    return {k: sums[k] for k in (*HEADLINES, *BALANCES)}


def _liquidity(p: Projection, inp: EngineInput) -> Liquidity:
    cash = [(m.month, m.bs["BS.CASH"]) for m in p.months]
    lowest = min(cash, key=lambda x: (x[1], x[0]))
    minimum = inp.drivers.get(("minimum_cash", ""), {})
    last = p.months[-1].bs
    return Liquidity(
        lowest_cash=lowest[1], lowest_cash_month=lowest[0],
        first_negative_month=next((m for m, c in cash if c < 0), None),
        months_below_minimum=sum(1 for m, c in cash if c < minimum.get(m, ZERO)),
        peak_facility=max((m.other_debt.get("revolver", ZERO) for m in p.months), default=ZERO),
        closing_debt=last["BS.DEBT.CURRENT"] + last["BS.DEBT.NONCURRENT"],
    )  # fmt: skip


def _table(s: Steps, scenario_out: Output, granularity: str) -> tuple[list[Column], list[Row]]:
    def chosen(v: Value) -> bool:
        return v.series_key.startswith(STATEMENTS) and (
            v.granularity == granularity or v.nature == Nature.ACTUAL)  # fmt: skip

    base = {_key(v): v for v in s.outputs[0].values if chosen(v)}
    scen = {_key(v): v for v in scenario_out.values if chosen(v)}
    periods = sorted({(k[1], k[2], v.nature) for k, v in scen.items()},
                     key=lambda p: (p[0], p[2] != Nature.ACTUAL))  # fmt: skip
    columns = [Column(start, end, str(nature)) for start, end, nature in periods]
    keys = sorted({k[0] for k in (*base, *scen)})
    rows = []
    for series in keys:
        b: list[Decimal | None] = []
        sc: list[Decimal | None] = []
        changed: list[list[str]] = []
        for c in columns:
            g = "MONTH" if c.nature == Nature.ACTUAL else granularity
            k = (series, c.start, c.end, g)
            b.append(base[k].value if k in base else None)
            v = scen.get(k)
            sc.append(v.value if v else None)
            lineage = v.lineage if v else ()
            changed.append([x.ref.removeprefix(PREFIX) for x in lineage
                            if x.ref.startswith(PREFIX)])  # fmt: skip
        rows.append(Row(series, b, sc, changed))
    return columns, rows


def _effects(s: Steps) -> list[Effect]:
    months = s.applied.inp.months
    heads = [_headlines(o, months) for o in s.outputs]
    out = [
        Effect(item.id, item.seq, item.type, item.label,
               {h: heads[k][h] - heads[k - 1][h] for h in heads[0]})
        for k, item in enumerate(s.items, start=1)
    ]  # fmt: skip
    total = {h: heads[-1][h] - heads[0][h] for h in heads[0]}
    return [*out, Effect(None, None, "TOTAL", "Total change", total)]


def compare(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID,
            granularity: str = "MONTH") -> Comparison:  # fmt: skip
    """The scenario against its base, computed now on the current books (not stored)."""
    s = services.get(ctx, entity_id, scenario_id, RUN)
    refs = _refs(ctx, entity_id, s)
    watermark = current_watermark(ctx, entity_id)
    base_inp = load_input(ctx, entity_id, refs["base"], watermark)
    st = steps(base_inp, items_of(refs))
    out = hypothetical(st)
    columns, rows = _table(st, out, granularity)
    failures = sorted(k for k, ok in out.invariants.items() if not ok and "@" in k)
    return Comparison(
        scenario=s, base=set_info(ctx, entity_id, s.base_set_id), watermark=watermark,
        columns=columns, rows=rows, effects=_effects(st),
        liquidity={"base": _liquidity(st.base, base_inp),
                   "scenario": _liquidity(st.final, st.applied.inp)},
        valid=all(out.invariants.values()), failures=failures,
        notes=[*st.applied.notes, *st.final.notes],
    )  # fmt: skip


# --- saving and promoting ------------------------------------------------------------------------


def save(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> CalcRun:
    """Record the scenario's run as a calculation run (kind SCENARIO, never published)."""
    s = services.get(ctx, entity_id, scenario_id, RUN)
    refs = _refs(ctx, entity_id, s)
    run = execute(ctx, entity_id, KIND, as_of=date.fromisoformat(refs["base"]["cutover"]),
                  refs=refs)  # fmt: skip
    services.audit_scenario(ctx, "run_saved", s, run_id=str(run.id), status=run.status)
    return run


def runs(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> list[CalcRun]:
    s = services.get(ctx, entity_id, scenario_id, READ)
    return [r for r in list_calc_runs(ctx, entity_id, KIND, limit=100)
            if r.input_refs.get("scenario_id") == str(s.id)]  # fmt: skip


def promote(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID, *,
            name: str | None = None) -> Any:  # fmt: skip
    """An assumption-set draft from the scenario (its base with the overrides written in)."""
    s = services.get(ctx, entity_id, scenario_id, RUN)
    items = items_of(_refs(ctx, entity_id, s))
    if not items:
        raise ConflictError("The scenario has no overrides; there is nothing to promote.")
    base_inp = load_input(ctx, entity_id, pin(ctx, entity_id, s.base_set_id), None)
    applied = apply(base_inp, items)
    if applied.inexpressible:
        message = ("An assumption set cannot hold these overrides: "
                   + "; ".join(applied.inexpressible) + ".")  # fmt: skip
        raise ValidationFailedError(message, field_errors={"overrides": applied.inexpressible})
    made = derive_set(
        ctx, entity_id, s.base_set_id, name=name or f"{s.name} (from scenario)",
        note=f"Created from scenario “{s.name}” ({len(items)} override(s)); "
             "review and approve it like any set.",
        values=applied.drivers, new_loans=applied.new_loans,
    )  # fmt: skip
    services.audit_scenario(ctx, "promoted", s, assumption_set_id=str(made.id))
    return made


def summary(ctx: WorkspaceContext, entity_id: UUID, scenario_id: UUID) -> dict[str, Any]:
    """A shared scenario against its base in a few figures (for the dashboard, M8-4): the total
    change of each headline over the horizon and the lowest cash of each. Hypothetical figures;
    computed now, not stored. Drafts are private to their author, so only shared ones qualify."""
    s = services.get(ctx, entity_id, scenario_id)
    if s.status != Scenario.Status.SHARED:
        raise NotFoundError("Choose a shared scenario for this widget.")
    c = compare(ctx, entity_id, scenario_id)
    total = c.effects[-1].changes
    return {
        "scenario_id": str(s.id), "name": s.name, "base_name": c.base.name,
        "base_version": c.base.version, "valid": c.valid, "nature": "HYPOTHETICAL",
        "changes": {k: f"{v:.2f}" for k, v in total.items()},
        "lowest_cash": {k: f"{v.lowest_cash:.2f}" for k, v in c.liquidity.items()},
        "first_negative_month": {k: v.first_negative_month.isoformat()
                                 if v.first_negative_month else None
                                 for k, v in c.liquidity.items()},
        "engine_status": "PENDING_PROFESSIONAL_REVIEW",
    }  # fmt: skip
