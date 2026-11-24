"""The three-statement projection engine (M6-3, doc 10 §4): a pure function, no database.

Order of calculation per month (doc 10 §4.1):
1. Income statement to EBIT: revenue per line; cost of sales from the gross margin on sales and
   services; operating costs per line; depreciation of the registered assets and of new capital
   expenditure (straight-line over its life, a full month from ``capex_start`` months after it is
   spent; by default the month after).
2. Interest on the **opening** debt and credit facility of the month (no circularity).
3. Corporate income tax (M6F-5, ``tax.py``): current tax on taxable profit year to date under the
   tax rule set of the year, with losses carried forward; deferred tax on temporary differences;
   net income.
4. Working capital from days: receivables = revenue x DSO / days in the month; inventory and
   payables = cost of sales x DIO (or DPO) / days in the month. Fixed assets roll forward
   (+ capex, - depreciation).
5. Debt rolls forward: + new borrowing, - repayments (capped at what is owed; current debt first).
6. Equity rolls forward: + net income - dividends + new share capital.
7. Cash flow statement (indirect method): the tax expense is added back and the tax actually paid
   (provisional instalments, final payments) is shown on its own line.
8. Closing cash = opening cash + net cash flow; then the credit facility: drawn up to its limit
   when cash would fall below the minimum, repaid when cash is above it.
9. Balance sheet from the roll-forwards. Lines the drivers do not cover (intangibles,
   investments, other receivables and payables, tax receivable, share premium) are held.

Rounding (doc 10 §2.4): each statement line is rounded to cents once per month; totals, cash and
retained earnings are sums of rounded lines, so the statements tie to the cent with no plug.

Every run checks eight invariants: the six of doc 10 §4.2, debt (M6F-4) and tax (M6F-5); the
framework marks a run that fails one INVALID, and an invalid run cannot be published. The
validation package (docs/validation) compares the engine with an independent model.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from fcp.modules.assets.api import (
    DECLINING_BALANCE,
    FULL_MONTH,
    STRAIGHT_LINE,
    AllowanceRate,
    AssetTerms,
    allowance_schedule,
    schedule,
)
from fcp.modules.calendar.api import add_months, month_end
from fcp.modules.metrics.api import Nature, Output, Source, Value

from .debt import LoanMonth, LoanTerms, opening_current, project_loan
from .drivers import DEFAULTS, OPEX_LINES, REVENUE_LINES
from .tax import TaxBook, TaxInputs, TaxMonth

# The engine is not production-ready until the validation package passes and a qualified
# independent professional has signed it (owner decision D9, 2026-11-15; brief 20 §5). Changed
# only when that sign-off is recorded.
VALIDATION_STATUS = "PENDING_PROFESSIONAL_REVIEW"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED, TWELVE = Decimal(100), Decimal(12)
ASSETS = ("BS.PPE.GROSS", "BS.PPE.ACCDEP", "BS.INTANGIBLES", "BS.INVESTMENTS", "BS.INVENTORY",
          "BS.AR", "BS.OTHER_REC", "BS.TAX_REC", "BS.CASH")  # fmt: skip
# BS.TAX_PAY and BS.TAX_REC hold VAT and other taxes (held); income tax has its own lines (M6F-5).
LIABILITIES = ("BS.DEBT.NONCURRENT", "BS.DEBT.CURRENT", "BS.AP", "BS.OTHER_PAY", "BS.TAX_PAY",
               "BS.INCOME_TAX", "BS.DEFERRED_TAX")  # fmt: skip
EQUITY = ("BS.EQUITY.SHARE_CAPITAL", "BS.EQUITY.SHARE_PREMIUM", "BS.EQUITY.RETAINED")
BS_LINES = ASSETS + LIABILITIES + EQUITY
INVARIANTS = (
    "balance_sheet_balances",
    "cash_ties",
    "retained_earnings_roll",
    "opening_equals_previous_closing",
    "roll_forwards_tie",
    "aggregation_consistent",
    "debt_reconciles",  # M6F-4: each loan's roll-forward, interest and the debt lines
    "tax_reconciles",  # M6F-5: income tax, deferred tax and the loss pool roll forward
)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT)


@dataclass(frozen=True)
class ExtraCapex:
    """Capital expenditure with its own useful life (M7-2: a scenario's investment); it starts and
    gets allowances like the set's capex of its month, straight-line."""

    month: date
    amount: Decimal
    life_months: int


@dataclass(frozen=True)
class EngineInput:
    """Everything a projection depends on, as plain data (pinned in the run's inputs)."""

    set_id: str
    cutover: date
    months: list[date]
    opening: dict[str, Decimal]  # balance-sheet line -> amount in its natural direction
    drivers: dict[tuple[str, str], dict[date, Decimal]]
    register_depreciation: dict[date, Decimal]
    fiscal_year_starts: set[date] = field(default_factory=set)  # months that start a year
    currency: str = "EUR"  # the entity's functional currency (ISO 4217)
    loans: tuple[LoanTerms, ...] = ()  # M6F-4: loans of the assumption set
    tax: TaxInputs | None = None  # M6F-5: tax rules and positions; None: no income tax
    # M7-2 (scenarios only; empty for every projection, so its results are unchanged): extra
    # capex, and one-off payments that settle held liabilities (line -> amount, by month).
    extra_capex: tuple[ExtraCapex, ...] = ()
    settlements: dict[date, dict[str, Decimal]] = field(default_factory=dict)


@dataclass
class Month:
    month: date
    pl: dict[str, Decimal]
    bs: dict[str, Decimal]
    cf: dict[str, Decimal]
    loans: dict[str, LoanMonth] = field(default_factory=dict)  # M6F-4, by loan code
    other_debt: dict[str, Decimal] = field(default_factory=dict)  # M6F-4
    tax: TaxMonth | None = None  # M6F-5


@dataclass
class Projection:
    opening: dict[str, Decimal]
    months: list[Month]
    invariants: dict[str, bool]
    notes: list[str]


def _d(inp: EngineInput, key: str, month: date, line: str = "") -> Decimal:
    return inp.drivers.get((key, line), {}).get(month, Decimal(0))


def _dd(inp: EngineInput, key: str, month: date) -> Decimal:
    """A driver's value, or its default when the set has no row for it (sets made before the
    driver existed)."""
    series = inp.drivers.get((key, ""))
    if series is None or month not in series:
        return Decimal(DEFAULTS.get(key, 0))
    return series[month]


@dataclass(frozen=True)
class NewCapex:
    depreciation: dict[date, Decimal]
    qualifying: dict[date, Decimal]  # of capex with a capital allowance rate
    allowances: dict[int, Decimal]  # by tax year


def _new_capex(inp: EngineInput) -> NewCapex:
    """New capex is depreciated from ``capex_start`` months after the month it is spent (a full
    first month), straight-line, or declining balance at ``capex_db_rate`` (M6F-3, #148). Its tax
    capital allowances run by tax year from the year of spend at ``capex_allowance_rate``, a full
    year's allowance in that year (M6F-5)."""
    found: dict[date, Decimal] = defaultdict(lambda: ZERO)
    qualifying: dict[date, Decimal] = defaultdict(lambda: ZERO)
    allowances: dict[int, Decimal] = defaultdict(lambda: ZERO)
    last_year = inp.months[-1].year if inp.months else 0
    spends = [(m, cents(_d(inp, "capex", m)), max(int(_dd(inp, "capex_life", m)), 1),
               _dd(inp, "capex_db_rate", m) / HUNDRED) for m in inp.months]  # fmt: skip
    spends += [(x.month, cents(x.amount), max(x.life_months, 1), Decimal(0))
               for x in inp.extra_capex]  # fmt: skip
    for month, spent, life, db_rate in spends:
        if spent <= 0:
            continue
        offset = max(int(_dd(inp, "capex_start", month)), 0)
        terms = AssetTerms(
            month, spent, Decimal(0), life,
            method=DECLINING_BALANCE if db_rate > 0 else STRAIGHT_LINE,
            annual_rate=db_rate if db_rate > 0 else None,
            available_on=add_months(month, offset), commencement=FULL_MONTH,
        )  # fmt: skip
        allowance_rate = _dd(inp, "capex_allowance_rate", month) / HUNDRED
        for row in schedule(terms):
            found[row.month] += row.depreciation
            if allowance_rate > 0:
                qualifying[row.month] += row.depreciation
        if allowance_rate > 0:
            rates = [AllowanceRate(date(1900, 1, 1), min(allowance_rate, Decimal(1)))]
            for a in allowance_schedule(spent, month, rates, until_year=last_year):
                allowances[a.tax_year] += a.allowance
    return NewCapex(dict(found), dict(qualifying), dict(allowances))


def _income(inp: EngineInput, month: date, depreciation: Decimal,
            interest: Decimal) -> dict[str, Decimal]:  # fmt: skip
    pl: dict[str, Decimal] = {}
    for line in REVENUE_LINES:
        pl[f"PL.{line}"] = cents(_d(inp, "revenue", month, line))
    revenue = sum((pl[f"PL.{line}"] for line in REVENUE_LINES), ZERO)
    sales = pl["PL.REV.SALES"] + pl["PL.REV.SERVICES"]
    pl["PL.REVENUE"] = revenue
    pl["PL.COGS"] = cents(sales * (HUNDRED - _d(inp, "gross_margin", month)) / HUNDRED)
    pl["PL.GROSS_PROFIT"] = revenue - pl["PL.COGS"]
    for line in OPEX_LINES:
        pl[f"PL.{line}"] = cents(_d(inp, "opex", month, line))
    pl["PL.OPEX"] = sum((pl[f"PL.{line}"] for line in OPEX_LINES), ZERO)
    pl["PL.EBITDA"] = pl["PL.GROSS_PROFIT"] - pl["PL.OPEX"]
    pl["PL.DA"] = depreciation
    pl["PL.EBIT"] = pl["PL.EBITDA"] - depreciation
    pl["PL.INTEREST"] = interest
    pl["PL.PBT"] = pl["PL.EBIT"] - pl["PL.INTEREST"]
    return pl


def project(inp: EngineInput) -> Projection:  # noqa: PLR0915 (one month, in doc 10's order)
    """Project the three statements month by month (see the module text)."""
    opening = {line: cents(inp.opening.get(line, ZERO)) for line in BS_LINES}
    capex_plan = _new_capex(inp)
    new_dep = capex_plan.depreciation
    book = (TaxBook(inp.tax, inp.cutover, inp.months[0], opening["BS.INCOME_TAX"],
                    opening["BS.DEFERRED_TAX"]) if inp.tax and inp.months else None)  # fmt: skip
    bs = dict(opening)
    revolver = ZERO  # part of current debt, tracked for its own rate and rule
    months: list[Month] = []
    notes: list[str] = []
    # Loans of the set (M6F-4); the rest of the opening debt is "other debt" (drivers).
    schedules = {loan.code: {r.month: r for r in project_loan(loan, inp.months)}
                 for loan in inp.loans}  # fmt: skip
    first = inp.months[0] if inp.months else date.min
    existing = [loan for loan in inp.loans if loan.drawdown_month is None]
    current0 = sum((opening_current(loan, first) for loan in existing), ZERO)
    other_current = opening["BS.DEBT.CURRENT"] - current0
    existing_total = sum((cents(loan.opening) for loan in existing), ZERO)
    other_noncurrent = opening["BS.DEBT.NONCURRENT"] - (existing_total - current0)
    for month in inp.months:
        prev = dict(bs)
        days = Decimal(calendar.monthrange(month.year, month.month)[1])
        dep = cents(inp.register_depreciation.get(month, ZERO) + new_dep.get(month, ZERO))
        loans = {code: rows[month] for code, rows in schedules.items()}
        other_opening = other_current + other_noncurrent
        other_interest = cents(other_opening * _d(inp, "interest_rate", month) / HUNDRED / TWELVE)
        revolver_interest = cents(revolver * _d(inp, "revolver_rate", month) / HUNDRED / TWELVE)
        loan_interest = sum((r.interest for r in loans.values()), ZERO)
        pl = _income(inp, month, dep, loan_interest + other_interest + revolver_interest)
        tax_month = None
        if book is not None and inp.tax is not None:
            tax_month = book.step(
                month, pbt=pl["PL.PBT"], da=dep, adjustment=cents(_d(inp, "tax_adjustment", month)),
                new_allowances=capex_plan.allowances.get(month.year, ZERO),
                qualifying_dep=inp.tax.qualifying_dep.get(month, ZERO)
                + capex_plan.qualifying.get(month, ZERO),
            )  # fmt: skip
        pl["PL.TAX.CURRENT"] = tax_month.current if tax_month else ZERO
        pl["PL.TAX.DEFERRED"] = tax_month.deferred if tax_month else ZERO
        pl["PL.TAX"] = pl["PL.TAX.CURRENT"] + pl["PL.TAX.DEFERRED"]
        pl["PL.NET_INCOME"] = pl["PL.PBT"] - pl["PL.TAX"]
        # Working capital and fixed assets.
        bs["BS.AR"] = cents(pl["PL.REVENUE"] * _d(inp, "dso", month) / days)
        bs["BS.INVENTORY"] = cents(pl["PL.COGS"] * _d(inp, "dio", month) / days)
        bs["BS.AP"] = cents(pl["PL.COGS"] * _d(inp, "dpo", month) / days)
        capex = cents(_d(inp, "capex", month)) + sum(
            (cents(x.amount) for x in inp.extra_capex if x.month == month), ZERO
        )
        settled = {line: cents(v) for line, v in inp.settlements.get(month, {}).items()}
        for line, amount in settled.items():
            bs[line] = prev[line] - amount
        bs["BS.PPE.GROSS"] = prev["BS.PPE.GROSS"] + capex
        bs["BS.PPE.ACCDEP"] = prev["BS.PPE.ACCDEP"] - dep
        # Income tax (M6F-5): what is owed and deferred, from the tax book.
        tax_paid = tax_month.paid if tax_month else ZERO
        bs["BS.INCOME_TAX"] = tax_month.income_tax if tax_month else prev["BS.INCOME_TAX"]
        bs["BS.DEFERRED_TAX"] = tax_month.deferred_tax if tax_month else prev["BS.DEFERRED_TAX"]
        # Other debt: new borrowing is non-current; repayments reduce current debt first.
        borrowing = cents(_d(inp, "borrowing", month))
        asked = cents(_d(inp, "repayment", month))
        repayment = max(min(asked, other_opening + borrowing), ZERO)
        if repayment < asked:
            notes.append(f"{month:%Y-%m}: repayment capped at the other debt owed ({repayment}).")
        from_current = min(repayment, max(other_current, ZERO))
        other_current -= from_current
        other_noncurrent += borrowing - (repayment - from_current)
        # Loans (M6F-4).
        drawn = sum((r.drawdown for r in loans.values()), ZERO)
        repaid = sum((r.principal + r.prepayment for r in loans.values()), ZERO)
        loans_closing = sum((r.closing for r in loans.values()), ZERO)
        loans_current = sum((r.current for r in loans.values()), ZERO)
        # Equity.
        dividends = cents(_d(inp, "dividends", month))
        issued = cents(_d(inp, "share_capital", month))
        bs["BS.EQUITY.SHARE_CAPITAL"] = prev["BS.EQUITY.SHARE_CAPITAL"] + issued
        bs["BS.EQUITY.RETAINED"] = prev["BS.EQUITY.RETAINED"] + pl["PL.NET_INCOME"] - dividends
        # Cash flow statement (indirect).
        cf: dict[str, Decimal] = {"CF.NET_INCOME": pl["PL.NET_INCOME"], "CF.DA": dep}
        cf["CF.WC.AR"] = prev["BS.AR"] - bs["BS.AR"]
        cf["CF.WC.INVENTORY"] = prev["BS.INVENTORY"] - bs["BS.INVENTORY"]
        cf["CF.WC.AP"] = bs["BS.AP"] - prev["BS.AP"]
        cf["CF.TAX_EXPENSE"] = pl["PL.TAX"]
        cf["CF.TAX_PAID"] = -tax_paid
        operating = ["CF.NET_INCOME", "CF.DA", "CF.TAX_EXPENSE", "CF.WC.AR", "CF.WC.INVENTORY",
                     "CF.WC.AP", "CF.TAX_PAID"]  # fmt: skip
        if inp.settlements:  # M7-2: a scenario's one-off settlements of held liabilities
            cf["CF.SETTLEMENTS"] = -sum(settled.values(), ZERO)
            operating.append("CF.SETTLEMENTS")
        cf["CF.OPERATING"] = sum((cf[k] for k in operating), ZERO)
        cf["CF.CAPEX"] = -capex
        cf["CF.INVESTING"] = cf["CF.CAPEX"]
        cf["CF.BORROWING"], cf["CF.REPAYMENT"] = borrowing + drawn, -(repayment + repaid)
        cf["CF.SHARE_CAPITAL"], cf["CF.DIVIDENDS"] = issued, -dividends
        before = (prev["BS.CASH"] + cf["CF.OPERATING"] + cf["CF.INVESTING"] + cf["CF.BORROWING"]
                  + cf["CF.REPAYMENT"] + issued - dividends)  # fmt: skip
        # The credit facility (doc 10 §4.1 step 8).
        minimum = cents(_d(inp, "minimum_cash", month))
        limit = cents(_d(inp, "revolver_limit", month))
        draw = repay = ZERO
        if before < minimum and limit > revolver:
            draw = min(minimum - before, limit - revolver)
        elif before > minimum and revolver > 0:
            repay = min(revolver, before - minimum)
        revolver_opening = revolver
        revolver += draw - repay
        cf["CF.REVOLVER"] = draw - repay
        cf["CF.FINANCING"] = (cf["CF.BORROWING"] + cf["CF.REPAYMENT"] + issued - dividends
                              + cf["CF.REVOLVER"])  # fmt: skip
        cf["CF.NET_CHANGE"] = cf["CF.OPERATING"] + cf["CF.INVESTING"] + cf["CF.FINANCING"]
        cf["CF.OPENING_CASH"] = prev["BS.CASH"]
        cf["CF.CLOSING_CASH"] = prev["BS.CASH"] + cf["CF.NET_CHANGE"]
        bs["BS.CASH"] = before + cf["CF.REVOLVER"]
        bs["BS.DEBT.NONCURRENT"] = other_noncurrent + loans_closing - loans_current
        bs["BS.DEBT.CURRENT"] = other_current + loans_current + revolver
        if bs["BS.CASH"] < 0:
            notes.append(f"{month:%Y-%m}: cash would be negative ({bs['BS.CASH']}).")
        other = {"opening": other_opening, "interest": other_interest, "borrowing": borrowing,
                 "repayment": repayment, "closing": other_current + other_noncurrent,
                 "revolver_opening": revolver_opening, "revolver_interest": revolver_interest,
                 "revolver": revolver}  # fmt: skip
        months.append(Month(month, pl, dict(bs), cf, loans, other, tax_month))
    projection = Projection(opening, months, {}, notes)
    projection.invariants = check(projection, inp)
    return projection


# --- invariants (doc 10 §4.2) -------------------------------------------------------------------


def totals(bs: dict[str, Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    return (sum((bs[x] for x in ASSETS), ZERO), sum((bs[x] for x in LIABILITIES), ZERO),
            sum((bs[x] for x in EQUITY), ZERO))  # fmt: skip


HELD = ("BS.INTANGIBLES", "BS.INVESTMENTS", "BS.OTHER_REC", "BS.TAX_REC", "BS.OTHER_PAY",
        "BS.TAX_PAY", "BS.EQUITY.SHARE_PREMIUM")  # fmt: skip


def _debt_reconciles(m: Month, start: dict[str, Decimal]) -> bool:
    """M6F-4: each loan's roll-forward ties and opens on its previous closing (``start``); the
    debt lines equal the loans, the other debt and the credit facility; interest is the sum of
    its parts."""
    loans_ok = all(
        r.opening == start.get(code, ZERO)
        and r.opening + r.drawdown - r.principal - r.prepayment == r.closing
        and r.closing >= 0
        and 0 <= r.current <= r.closing
        for code, r in m.loans.items()
    )
    o = m.other_debt
    if not o:
        return loans_ok
    debt = m.bs["BS.DEBT.NONCURRENT"] + m.bs["BS.DEBT.CURRENT"]
    closing = sum((r.closing for r in m.loans.values()), ZERO) + o["closing"] + o["revolver"]
    interest = (sum((r.interest for r in m.loans.values()), ZERO) + o["interest"]
                + o["revolver_interest"])  # fmt: skip
    other_ok = o["opening"] + o["borrowing"] - o["repayment"] == o["closing"]
    return loans_ok and other_ok and debt == closing and m.pl["PL.INTEREST"] == interest


def _tax_reconciles(m: Month, prev: dict[str, Decimal]) -> bool:
    """M6F-5: income tax owed rolls forward by the current tax less what is paid; deferred tax by
    the deferred tax expense; the tax expense is their sum; the statements carry the tax book's
    expense, payments and balances; at a year end the loss pool rolls
    forward (before + arising - used - expired = after)."""
    pl, bs, cf = m.pl, m.bs, m.cf
    ok = (bs["BS.INCOME_TAX"] - prev["BS.INCOME_TAX"] == pl["PL.TAX.CURRENT"] + cf["CF.TAX_PAID"]
          and bs["BS.DEFERRED_TAX"] - prev["BS.DEFERRED_TAX"] == pl["PL.TAX.DEFERRED"]
          and pl["PL.TAX"] == pl["PL.TAX.CURRENT"] + pl["PL.TAX.DEFERRED"]
          and cf["CF.TAX_EXPENSE"] == pl["PL.TAX"])  # fmt: skip
    t = m.tax
    if t is not None:  # the statements carry the tax book's figures
        ok = ok and (pl["PL.TAX.CURRENT"] == t.current and pl["PL.TAX.DEFERRED"] == t.deferred
                     and cf["CF.TAX_PAID"] == -t.paid and bs["BS.INCOME_TAX"] == t.income_tax
                     and bs["BS.DEFERRED_TAX"] == t.deferred_tax)  # fmt: skip
    if t is not None and t.year and m.month.month == 12:
        ok = ok and (t.pool_before + t.losses_arising - t.losses_used - t.losses_expired
                     == t.pool_after) and t.losses_used >= 0  # fmt: skip
    return ok


def _month_checks(m: Month, prev: dict[str, Decimal], loan_start: dict[str, Decimal],
                  settled: dict[str, Decimal]) -> dict[str, bool]:  # fmt: skip
    a, liabilities, e = totals(m.bs)
    debt = m.bs["BS.DEBT.NONCURRENT"] + m.bs["BS.DEBT.CURRENT"]
    debt_before = prev["BS.DEBT.NONCURRENT"] + prev["BS.DEBT.CURRENT"]
    return {
        "balance_sheet_balances": a == liabilities + e,
        "cash_ties": m.cf["CF.CLOSING_CASH"] == m.bs["BS.CASH"]
        and m.cf["CF.OPENING_CASH"] == prev["BS.CASH"],
        "retained_earnings_roll": m.bs["BS.EQUITY.RETAINED"]
        == prev["BS.EQUITY.RETAINED"] + m.pl["PL.NET_INCOME"] + m.cf["CF.DIVIDENDS"],
        "opening_equals_previous_closing": all(
            m.bs[x] == prev[x] - settled.get(x, ZERO) for x in HELD),
        "roll_forwards_tie": all((
            m.bs["BS.PPE.GROSS"] - prev["BS.PPE.GROSS"] == -m.cf["CF.CAPEX"],
            m.bs["BS.PPE.ACCDEP"] - prev["BS.PPE.ACCDEP"] == -m.cf["CF.DA"],
            debt - debt_before == m.cf["CF.BORROWING"] + m.cf["CF.REPAYMENT"] + m.cf["CF.REVOLVER"],
            m.bs["BS.AR"] - prev["BS.AR"] == -m.cf["CF.WC.AR"],
            m.bs["BS.INVENTORY"] - prev["BS.INVENTORY"] == -m.cf["CF.WC.INVENTORY"],
            m.bs["BS.AP"] - prev["BS.AP"] == m.cf["CF.WC.AP"],
            m.bs["BS.EQUITY.SHARE_CAPITAL"] - prev["BS.EQUITY.SHARE_CAPITAL"]
            == m.cf["CF.SHARE_CAPITAL"],
        )),
        "debt_reconciles": _debt_reconciles(m, loan_start),
        "tax_reconciles": _tax_reconciles(m, prev),
    }  # fmt: skip


def check(p: Projection, inp: EngineInput) -> dict[str, bool]:
    """The invariants over every month (doc 10's six, and the debt reconciliation of M6F-4). A
    failure also adds "<invariant>@<YYYY-MM>": False,
    so a run that fails says where (brief AC-PJ6)."""
    ok = dict.fromkeys(INVARIANTS, True)
    failures: dict[str, bool] = {}

    def record(name: str, passed: bool, where: str) -> None:
        if not passed:
            ok[name] = False
            failures[f"{name}@{where}"] = False

    a, liabilities, e = totals(p.opening)
    record("balance_sheet_balances", a == liabilities + e, "opening")
    # Period 1 opens on the actual balance sheet (inputs rounded to cents only).
    record("opening_equals_previous_closing",
           all(p.opening[x] == cents(inp.opening.get(x, ZERO)) for x in BS_LINES),
           "opening")  # fmt: skip
    prev = p.opening
    loan_start = {loan.code: cents(loan.opening) if loan.drawdown_month is None else ZERO
                  for loan in inp.loans}  # fmt: skip
    for m in p.months:
        settled = {line: cents(v) for line, v in inp.settlements.get(m.month, {}).items()}
        for name, passed in _month_checks(m, prev, loan_start, settled).items():
            record(name, passed, f"{m.month:%Y-%m}")
        prev = m.bs
        loan_start = {code: r.closing for code, r in m.loans.items()}
    for where in _aggregate_failures(p):
        record("aggregation_consistent", False, where)
    return {**ok, **failures}


Bucket = tuple[date, date, dict[str, Decimal], dict[str, Decimal]]


def aggregate(p: Projection, months_per_bucket: int) -> list[Bucket]:
    """Flows summed, and balances at the end, per bucket of whole months from the first month."""
    buckets: list[Bucket] = []
    for i in range(0, len(p.months), months_per_bucket):
        part = p.months[i : i + months_per_bucket]
        flows: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for m in part:
            for key, value in {**m.pl, **m.cf}.items():
                if key not in ("CF.OPENING_CASH", "CF.CLOSING_CASH"):
                    flows[key] += value
        flows["CF.OPENING_CASH"] = part[0].cf["CF.OPENING_CASH"]
        flows["CF.CLOSING_CASH"] = part[-1].cf["CF.CLOSING_CASH"]
        buckets.append((part[0].month, month_end(part[-1].month), dict(flows), part[-1].bs))
    return buckets


def _aggregate_failures(p: Projection) -> list[str]:
    """Doc 10 §4.2 (6): every bucket's flows sum its months, and its cash ties."""
    failed = []
    for size, label in ((3, "Q"), (12, "Y")):
        for start, _, flows, bs in aggregate(p, size):
            inside = [m for m in p.months if start <= m.month < add_months(start, size)]
            if not all((
                flows["PL.NET_INCOME"] == sum((m.pl["PL.NET_INCOME"] for m in inside), ZERO),
                flows["CF.CLOSING_CASH"] == bs["BS.CASH"],
                flows["CF.OPENING_CASH"] + flows["CF.NET_CHANGE"] == flows["CF.CLOSING_CASH"],
            )):  # fmt: skip
                failed.append(f"{label}{start:%Y-%m}")
    return failed


# --- as calculation-run values --------------------------------------------------------------------


def values(p: Projection, inp: EngineInput) -> list[Value]:
    """Monthly values with lineage, and quarter and year totals, for the calculation run."""
    out: list[Value] = []
    first = add_months(inp.months[0], -1)
    for line in BS_LINES:  # the actual balance sheet at the cut-over
        out.append(Value(line, first, Nature.ACTUAL, p.opening[line], inp.currency,
                         period_end=inp.cutover, granularity="MONTH",
                         lineage=(Source("ACTUAL", f"balance:{line}:{inp.cutover.isoformat()}",
                                         p.opening[line]),)))  # fmt: skip
    for m in p.months:
        end = month_end(m.month)
        for key, amount in {**m.pl, **m.bs, **m.cf}.items():
            out.append(Value(key, m.month, Nature.FORECAST, amount, inp.currency, period_end=end,
                             granularity="MONTH", lineage=_lineage(key, m, inp)))  # fmt: skip
        out += _loan_values(m, inp, end)
        out += _tax_values(m, inp, end)
    for size, granularity in ((3, "QUARTER"), (12, "YEAR")):
        for start, end, flows, bs in aggregate(p, size):
            for key, amount in {**flows, **bs}.items():
                out.append(Value(key, start, Nature.FORECAST, amount, inp.currency, period_end=end,
                                 granularity=granularity))  # fmt: skip
    return out


LOAN_FIELDS = ("opening", "interest", "drawdown", "principal", "prepayment", "closing", "current")


def _loan_values(m: Month, inp: EngineInput, end: date) -> list[Value]:
    """Each loan's month (M6F-4): ``DEBT.<code>.<field>``, and its rate as ``DEBT.<code>.rate``."""
    ref = f"assumption_set:{inp.set_id}"
    out = []
    for code, r in m.loans.items():
        lineage = (Source("ASSUMPTION", f"{ref}:loan:{code}:{m.month:%Y-%m}", None,
                          "loan terms, rate path, early repayments and drawdowns"),)  # fmt: skip
        for name in LOAN_FIELDS:
            out.append(Value(f"DEBT.{code}.{name}", m.month, Nature.FORECAST, getattr(r, name),
                             inp.currency, period_end=end, granularity="MONTH",
                             lineage=lineage))  # fmt: skip
        out.append(Value(f"DEBT.{code}.rate", m.month, Nature.FORECAST, r.rate, "percent",
                         period_end=end, granularity="MONTH", lineage=lineage))  # fmt: skip
    return out


def _tax_source(m: Month) -> Source:
    t = m.tax
    if t is None:
        return Source("FORMULA", "tax:none", None, "no tax rules: no income tax")
    status = "verified" if t.verified else "pending professional verification"
    return Source("ASSUMPTION", f"tax_rules:{t.rule_id}", None, f"rule set {status}")


def _tax_values(m: Month, inp: EngineInput, end: date) -> list[Value]:
    """The tax book's month (M6F-5): taxable profit to date, tax paid, losses available."""
    t = m.tax
    if t is None:
        return []
    lineage = (_tax_source(m),)
    return [
        Value(key, m.month, Nature.FORECAST, amount, inp.currency, period_end=end,
              granularity="MONTH", lineage=lineage)
        for key, amount in (("TAX.TAXABLE_YTD", t.taxable_ytd), ("TAX.PAID", t.paid),
                            ("TAX.LOSSES_AVAILABLE", t.losses_available))
    ]  # fmt: skip


def _lineage(key: str, m: Month, inp: EngineInput) -> tuple[Source, ...]:
    ref = f"assumption_set:{inp.set_id}"
    month = f"{m.month:%Y-%m}"
    code = key.removeprefix("PL.")
    if code in REVENUE_LINES:
        return (Source("ASSUMPTION", f"{ref}:revenue:{code}:{month}", m.pl[key]),)
    if code in OPEX_LINES:
        return (Source("ASSUMPTION", f"{ref}:opex:{code}:{month}", m.pl[key]),)
    simple = {
        "PL.COGS": ("gross_margin", "cost of sales = sales and services x (100% - gross margin)"),
        "PL.INTEREST": (
            "interest_rate",
            "on opening balances: each loan at its rate, other debt "
            "and the credit facility at theirs",
        ),
        "PL.TAX": (
            "tax_adjustment",
            "current tax (rule set, losses carried forward) plus deferred tax",
        ),
        "BS.AR": ("dso", "revenue x DSO / days in the month"),
        "BS.INVENTORY": ("dio", "cost of sales x DIO / days in the month"),
        "BS.AP": ("dpo", "cost of sales x DPO / days in the month"),
        "CF.CAPEX": ("capex", "capital expenditure"),
        "CF.BORROWING": ("borrowing", "new borrowing"),
        "CF.REPAYMENT": ("repayment", "repayments, capped at the debt owed"),
        "CF.DIVIDENDS": ("dividends", "dividends paid"),
        "CF.SHARE_CAPITAL": ("share_capital", "new share capital"),
        "CF.REVOLVER": ("revolver_limit", "credit facility drawn or repaid around minimum cash"),
    }
    if key in ("PL.TAX.CURRENT", "PL.TAX.DEFERRED", "BS.INCOME_TAX", "BS.DEFERRED_TAX",
               "CF.TAX_PAID"):  # fmt: skip
        return (_tax_source(m),)
    if key in simple:
        driver, note = simple[key]
        return (Source("ASSUMPTION", f"{ref}:{driver}:{month}", None, note),)
    if key == "PL.DA":
        return (
            Source("SCHEDULE", f"fixed_assets:{month}", inp.register_depreciation.get(m.month),
                   "registered assets"),
            Source("ASSUMPTION", f"{ref}:capex:{month}", None, "new capital expenditure"),
        )  # fmt: skip
    return (Source("FORMULA", f"projection:{key}", None, "from other lines of the month"),)


def output(inp: EngineInput) -> tuple[Projection, Output]:
    p = project(inp)
    return p, Output(values=tuple(values(p, inp)), invariants=p.invariants)
