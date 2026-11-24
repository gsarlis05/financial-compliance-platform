"""KPIs on projected and scenario figures (M7-6, brief 21 §3): the KPI library's definitions,
unchanged, evaluated on a projection's months instead of the posted books.

Each projection line becomes a pseudo-account with its taxonomy code and section (``PL.REV.SALES``
is revenue line ``REV.SALES``; ``BS.AR`` is trade receivables), so every formula reads the same
keys as on actuals: flows are the projected monthly amounts, balances the projected month-end
balance sheet (the actual one at the cut-over). Values are FORECAST for an approved assumption set
and HYPOTHETICAL for a scenario (shown next to its base). A KPI that needs months the projection
does not hold (the same period a year earlier, the 12 months before the period's end, three months
of cash before it) is "not meaningful" with that reason, never computed on missing data.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from fcp.core.errors import ValidationFailedError
from fcp.modules.calendar.api import add_months, month_end
from fcp.modules.kpi.api import DEFAULT_LIBRARY, Account, KpiDefinition, cutoffs, evaluate_formula
from fcp.modules.projections.api import OPEX_LINES, EngineInput, Projection, load_input, project
from fcp.modules.tenancy.api import WorkspaceContext

from .sensitivity_runs import base as analysis_base

ZERO = Decimal(0)

# Projection line -> (taxonomy code, section, credit normal); income statement lines.
PL_LINES: dict[str, tuple[str, str, bool]] = {
    "PL.REV.SALES": ("REV.SALES", "REVENUE", True),
    "PL.REV.SERVICES": ("REV.SERVICES", "REVENUE", True),
    "PL.REV.OTHER": ("REV.OTHER", "OTHER_INCOME", True),
    "PL.COGS": ("COGS", "COST_OF_SALES", False),
    **{f"PL.{x}": (x, "OPERATING_EXPENSES", False) for x in OPEX_LINES},
    "PL.DA": ("DA.DEPRECIATION", "DEPRECIATION_AMORTISATION", False),
    "PL.INTEREST": ("INT.EXPENSE", "FINANCE", False),
    "PL.TAX": ("TAX.INCOME", "TAX", False),
}
_ASSETS = {"BS.PPE.GROSS": "NON_CURRENT_ASSETS", "BS.PPE.ACCDEP": "NON_CURRENT_ASSETS",
           "BS.INTANGIBLES": "NON_CURRENT_ASSETS", "BS.INVESTMENTS": "NON_CURRENT_ASSETS",
           "BS.INVENTORY": "CURRENT_ASSETS", "BS.AR": "CURRENT_ASSETS",
           "BS.OTHER_REC": "CURRENT_ASSETS", "BS.TAX_REC": "CURRENT_ASSETS",
           "BS.CASH": "CURRENT_ASSETS"}  # fmt: skip
_CLAIMS = {"BS.DEBT.NONCURRENT": ("BS.DEBT.NONCURRENT", "NON_CURRENT_LIABILITIES"),
           "BS.DEBT.CURRENT": ("BS.DEBT.CURRENT", "CURRENT_LIABILITIES"),
           "BS.AP": ("BS.AP", "CURRENT_LIABILITIES"),
           "BS.OTHER_PAY": ("BS.OTHER_PAY", "CURRENT_LIABILITIES"),
           "BS.TAX_PAY": ("BS.TAX_PAY", "CURRENT_LIABILITIES"),
           "BS.INCOME_TAX": ("BS.TAX_PAY.INCOME", "CURRENT_LIABILITIES"),
           "BS.DEFERRED_TAX": ("BS.DEFERRED_TAX", "NON_CURRENT_LIABILITIES"),
           "BS.EQUITY.SHARE_CAPITAL": ("BS.EQUITY.SHARE_CAPITAL", "EQUITY"),
           "BS.EQUITY.SHARE_PREMIUM": ("BS.EQUITY.SHARE_PREMIUM", "EQUITY"),
           "BS.EQUITY.RETAINED": ("BS.EQUITY.RETAINED", "EQUITY")}  # fmt: skip


def accounts() -> dict[str, Account]:
    out = {
        k: Account(code, section, credit, True) for k, (code, section, credit) in PL_LINES.items()
    }
    out.update({k: Account(k, section, False, False) for k, section in _ASSETS.items()})
    out.update({k: Account(code, section, True, False) for k, (code, section) in _CLAIMS.items()})
    return out


def _net_debit(account: Account, natural: Decimal) -> Decimal:
    return -natural if account.credit_normal else natural


@dataclass(frozen=True)
class Books:
    """A projection as KPI data: flows by (line, month) and balances before each month start."""

    months: list[date]
    flows: dict[tuple[str, date], Decimal]
    balances: dict[date, dict[str, Decimal]]


def books(p: Projection) -> Books:
    acc = accounts()
    flows = {(k, m.month): _net_debit(acc[k], m.pl[k]) for m in p.months for k in PL_LINES}

    def sheet(bs: dict[str, Decimal]) -> dict[str, Decimal]:
        return {k: _net_debit(a, bs.get(k, ZERO)) for k, a in acc.items() if k.startswith("BS.")}

    balances = {p.months[0].month: sheet(p.opening)}
    for m in p.months:
        balances[add_months(m.month, 1)] = sheet(m.bs)
    return Books([m.month for m in p.months], flows, balances)


@dataclass(frozen=True)
class Kpi:
    key: str
    name: str
    display: str
    value: Decimal | None
    nm_reason: str


def _missing(formula: str, start: date, end: date, held: set[date]) -> str:
    """Why a definition cannot be evaluated on the projection's months, or ""."""
    last = date(end.year, end.month, 1)
    period = {m for m in held if start <= m <= last}
    if "prior_flow(" in formula and any(add_months(m, -12) not in held for m in period):
        return "The projection does not hold the same period a year earlier"
    if "ltm_flow(" in formula and any(add_months(last, -k) not in held for k in range(12)):
        return "The projection does not hold the 12 months to the end of the period"
    if "burn_3m(" in formula and cutoffs(start, end)["three_months"] < min(held):
        return "The projection does not hold three months of cash before the end of the period"
    return ""


