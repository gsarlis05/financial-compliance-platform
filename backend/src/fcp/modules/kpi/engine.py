"""The KPI_SET calculation engine (M4-4, doc 10 §5, AC-KP1 to AC-KP3).

One run computes every KPI of a library version for one period (whole months), from posted
actuals pinned to the run's ledger watermark. The run's inputs also hold a snapshot of the account
mapping (account → taxonomy line), so a later mapping change never changes a stored run.

Formulas use these reference functions; a key is a taxonomy section (``REVENUE``,
``CURRENT_ASSETS``, …), a line code (``BS.AR``) or a code prefix (``BS.DEBT`` covers current and
non-current debt). Amounts are in each account's natural direction (debit-normal accounts as
debit minus credit, credit-normal ones the other way round):
- ``flow(key)``: posted movements of the period (closing entries excluded);
- ``prior_flow(key)``: the same months one year earlier;
- ``balance(key)`` / ``opening(key)``: the balance at the end / the start of the period;
  ``EQUITY`` and ``BS.EQUITY`` include the result of years not yet closed;
- ``avg_balance(key)``: the mean of opening and closing;
- ``days()``: calendar days in the period; ``annual_factor()``: 365 ÷ days;
- ``burn_3m()``: the average monthly decrease of cash over the 3 months to the period end;
- ``count_metric(key)`` / ``amount_metric(key)``: an operational metric entered by hand (M4-5):
  the period's last month for point metrics (headcount), the sum of its months for flow metrics
  (units sold). Their values are snapshotted into the run's inputs, and every KPI that uses one
  is marked NON_LEDGER (AC-KP5).

Approved workspace KPIs (M4-5) are snapshotted into the run's inputs too, with their version.

Every value is ACTUAL. Its lineage names the definition version, each reference call, and the
accounts that contributed (AC-KP3: drill-down from a KPI to accounts, and from there to entries).
"""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from fcp.modules.calendar.api import add_months
from fcp.modules.metrics.api import (
    KEY,
    Function,
    Nature,
    NotMeaningful,
    Output,
    Param,
    RunInputs,
    Source,
    compile_expression,
    evaluate,
    formula_value,
    register_engine,
    scalar,
)
from fcp.modules.reporting.api import actuals_monthly, opening_net
from fcp.modules.tenancy.api import WorkspaceContext

KIND = "KPI_SET"
ZERO = Decimal(0)
PLACES = Decimal("1e-20")  # ratios are kept unrounded to 20 places; displays round
MAX_SOURCES = 60
EQUITY_KEYS = ("EQUITY", "BS.EQUITY")


@dataclass(frozen=True)
class Account:
    code: str
    section: str
    credit_normal: bool
    profit_and_loss: bool


@dataclass(frozen=True)
class Data:
    definitions: list[dict[str, str]]
    flows: dict[tuple[str, date], Decimal]  # (account id, month) -> net debit
    balances: dict[date, dict[str, Decimal]]  # cut-off -> account id -> net debit before it


def matches(account: Account, key: str) -> bool:
    return key in (account.section, account.code) or account.code.startswith(f"{key}.")


def period_months(start: date, end: date) -> list[date]:
    months, month = [], start
    while month <= end:
        months.append(month)
        month = add_months(month, 1)
    return months


def cutoffs(start: date, end: date) -> dict[str, date]:
    after = end + timedelta(days=1)
    return {"opening": start, "closing": after, "three_months": add_months(after, -3)}


