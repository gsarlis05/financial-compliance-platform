"""The three-statement projection engine (M6-3, doc 10 §4): a pure function, no database.

Order of calculation per month (doc 10 §4.1):
1. Income statement to EBIT: revenue per line; cost of sales from the gross margin on sales and
   services; operating costs per line; depreciation of the registered assets and of new capital
   expenditure (straight-line over its life, from the month after it is spent).
2. Interest on the **opening** debt and credit facility of the month (no circularity).
3. Tax on a positive profit before tax at the assumed rate (no relief for losses); net income.
4. Working capital from days: receivables = revenue x DSO / days in the month; inventory and
   payables = cost of sales x DIO (or DPO) / days in the month. Fixed assets roll forward
   (+ capex, - depreciation).
5. Debt rolls forward: + new borrowing, - repayments (capped at what is owed; current debt first).
6. Equity rolls forward: + net income - dividends + new share capital.
7. Cash flow statement (indirect method). Tax payable is paid in the first month of each fiscal
   year (the balance owed at the start of that month).
8. Closing cash = opening cash + net cash flow; then the credit facility: drawn up to its limit
   when cash would fall below the minimum, repaid when cash is above it.
9. Balance sheet from the roll-forwards. Lines the drivers do not cover (intangibles,
   investments, other receivables and payables, tax receivable, share premium) are held.

Rounding (doc 10 §2.4): each statement line is rounded to cents once per month; totals, cash and
retained earnings are sums of rounded lines, so the statements tie to the cent with no plug.

Every run checks the six invariants of doc 10 §4.2; the framework marks a run that fails one
INVALID, and an invalid run cannot be published.
"""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from fcp.modules.assets.api import AssetTerms, schedule
from fcp.modules.calendar.api import add_months, month_end
from fcp.modules.metrics.api import Nature, Output, Source, Value

from .drivers import OPEX_LINES, REVENUE_LINES

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED, TWELVE = Decimal(100), Decimal(12)
ASSETS = ("BS.PPE.GROSS", "BS.PPE.ACCDEP", "BS.INTANGIBLES", "BS.INVESTMENTS", "BS.INVENTORY",
          "BS.AR", "BS.OTHER_REC", "BS.TAX_REC", "BS.CASH")  # fmt: skip
LIABILITIES = ("BS.DEBT.NONCURRENT", "BS.DEBT.CURRENT", "BS.AP", "BS.OTHER_PAY", "BS.TAX_PAY")
EQUITY = ("BS.EQUITY.SHARE_CAPITAL", "BS.EQUITY.SHARE_PREMIUM", "BS.EQUITY.RETAINED")
BS_LINES = ASSETS + LIABILITIES + EQUITY
INVARIANTS = (
    "balance_sheet_balances",
    "cash_ties",
    "retained_earnings_roll",
    "opening_equals_previous_closing",
    "roll_forwards_tie",
    "aggregation_consistent",
)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT)


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


@dataclass
class Month:
    month: date
    pl: dict[str, Decimal]
    bs: dict[str, Decimal]
    cf: dict[str, Decimal]


@dataclass
class Projection:
    opening: dict[str, Decimal]
    months: list[Month]
    invariants: dict[str, bool]
    notes: list[str]


def _d(inp: EngineInput, key: str, month: date, line: str = "") -> Decimal:
    return inp.drivers.get((key, line), {}).get(month, Decimal(0))


def _new_capex_depreciation(inp: EngineInput) -> dict[date, Decimal]:
    found: dict[date, Decimal] = defaultdict(lambda: ZERO)
    for month in inp.months:
        spent = cents(_d(inp, "capex", month))
        if spent <= 0:
            continue
        life = max(int(_d(inp, "capex_life", month)), 1)
        for row in schedule(AssetTerms(month, spent, Decimal(0), life)):
            found[row.month] += row.depreciation
    return found


