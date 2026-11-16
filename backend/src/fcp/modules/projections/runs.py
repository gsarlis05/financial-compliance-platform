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
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.assets.api import depreciation_plan
from fcp.modules.calendar.api import add_months
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
from .assumptions import READ, RUN, approved_loans, approved_values, horizon
from .debt import LoanTerms, project_loan
from .models import AssumptionSet

KIND = "PROJECTION"
ZERO_AMOUNT = Decimal("0.00")
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


Drivers = dict[tuple[str, str], dict[date, Decimal]]


def same_month_of_the_set(drivers: Drivers, months: list[date]) -> Drivers:
    """Driver values for ``months``: the set's own where it has them; elsewhere (a rolling
    forecast reaching past the set) the same calendar month of the set, the nearest year first,
    earlier before later. No growth is assumed."""
    out: dict[tuple[str, str], dict[date, Decimal]] = {}
    for key, series in drivers.items():
        filled: dict[date, Decimal] = {}
        for month in months:
            for years in (0, *(sign * n for n in range(1, 11) for sign in (-1, 1))):
                found = series.get(add_months(month, 12 * years))
                if found is not None:
                    filled[month] = found
                    break
        out[key] = filled
    return out


def _pinned(ctx: WorkspaceContext, entity_id: UUID, made: AssumptionSet,
            cutover: date | None = None, count: int | None = None) -> dict[str, Any]:  # fmt: skip
    cutover = cutover or made.cutover
    months = horizon(cutover, count or made.months)
    plan = depreciation_plan(ctx, entity_id, months)
    return {
        "assumption_set_id": str(made.id),
        "assumption_set_version": made.version,
        "currency": get_entity(ctx, entity_id, RUN).functional_currency,
        "cutover": cutover.isoformat(),
        "months": [m.isoformat() for m in months],
        "mapping": _mapping(entity_id),
        "register_depreciation": {d.month.isoformat(): str(d.amount) for d in plan if d.amount},
        "fiscal_year_starts": [m.isoformat() for m in months
                               if fiscal_year_start(ctx, entity_id, m) == m],
    }  # fmt: skip


@dataclass(frozen=True)
class Loaded:
    inp: engine.EngineInput


def _series(drivers: Drivers, key: str, code: str) -> dict[date, Decimal]:
    return dict(drivers.get((key, code), {}))


def loan_terms(made: AssumptionSet, drivers: Drivers, months: list[date]) -> tuple[LoanTerms, ...]:
    """The set's loans as engine terms for ``months``. A run starting after the set's first month
    (a rolling forecast) rolls each loan forward through the months in between first."""
    set_months = horizon(made.cutover, made.months)
    before = [m for m in set_months if months and m < months[0]]
    out = []
    for loan in approved_loans(made):
        terms = LoanTerms(
            code=loan.code, structure=loan.structure, term_months=loan.term_months,
            annual_rate=loan.annual_rate, opening=loan.opening_balance, amount=loan.amount,
            drawdown_month=loan.drawdown_month,
            interest_only_months=loan.interest_only_months,
            rate_path=_series(drivers, "loan_rate", loan.code),
            prepayments=_series(drivers, "loan_prepayment", loan.code),
            drawdowns=_series(drivers, "loan_drawdown", loan.code),
        )  # fmt: skip
        rolled = _rolled_forward(terms, before) if before else terms
        if rolled is not None:
            out.append(rolled)
    return tuple(out)


def _rolled_forward(terms: LoanTerms, before: list[date]) -> LoanTerms | None:
    """The loan as it stands after ``before`` (months already past), as an existing loan."""
    rows = project_loan(terms, before)
    balance = rows[-1].closing
    if terms.drawdown_month is not None and terms.drawdown_month > before[-1]:
        return terms  # not drawn yet
    start = add_months(terms.drawdown_month, 1) if terms.drawdown_month else before[0]
    elapsed = max((add_months(before[-1], 1).year - start.year) * 12
                  + add_months(before[-1], 1).month - start.month, 0)  # fmt: skip
    left = terms.term_months - elapsed
    if balance <= 0 or left < 1:
        return None
    return replace(terms, opening=balance, amount=ZERO_AMOUNT, drawdown_month=None,
                   term_months=left,
                   interest_only_months=max(terms.interest_only_months - elapsed, 0),
                   annual_rate=rows[-1].rate)  # fmt: skip