class _Context:
    """The reference functions for one KPI, recording which accounts contributed."""

    def __init__(
        self,
        start: date,
        end: date,
        data: Data,
        accounts: dict[str, Account],
        operational: dict[str, dict[str, Any]],
    ) -> None:
        self.start, self.end = start, end
        self.data, self.accounts = data, accounts
        self.cut = cutoffs(self.start, self.end)
        self.months = period_months(self.start, self.end)
        self.sources: dict[str, Decimal] = defaultdict(Decimal)
        self.operational = operational
        self.non_ledger = False

    def _natural(self, account_id: str, net_debit: Decimal) -> Decimal:
        return -net_debit if self.accounts[account_id].credit_normal else net_debit

    def _flow(self, key: str, months: list[date], label: str) -> Decimal:
        total = ZERO
        for account_id, account in self.accounts.items():
            if not matches(account, key):
                continue
            amount = sum((self.data.flows.get((account_id, m), ZERO) for m in months), ZERO)
            if amount:
                natural = self._natural(account_id, amount)
                total += natural
                self.sources[f"account:{account_id}:{label}"] += natural
        return total

    def flow(self, key: str) -> Decimal:
        return self._flow(key, self.months, "flow")

    def prior_flow(self, key: str) -> Decimal:
        return self._flow(key, [add_months(m, -12) for m in self.months], "prior_flow")

    def _balance(self, key: str, cut: str) -> Decimal:
        net = self.data.balances.get(self.cut[cut], {})
        total = ZERO
        for account_id, account in self.accounts.items():
            amount = net.get(account_id, ZERO)
            if not amount:
                continue
            if key in EQUITY_KEYS and account.profit_and_loss:
                natural = -amount  # the unclosed result is equity: credit side up
            elif matches(account, key):
                natural = self._natural(account_id, amount)
            else:
                continue
            total += natural
            self.sources[f"account:{account_id}:{cut}"] += natural
        return total

    def balance(self, key: str) -> Decimal:
        return self._balance(key, "closing")

    def opening(self, key: str) -> Decimal:
        return self._balance(key, "opening")

    def avg_balance(self, key: str) -> Decimal:
        return (self.opening(key) + self.balance(key)) / 2

    def days(self) -> Decimal:
        return Decimal((self.end - self.start).days + 1)

    def annual_factor(self) -> Decimal:
        return Decimal(365) / self.days()

    def burn_3m(self) -> Decimal:
        earlier = self._balance("BS.CASH", "three_months")
        return (earlier - self.balance("BS.CASH")) / 3

    def _metric(self, key: str, unit: str) -> Decimal | NotMeaningful:
        metric = self.operational.get(key)
        if metric is None or metric["unit"] != unit:
            return NotMeaningful(f"No {unit} metric {key}")
        self.non_ledger = True
        months = self.months[-1:] if metric["aggregation"] == "LAST" else self.months
        found = [metric["values"].get(m.isoformat()) for m in months]
        if any(v is None for v in found):
            return NotMeaningful(f"{key} has no value for every month of the period")
        total = sum((Decimal(v) for v in found), ZERO)
        for m, v in zip(months, found, strict=True):
            self.sources[f"operational:{key}:{m.isoformat()}"] += Decimal(v)
        return total

    def count_metric(self, key: str) -> Decimal | NotMeaningful:
        return self._metric(key, "count")

    def amount_metric(self, key: str) -> Decimal | NotMeaningful:
        return self._metric(key, "EUR")

    def functions(self) -> list[Function]:
        def keyed(name: str, impl: Callable[[str], Decimal]) -> Function:
            return Function(name, (Param("key", KEY),), scalar("EUR"), impl)

        return [
            keyed("flow", self.flow),
            keyed("prior_flow", self.prior_flow),
            keyed("balance", self.balance),
            keyed("opening", self.opening),
            keyed("avg_balance", self.avg_balance),
            Function("days", (), scalar("days"), self.days),
            Function("annual_factor", (), scalar("ratio"), self.annual_factor),
            Function("burn_3m", (), scalar("EUR"), self.burn_3m),
            Function("count_metric", (Param("key", KEY),), scalar("count"), self.count_metric),
            Function("amount_metric", (Param("key", KEY),), scalar("EUR"), self.amount_metric),
        ]


def reference_functions() -> list[Function]:
    """The functions a KPI formula may use, for checking formulas without data (M4-5)."""
    return _Context(date(2000, 1, 1), date(2000, 1, 31), Data([], {}, {}), {}, {}).functions()


@dataclass(frozen=True)
class Evaluated:
    """A formula evaluated on given data, with the accounts and reference calls behind it."""

    value: Decimal | None
    nm_reason: str
    unit: str
    sources: dict[str, Decimal]
    calls: tuple[str, ...]
    non_ledger: bool