def _income(inp: EngineInput, month: date, depreciation: Decimal,
            debt: Decimal, revolver: Decimal) -> dict[str, Decimal]:  # fmt: skip
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
    pl["PL.INTEREST"] = cents(debt * _d(inp, "interest_rate", month) / HUNDRED / TWELVE) + cents(
        revolver * _d(inp, "revolver_rate", month) / HUNDRED / TWELVE
    )
    pl["PL.PBT"] = pl["PL.EBIT"] - pl["PL.INTEREST"]
    rate = _d(inp, "tax_rate", month)
    pl["PL.TAX"] = cents(pl["PL.PBT"] * rate / HUNDRED) if pl["PL.PBT"] > 0 else ZERO
    pl["PL.NET_INCOME"] = pl["PL.PBT"] - pl["PL.TAX"]
    return pl


def project(inp: EngineInput) -> Projection:  # noqa: PLR0915 (one month, in doc 10's order)
    """Project the three statements month by month (see the module text)."""
    opening = {line: cents(inp.opening.get(line, ZERO)) for line in BS_LINES}
    new_dep = _new_capex_depreciation(inp)
    bs = dict(opening)
    revolver = ZERO  # part of current debt, tracked for its own rate and rule
    months: list[Month] = []
    notes: list[str] = []
    for month in inp.months:
        prev = dict(bs)
        days = Decimal(calendar.monthrange(month.year, month.month)[1])
        dep = cents(inp.register_depreciation.get(month, ZERO) + new_dep.get(month, ZERO))
        term_debt = prev["BS.DEBT.NONCURRENT"] + prev["BS.DEBT.CURRENT"] - revolver
        pl = _income(inp, month, dep, term_debt, revolver)
        # Working capital and fixed assets.
        bs["BS.AR"] = cents(pl["PL.REVENUE"] * _d(inp, "dso", month) / days)
        bs["BS.INVENTORY"] = cents(pl["PL.COGS"] * _d(inp, "dio", month) / days)
        bs["BS.AP"] = cents(pl["PL.COGS"] * _d(inp, "dpo", month) / days)
        capex = cents(_d(inp, "capex", month))
        bs["BS.PPE.GROSS"] = prev["BS.PPE.GROSS"] + capex
        bs["BS.PPE.ACCDEP"] = prev["BS.PPE.ACCDEP"] - dep
        # Tax: accrued this month; last year's balance paid in the first month of a fiscal year.
        tax_paid = prev["BS.TAX_PAY"] if month in inp.fiscal_year_starts else ZERO
        bs["BS.TAX_PAY"] = prev["BS.TAX_PAY"] - tax_paid + pl["PL.TAX"]
        # Debt: new borrowing is non-current; repayments reduce current debt first.
        borrowing = cents(_d(inp, "borrowing", month))
        asked = cents(_d(inp, "repayment", month))
        repayment = max(min(asked, term_debt + borrowing), ZERO)
        if repayment < asked:
            notes.append(f"{month:%Y-%m}: repayment capped at the debt owed ({repayment}).")
        current_term = prev["BS.DEBT.CURRENT"] - revolver
        from_current = min(repayment, max(current_term, ZERO))
        noncurrent = prev["BS.DEBT.NONCURRENT"] + borrowing - (repayment - from_current)
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
        cf["CF.WC.TAX"] = bs["BS.TAX_PAY"] - prev["BS.TAX_PAY"]
        cf["CF.OPERATING"] = sum((cf[k] for k in ("CF.NET_INCOME", "CF.DA", "CF.WC.AR",
                                                   "CF.WC.INVENTORY", "CF.WC.AP", "CF.WC.TAX")),
                                 ZERO)  # fmt: skip
        cf["CF.CAPEX"] = -capex
        cf["CF.INVESTING"] = cf["CF.CAPEX"]
        cf["CF.BORROWING"], cf["CF.REPAYMENT"] = borrowing, -repayment
        cf["CF.SHARE_CAPITAL"], cf["CF.DIVIDENDS"] = issued, -dividends
        before = (prev["BS.CASH"] + cf["CF.OPERATING"] + cf["CF.INVESTING"] + borrowing
                  - repayment + issued - dividends)  # fmt: skip
        # The credit facility (doc 10 §4.1 step 8).
        minimum = cents(_d(inp, "minimum_cash", month))
        limit = cents(_d(inp, "revolver_limit", month))
        draw = repay = ZERO
        if before < minimum and limit > revolver:
            draw = min(minimum - before, limit - revolver)
        elif before > minimum and revolver > 0:
            repay = min(revolver, before - minimum)
        revolver += draw - repay
        cf["CF.REVOLVER"] = draw - repay
        cf["CF.FINANCING"] = borrowing - repayment + issued - dividends + cf["CF.REVOLVER"]
        cf["CF.NET_CHANGE"] = cf["CF.OPERATING"] + cf["CF.INVESTING"] + cf["CF.FINANCING"]
        cf["CF.OPENING_CASH"] = prev["BS.CASH"]
        cf["CF.CLOSING_CASH"] = prev["BS.CASH"] + cf["CF.NET_CHANGE"]
        bs["BS.CASH"] = before + cf["CF.REVOLVER"]
        bs["BS.DEBT.NONCURRENT"] = noncurrent
        bs["BS.DEBT.CURRENT"] = current_term - from_current + revolver
        if bs["BS.CASH"] < 0:
            notes.append(f"{month:%Y-%m}: cash would be negative ({bs['BS.CASH']}).")
        months.append(Month(month, pl, dict(bs), cf))
    projection = Projection(opening, months, {}, notes)
    projection.invariants = check(projection, inp)
    return projection