def check_loans(opening: dict[str, Decimal], loans: tuple[LoanTerms, ...]) -> None:
    """Existing loans cannot add up to more than the debt in the books at the cut-over."""
    books = opening.get("BS.DEBT.CURRENT", Decimal(0)) + opening.get("BS.DEBT.NONCURRENT",
                                                                      Decimal(0))  # fmt: skip
    loans_total = sum((t.opening for t in loans if t.drawdown_month is None), Decimal(0))
    if loans_total > books:
        message = (f"The set's existing loans ({loans_total:.2f}) are more than the debt in the "
                   f"books at the cut-over ({books:.2f}). Check the balances, or the mapping of "
                   "the loan accounts.")  # fmt: skip
        raise ValidationFailedError(message, field_errors={"loans": [message]})


class ProjectionEngine:
    kind = KIND
    version = "2"  # M6F-4: loans

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> Loaded:
        refs = inputs.refs
        cutover = date.fromisoformat(refs["cutover"])
        _, net = opening_net(ctx, inputs.legal_entity_id, before=cutover + timedelta(days=1),
                             watermark=inputs.actuals_watermark)  # fmt: skip
        made, drivers = approved_values(ctx, inputs.legal_entity_id,
                                        UUID(refs["assumption_set_id"]))  # fmt: skip
        months = [date.fromisoformat(m) for m in refs["months"]]
        return Loaded(engine.EngineInput(
            set_id=str(made.id),
            cutover=cutover,
            months=months,
            opening=opening_balance_sheet(net, refs["mapping"]),
            drivers=same_month_of_the_set(drivers, months),
            register_depreciation={date.fromisoformat(m): Decimal(v)
                                   for m, v in refs["register_depreciation"].items()},
            fiscal_year_starts={date.fromisoformat(m) for m in refs["fiscal_year_starts"]},
            currency=refs.get("currency", "EUR"),  # runs made before M6F-1 are in EUR
            loans=loan_terms(made, drivers, months),
        ))  # fmt: skip

    def compute(self, inputs: RunInputs, data: Loaded) -> Output:
        check_loans(data.inp.opening, data.inp.loans)
        return engine.output(data.inp)[1]


ENGINE = register_engine(ProjectionEngine())


def run_projection(  # noqa: PLR0913 (keyword options for rolling forecasts)
    ctx: WorkspaceContext,
    entity_id: UUID,
    set_id: UUID,
    *,
    cutover: date | None = None,
    months: int | None = None,
    rolling: UUID | None = None,
    trigger: str = CalcRun.Trigger.USER,
    supersedes: CalcRun | None = None,
) -> CalcRun:
    """Project the three statements from an approved assumption set (a new run every time). A
    rolling forecast (M6-4) chooses its own cut-over and horizon."""
    entity = get_entity(ctx, entity_id, RUN).id
    made = AssumptionSet.objects.filter(legal_entity_id=entity, id=set_id).first()
    if made is None:
        raise NotFoundError("Assumption set not found.")
    if made.status == AssumptionSet.Status.DRAFT:
        raise ConflictError("Approve the assumption set before projecting with it.")
    refs = _pinned(ctx, entity, made, cutover, months)
    if rolling is not None:
        refs["rolling_forecast_id"] = str(rolling)
    as_of = date.fromisoformat(refs["cutover"])
    # Refuse an unmappable opening before recording a run (the run's own read is pinned).
    _, net = opening_net(ctx, entity, before=as_of + timedelta(days=1))
    start = opening_balance_sheet(net, refs["mapping"])
    _, drivers = approved_values(ctx, entity, made.id)
    check_loans(start, loan_terms(made, drivers, [date.fromisoformat(m) for m in refs["months"]]))
    return execute(ctx, entity, KIND, as_of=as_of, refs=refs, trigger=trigger,
                   supersedes=supersedes)  # fmt: skip


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
    ids: dict[str, list[UUID | None]]  # series key -> the stored result per column (explain)


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
    ids: dict[str, list[UUID | None]] = {}
    for r in found:
        at = index[(r.period_start, r.period_end, r.nature)]
        rows.setdefault(r.series_key, [None] * len(keys))[at] = r.value
        ids.setdefault(r.series_key, [None] * len(keys))[at] = r.id
    failures = sorted(k for k, v in run.invariant_results.items() if not v and "@" in k)
    return Statements(run, [Column(*k) for k in keys], rows, failures, ids)