def evaluate_formula(  # noqa: PLR0913 (the period and the data it reads)
    formula: str,
    *,
    date_from: date,
    date_to: date,
    accounts: dict[str, Account],
    flows: dict[tuple[str, date], Decimal],
    balances: dict[date, dict[str, Decimal]],
    operational: dict[str, dict[str, Any]] | None = None,
) -> Evaluated:
    """Evaluate a KPI formula on data the caller supplies (goals, M4-6): ``flows`` are net debits
    per (account id, month) and ``balances`` the net debit per account before each cut-off date
    (``cutoffs``). An account id may be a pseudo-account (e.g. a budget line) as long as
    ``accounts`` describes it. Raises ``ExpressionError`` for a formula that does not compile."""
    context = _Context(date_from, date_to, Data([], flows, balances), accounts, operational or {})
    evaluation = evaluate(compile_expression(formula, functions=context.functions()))
    result = evaluation.value
    if isinstance(result, bool):
        raise ValueError("a true/false formula has no value")
    meaningful = not isinstance(result, NotMeaningful)
    return Evaluated(
        result if not isinstance(result, NotMeaningful) else None,
        "" if meaningful else getattr(result, "reason", ""),
        evaluation.unit,
        dict(context.sources),
        evaluation.calls,
        context.non_ledger,
    )


class KpiSetEngine:
    kind = KIND
    version = "1"

    def load(self, ctx: WorkspaceContext, inputs: RunInputs) -> Data:
        from .models import KpiDefinition  # noqa: PLC0415 (reference data, read at run time)

        refs = inputs.refs
        start, end = date.fromisoformat(refs["date_from"]), date.fromisoformat(refs["date_to"])
        definitions = [
            {"id": d.id, "key": d.key, "formula": d.formula, "nm_reason": d.nm_reason}
            for d in KpiDefinition.objects.filter(library=refs["library"]).order_by("order")
        ] + [
            {"id": c["id"], "key": c["key"], "formula": c["formula"], "nm_reason": ""}
            for c in refs.get("custom", [])
        ]
        facts = actuals_monthly(
            ctx,
            inputs.legal_entity_id,
            date_from=add_months(start, -12),
            date_to=end,
            watermark=inputs.actuals_watermark,
        ).facts
        flows = {(str(f.account_id), f.period): f.net_debit for f in facts}
        balances = {}
        for cut in cutoffs(start, end).values():
            _, net = opening_net(
                ctx, inputs.legal_entity_id, before=cut, watermark=inputs.actuals_watermark
            )
            balances[cut] = {str(a): v for a, v in net.items()}
        return Data(definitions, flows, balances)

    def compute(self, inputs: RunInputs, data: Data) -> Output:
        accounts = {a: Account(*row) for a, row in inputs.refs["accounts"].items()}
        start, end = (
            date.fromisoformat(inputs.refs["date_from"]),
            date.fromisoformat(inputs.refs["date_to"]),
        )
        values = []
        for definition in data.definitions:
            context = _Context(start, end, data, accounts, inputs.refs.get("operational", {}))
            compiled = compile_expression(definition["formula"], functions=context.functions())
            evaluation = evaluate(compiled)
            sources = sorted(context.sources.items())[:MAX_SOURCES]
            value = formula_value(
                f"kpi.{definition['key']}",
                start,
                Nature.ACTUAL,
                definition["id"],
                evaluation,
                period_end=end,
                granularity="POINT",
                lineage=tuple(
                    Source(
                        "MANUAL" if ref.startswith("operational:") else "ACTUAL",
                        ref,
                        amount.quantize(PLACES),
                    )
                    for ref, amount in sources
                ),
                dimensions=("NON_LEDGER",) if context.non_ledger else (),
            )
            if value.value is not None:
                value = replace(value, value=value.value.quantize(PLACES))
            elif definition["nm_reason"]:
                value = replace(value, nm_reason=definition["nm_reason"])
            values.append(value)
        return Output(tuple(values), {"definitions_found": bool(data.definitions)})


def account_snapshot(rows: list[tuple[UUID, str, str, bool, bool]]) -> dict[str, list[Any]]:
    """The mapping as stored in a run's inputs: account id -> [code, section, credit normal,
    profit and loss]."""
    return {str(a): [code, section, credit, pl] for a, code, section, credit, pl in rows}


ENGINE = register_engine(KpiSetEngine())