# --- invariants (doc 10 §4.2) -------------------------------------------------------------------


def totals(bs: dict[str, Decimal]) -> tuple[Decimal, Decimal, Decimal]:
    return (sum((bs[x] for x in ASSETS), ZERO), sum((bs[x] for x in LIABILITIES), ZERO),
            sum((bs[x] for x in EQUITY), ZERO))  # fmt: skip


HELD = ("BS.INTANGIBLES", "BS.INVESTMENTS", "BS.OTHER_REC", "BS.TAX_REC", "BS.OTHER_PAY",
        "BS.EQUITY.SHARE_PREMIUM")  # fmt: skip


def _month_checks(m: Month, prev: dict[str, Decimal]) -> dict[str, bool]:
    a, liabilities, e = totals(m.bs)
    debt = m.bs["BS.DEBT.NONCURRENT"] + m.bs["BS.DEBT.CURRENT"]
    debt_before = prev["BS.DEBT.NONCURRENT"] + prev["BS.DEBT.CURRENT"]
    return {
        "balance_sheet_balances": a == liabilities + e,
        "cash_ties": m.cf["CF.CLOSING_CASH"] == m.bs["BS.CASH"]
        and m.cf["CF.OPENING_CASH"] == prev["BS.CASH"],
        "retained_earnings_roll": m.bs["BS.EQUITY.RETAINED"]
        == prev["BS.EQUITY.RETAINED"] + m.pl["PL.NET_INCOME"] + m.cf["CF.DIVIDENDS"],
        "opening_equals_previous_closing": all(m.bs[x] == prev[x] for x in HELD),
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
    }  # fmt: skip


def check(p: Projection, inp: EngineInput) -> dict[str, bool]:
    """The six invariants over every month. A failure also adds "<invariant>@<YYYY-MM>": False,
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
    for m in p.months:
        for name, passed in _month_checks(m, prev).items():
            record(name, passed, f"{m.month:%Y-%m}")
        prev = m.bs
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
        out.append(Value(line, first, Nature.ACTUAL, p.opening[line], "EUR",
                         period_end=inp.cutover, granularity="MONTH",
                         lineage=(Source("ACTUAL", f"balance:{line}:{inp.cutover.isoformat()}",
                                         p.opening[line]),)))  # fmt: skip
    for m in p.months:
        end = month_end(m.month)
        for key, amount in {**m.pl, **m.bs, **m.cf}.items():
            out.append(Value(key, m.month, Nature.FORECAST, amount, "EUR", period_end=end,
                             granularity="MONTH", lineage=_lineage(key, m, inp)))  # fmt: skip
    for size, granularity in ((3, "QUARTER"), (12, "YEAR")):
        for start, end, flows, bs in aggregate(p, size):
            for key, amount in {**flows, **bs}.items():
                out.append(Value(key, start, Nature.FORECAST, amount, "EUR", period_end=end,
                                 granularity=granularity))  # fmt: skip
    return out


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
        "PL.INTEREST": ("interest_rate", "on opening debt; credit facility at its own rate"),
        "PL.TAX": ("tax_rate", "on a positive profit before tax; no relief for losses"),
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
