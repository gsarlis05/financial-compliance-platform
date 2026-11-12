"""Projections as calculation runs (M6-3, doc 10 P4): kind ``PROJECTION``.

``prepare`` pins in the run's inputs everything the projection reads besides the ledger and the
approved assumption set (which never changes): the account mapping, the depreciation of the
registered assets by month, and the months that start a fiscal year. ``load`` reads the opening
balance sheet from the ledger at the run's watermark (through ``reporting``) and the set's values;
``compute`` is the pure engine. The same inputs and engine version give the same hash (AC-PJ4).

Opening balance sheet (AC-PJ2): every account with a balance at the cut-over, by its taxonomy line,
in the line's natural direction (assets debit, liabilities and equity credit). Income and expense
accounts not yet closed into retained earnings are added to retained earnings. An account with a
balance that is not mapped, or is mapped to a line the projection does not hold, is refused, so the
opening always balances when the books do.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.assets.api import depreciation_plan
from fcp.modules.metrics.api import (
    CalcRun,
    Output,
    RunInputs,
    calc_results,
    current_mapping,
    execute,
    get_calc_run,
    list_calc_runs,
    register_engine,
)
from fcp.modules.reporting.api import fiscal_year_start, opening_net
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import engine
from .assumptions import READ, RUN, approved_values, horizon
from .models import AssumptionSet

KIND = "PROJECTION"
RETAINED = "BS.EQUITY.RETAINED"


def opening_balance_sheet(net: dict[UUID, Decimal],
                          mapping: dict[str, str]) -> dict[str, Decimal]:  # fmt: skip
    """Balances by line in their natural direction; ``mapping`` is account id -> line code, or
    "PL" for an income or expense account."""
    opening: dict[str, Decimal] = defaultdict(Decimal)
    refused = []
    for account_id, amount in sorted(net.items(), key=lambda item: str(item[0])):
        if amount == 0:
            continue
        code = mapping.get(str(account_id))
        if code == "PL":
            opening[RETAINED] -= amount
        elif code in engine.ASSETS:
            opening[code] += amount
        elif code in engine.LIABILITIES or code in engine.EQUITY:
            opening[code] -= amount
        else:
            refused.append(str(account_id))
    if refused:
        raise ValidationFailedError(
            f"{len(refused)} account(s) with a balance at the cut-over are not mapped to a "
            "balance-sheet line the projection holds. Map them, then run the projection.",
            field_errors={"mapping": refused[:20]},
        )
    return dict(opening)


def _mapping(entity_id: UUID) -> dict[str, str]:
    return {str(account_id): ("PL" if line.statement == "PL" else line.code)
            for account_id, line in current_mapping(entity_id).items()}  # fmt: skip


def _pinned(ctx: WorkspaceContext, entity_id: UUID, made: AssumptionSet) -> dict[str, Any]:
    months = horizon(made.cutover, made.months)
    plan = depreciation_plan(ctx, entity_id, months)
    return {
        "assumption_set_id": str(made.id),
        "assumption_set_version": made.version,
        "cutover": made.cutover.isoformat(),
        "months": [m.isoformat() for m in months],
        "mapping": _mapping(entity_id),
        "register_depreciation": {d.month.isoformat(): str(d.amount) for d in plan if d.amount},
        "fiscal_year_starts": [m.isoformat() for m in months
                               if fiscal_year_start(ctx, entity_id, m) == m],
    }  # fmt: skip


@dataclass(frozen=True)
class Loaded:
    inp: engine.EngineInput


class ProjectionEngine:
    kind = KIND
    version = "1"

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> Loaded:
        refs = inputs.refs
        cutover = date.fromisoformat(refs["cutover"])
        _, net = opening_net(ctx, inputs.legal_entity_id, before=cutover + timedelta(days=1),
                             watermark=inputs.actuals_watermark)  # fmt: skip
        made, drivers = approved_values(ctx, inputs.legal_entity_id,
                                        UUID(refs["assumption_set_id"]))  # fmt: skip
        return Loaded(engine.EngineInput(
            set_id=str(made.id),
            cutover=cutover,
            months=[date.fromisoformat(m) for m in refs["months"]],
            opening=opening_balance_sheet(net, refs["mapping"]),
            drivers=drivers,
            register_depreciation={date.fromisoformat(m): Decimal(v)
                                   for m, v in refs["register_depreciation"].items()},
            fiscal_year_starts={date.fromisoformat(m) for m in refs["fiscal_year_starts"]},
        ))  # fmt: skip

    def compute(self, inputs: RunInputs, data: Loaded) -> Output:
        return engine.output(data.inp)[1]


ENGINE = register_engine(ProjectionEngine())


def run_projection(ctx: WorkspaceContext, entity_id: UUID, set_id: UUID) -> CalcRun:
    """Project the three statements from an approved assumption set (a new run every time)."""
    entity = get_entity(ctx, entity_id, RUN).id
    made = AssumptionSet.objects.filter(legal_entity_id=entity, id=set_id).first()
    if made is None:
        raise NotFoundError("Assumption set not found.")
    if made.status == AssumptionSet.Status.DRAFT:
        raise ConflictError("Approve the assumption set before projecting with it.")
    refs = _pinned(ctx, entity, made)
    # Refuse an unmappable opening before recording a run (the run's own read is pinned).
    _, net = opening_net(ctx, entity, before=made.cutover + timedelta(days=1))
    opening_balance_sheet(net, refs["mapping"])
    return execute(ctx, entity, KIND, as_of=made.cutover, refs=refs)


def projections(ctx: WorkspaceContext, entity_id: UUID) -> list[CalcRun]:
    return list_calc_runs(ctx, entity_id, KIND, limit=100)


@dataclass(frozen=True)
class Column:
    start: date
    end: date
    nature: str


@dataclass(frozen=True)
class Statements:
    run: CalcRun
    columns: list[Column]
    rows: dict[str, list[Decimal | None]]  # series key -> one value per column
    failures: list[str]  # "<invariant>@<where>"


def statements(ctx: WorkspaceContext, entity_id: UUID, run_id: UUID,
               granularity: str = "MONTH") -> Statements:  # fmt: skip
    """A run's statements as columns (the opening balance sheet first, as ACTUAL) and rows."""
    get_entity(ctx, entity_id, READ)
    run = get_calc_run(ctx, entity_id, run_id)
    if run.kind != KIND:
        raise NotFoundError("Projection not found.")
    found = [r for r in calc_results(run)
             if r.granularity == granularity or r.nature == "ACTUAL"]  # fmt: skip
    keys = sorted({(r.period_start, r.period_end, r.nature) for r in found},
                  key=lambda k: (k[0], k[2] != "ACTUAL"))  # fmt: skip
    index = {k: i for i, k in enumerate(keys)}
    rows: dict[str, list[Decimal | None]] = {}
    for r in found:
        rows.setdefault(r.series_key, [None] * len(keys))[
            index[(r.period_start, r.period_end, r.nature)]] = r.value  # fmt: skip
    failures = sorted(k for k, v in run.invariant_results.items() if not v and "@" in k)
    return Statements(run, [Column(*k) for k in keys], rows, failures)