def evaluate(b: Books, start: date, end: date) -> list[Kpi]:
    acc = accounts()
    held = set(b.months)
    out = []
    for d in KpiDefinition.objects.filter(library=DEFAULT_LIBRARY).order_by("order"):
        reason = _missing(d.formula, start, end, held)
        if reason:
            out.append(Kpi(d.key, d.name, d.display, None, reason))
            continue
        e = evaluate_formula(d.formula, date_from=start, date_to=end, accounts=acc,
                             flows=b.flows, balances=b.balances)  # fmt: skip
        out.append(Kpi(d.key, d.name, d.display, e.value,
                       "" if e.value is not None else d.nm_reason or e.nm_reason))  # fmt: skip
    return out


@dataclass(frozen=True)
class ProjectedKpis:
    label: str
    nature: str
    year: int
    start: date
    end: date
    values: list[Kpi]
    base: list[Kpi] | None  # a scenario's base, for comparison


def _period(inp: EngineInput, year: int) -> tuple[date, date]:
    months = [m for m in inp.months if m.year == year]
    if not months:
        choices = ", ".join(sorted({str(m.year) for m in inp.months}))
        message = f"year: choose a year of the horizon ({choices})."
        raise ValidationFailedError(message, field_errors={"year": [message]})
    return months[0], month_end(months[-1])


def projected_kpis(ctx: WorkspaceContext, entity_id: UUID, *, set_id: UUID | None,
                   scenario_id: UUID | None, year: int) -> ProjectedKpis:  # fmt: skip
    """The KPI library on a projected year: an approved set (FORECAST), or a shared scenario
    (HYPOTHETICAL) next to its base."""
    b = analysis_base(ctx, entity_id, set_id=set_id, scenario_id=scenario_id)
    start, end = _period(b.inp, year)
    values = evaluate(books(project(b.inp)[0]), start, end)
    if scenario_id is None:
        return ProjectedKpis(b.label, "FORECAST", year, start, end, values, None)
    plain = load_input(ctx, entity_id, b.refs["scenario"]["base"], b.watermark)
    base_values = evaluate(books(project(plain)[0]), start, end)
    return ProjectedKpis(b.label, "HYPOTHETICAL", year, start, end, values, base_values)
