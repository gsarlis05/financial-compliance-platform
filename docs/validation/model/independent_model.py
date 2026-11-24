"""Independent 24-month three-statement model for the validation package (M6F-8, #153).

Written from the documented conventions (docs/validation/01-scope-and-method.md, which cites
doc 10 §4, ADR-0040, ADR-0044, ADR-0045 and ADR-0046), not from the engine's code: it imports
nothing from the platform and needs only the Python standard library, so a reviewer can run it on
their own:

    python3 docs/validation/model/independent_model.py docs/validation/scenarios/s1-base.json

It prints every month's income statement, balance sheet and cash flow statement, then its own
reconciliation checks. Amounts are ``Decimal``; every statement line is rounded to cents
(half up) once, and totals are sums of rounded lines (rule R1 to R5 of the method).

Limitations (stated in the method): straight-line depreciation for new capital expenditure; the
cut-over is a calendar year end; tax years are calendar years; capital allowances of new capital
expenditure take a full year's allowance in the year of spend.
"""

# ruff: noqa: T201, PLR0915 (a stand-alone script that prints; one function per statement order)
from __future__ import annotations

import calendar
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
D = Decimal

REVENUE = ("REV.SALES", "REV.SERVICES", "REV.OTHER")
# The projection lines of the financial taxonomy (doc 10 §3).
OPEX = ("OPEX.PAYROLL", "OPEX.RENT", "OPEX.UTILITIES", "OPEX.PROFESSIONAL", "OPEX.MARKETING",
        "OPEX.TRAVEL", "OPEX.INSURANCE", "OPEX.OTHER")  # fmt: skip
ASSETS = ("BS.PPE.GROSS", "BS.PPE.ACCDEP", "BS.INTANGIBLES", "BS.INVESTMENTS", "BS.INVENTORY",
          "BS.AR", "BS.OTHER_REC", "BS.TAX_REC", "BS.CASH")  # fmt: skip
LIABILITIES = ("BS.DEBT.NONCURRENT", "BS.DEBT.CURRENT", "BS.AP", "BS.OTHER_PAY", "BS.TAX_PAY",
               "BS.INCOME_TAX", "BS.DEFERRED_TAX")  # fmt: skip
EQUITY = ("BS.EQUITY.SHARE_CAPITAL", "BS.EQUITY.SHARE_PREMIUM", "BS.EQUITY.RETAINED")
DEFAULTS = {"capex_life": D(60), "capex_start": D(1)}


def c(value: Decimal) -> Decimal:
    """Rule R1: round to cents, half up."""
    return value.quantize(CENT, ROUND_HALF_UP)


def next_month(m: date, n: int = 1) -> date:
    k = m.year * 12 + m.month - 1 + n
    return date(k // 12, k % 12 + 1, 1)


def months_between(a: date, b: date) -> int:
    return (b.year - a.year) * 12 + b.month - a.month


# --- the scenario --------------------------------------------------------------------------------


@dataclass
class Scenario:
    name: str
    first: date
    months: list[date]
    opening: dict[str, Decimal]
    drivers: dict[str, dict[date, Decimal]]  # "driver:line" -> month -> value
    register_dep: dict[date, Decimal]
    tax: dict[str, Any] | None
    loans: list[dict[str, Any]] = field(default_factory=list)
    split_opening_debt: bool = False  # opening current debt = the loans' current portion

    def get(self, key: str, m: date) -> Decimal:
        """A driver's value for the month; a driver the scenario does not set takes its default
        (``capex_life`` 60, ``capex_start`` 1), any other 0."""
        series = self.drivers.get(key)
        if series is None:
            return DEFAULTS.get(key.split(":", maxsplit=1)[0], D(0))
        return series.get(m, D(0))


def _series(value: Any, months: list[date]) -> dict[date, Decimal]:
    if isinstance(value, (str, int)):
        return dict.fromkeys(months, D(str(value)))
    return {date.fromisoformat(k + "-01" if len(k) == 7 else k): D(str(v))
            for k, v in value.items()}  # fmt: skip


def load(path: str | Path) -> Scenario:
    raw = json.loads(Path(path).read_text())
    first = date.fromisoformat(raw["first_month"])
    months = [next_month(first, n) for n in range(raw["months"])]
    drivers = {key: _series(v, months) for key, v in raw["drivers"].items()}
    reg = raw.get("register_depreciation", {})
    register = ({m: D(reg["amount"]) for m in months[: reg["months"]]} if "amount" in reg
                else _series(reg, months))  # fmt: skip
    opening = {k: D(v) for k, v in raw["opening"].items()}
    assets = sum((opening.get(k, D(0)) for k in ASSETS), D(0))
    claims = sum((opening.get(k, D(0)) for k in LIABILITIES + EQUITY), D(0))
    if assets != claims:
        raise ValueError(f"{raw['name']}: the opening balance sheet does not balance "
                         f"(assets {assets}, liabilities and equity {claims}).")  # fmt: skip
    return Scenario(raw["name"], first, months, opening, drivers, register, raw.get("tax"),
                    raw.get("loans", []), bool(raw.get("split_opening_debt")))  # fmt: skip


# --- new capital expenditure (ADR-0044, D1) -------------------------------------------------------


def capex_plan(s: Scenario) -> tuple[dict[date, Decimal], dict[date, Decimal], dict[int, Decimal]]:
    """Depreciation, depreciation of capex with allowances, and allowances by tax year."""
    dep: dict[date, Decimal] = {}
    qualifying: dict[date, Decimal] = {}
    allowances: dict[int, Decimal] = {}
    last_year = s.months[-1].year
    for m in s.months:
        spent = c(s.get("capex:", m))
        if spent <= 0:
            continue
        life = max(int(s.get("capex_life:", m)), 1)
        start = next_month(m, max(int(s.get("capex_start:", m)), 0))
        if s.get("capex_db_rate:", m) > 0:
            raise NotImplementedError("declining balance is outside this model's scope")
        each = c(spent / life)
        for k in range(life):
            amount = spent - each * (life - 1) if k == life - 1 else each
            month = next_month(start, k)
            dep[month] = dep.get(month, ZERO) + amount
            if s.get("capex_allowance_rate:", m) > 0:
                qualifying[month] = qualifying.get(month, ZERO) + amount
        rate = min(s.get("capex_allowance_rate:", m) / 100, D(1))
        left, year = spent, m.year
        while rate > 0 and left > 0 and year <= last_year:
            allowance = min(c(spent * rate), left)
            allowances[year] = allowances.get(year, ZERO) + allowance
            left -= allowance
            year += 1
    return dep, qualifying, allowances


# --- loans (ADR-0045, D5) -------------------------------------------------------------------------


def payment(balance: Decimal, r: Decimal, n: int) -> Decimal:
    """Level (annuity) payment on ``balance`` over ``n`` months at the monthly rate ``r``."""
    if n <= 0:
        return balance
    if r == 0:
        return c(balance / n)
    f = (1 + r) ** n
    return c(balance * r * f / (f - 1))


def scheduled(loan: dict[str, Any], balance: Decimal, rate: Decimal, idx: int) -> Decimal:
    """Scheduled principal in repayment month ``idx`` (0 = the first)."""
    term, io = loan["term_months"], loan.get("interest_only_months", 0)
    left = term - idx
    if balance <= 0 or left <= 0 or idx < 0:
        return ZERO
    if left == 1:
        return balance
    if idx < io or loan["structure"] == "BULLET":
        return ZERO
    if loan["structure"] == "EQUAL_PRINCIPAL":
        return min(c(balance / left), balance)
    interest = c(balance * rate / 1200)
    return min(max(payment(balance, rate / 1200, left) - interest, ZERO), balance)


def due_within_12(loan: dict[str, Any], balance: Decimal, rate: Decimal, idx: int) -> Decimal:
    """IAS 1.69: scheduled principal of the next 12 repayment months from ``idx``."""
    total = ZERO
    for k in range(12):
        p = scheduled(loan, balance, rate, idx + k)
        total += p
        balance -= p
    return total


@dataclass
class LoanRow:
    opening: Decimal
    interest: Decimal
    drawdown: Decimal
    principal: Decimal
    prepayment: Decimal
    closing: Decimal
    current: Decimal


def loan_rows(loan: dict[str, Any], months: list[date]) -> dict[date, LoanRow]:
    new = loan.get("drawdown_month") is not None
    drawn_in = date.fromisoformat(loan["drawdown_month"] + "-01") if new else None
    first = next_month(drawn_in) if drawn_in else months[0]
    path = _series(loan.get("rate_path", {}), months)
    pre = _series(loan.get("prepayments", {}), months)
    extra = _series(loan.get("drawdowns", {}), months)
    balance = ZERO if new else c(D(loan["opening"]))
    rate = D(str(loan["annual_rate"]))
    rows: dict[date, LoanRow] = {}
    for m in months:
        rate = path.get(m, rate)
        opening = balance
        interest = c(opening * rate / 1200)
        idx = months_between(first, m)
        principal = scheduled(loan, opening, rate, idx) if idx >= 0 else ZERO
        prepayment = max(min(c(pre.get(m, ZERO)), opening - principal), ZERO)
        drawdown = c(extra.get(m, ZERO)) + (c(D(loan["amount"])) if m == drawn_in else ZERO)
        balance = opening - principal - prepayment + drawdown
        rows[m] = LoanRow(opening, interest, drawdown, principal, prepayment, balance,
                          due_within_12(loan, balance, rate, idx + 1))  # fmt: skip
    return rows


def opening_current(loan: dict[str, Any], months: list[date]) -> Decimal:
    if loan.get("drawdown_month") is not None:
        return ZERO
    rate = _series(loan.get("rate_path", {}), months).get(months[0], D(str(loan["annual_rate"])))
    return due_within_12(loan, c(D(loan["opening"])), rate, 0)


# --- corporate tax (ADR-0046, D4) -----------------------------------------------------------------


class Tax:
    """The tax book: year-to-date current tax after usable losses, instalments, final payments
    and deferred tax. Cut-over at a calendar year end (no actual months in the first tax year)."""

    def __init__(self, spec: dict[str, Any], first: date, opening_tax: Decimal,
                 opening_deferred: Decimal) -> None:  # fmt: skip
        self.rules = {int(r["year"]): r for r in spec["rules"]}
        self.pool = [[int(y), c(D(a))] for y, a in sorted(spec.get("losses_bf", {}).items())
                     if D(a) > 0]  # fmt: skip
        self.allowances = {int(y): D(a) for y, a in spec.get("allowances", {}).items()}
        self.recognise = bool(spec.get("recognise_loss_dta", False))
        self.prior = c(opening_tax)
        before = self.rules.get(first.year - 1)
        self.prior_date = self.final_date(first.year - 1) if before else first
        self.prior_date = max(self.prior_date, first)
        self.owed: dict[int, Decimal] = {}
        self.paid: dict[int, Decimal] = {}
        self.year: int | None = None
        self.deferred = c(opening_deferred)
        self.opening_deferred = self.deferred
        self.temporary = D(0)
        rule = self.rules.get(first.year)
        self.asset_start = ZERO
        if self.recognise and rule:
            on_losses = c(self.usable(first.year) * D(rule["rate"]))
            self.asset_start = min(on_losses, max(-self.opening_deferred, ZERO))

    def final_date(self, year: int) -> date:
        month, day = (int(x) for x in self.rules[year]["final"].split("-"))
        return date(year + 1, month, day)

    def carry(self, year: int) -> int:
        return int(self.rules[year]["carry"]) if year in self.rules else 0

    def usable(self, year: int) -> Decimal:
        return sum((a for y, a in self.pool if y < year <= y + self.carry(y)), ZERO)

    def step(self, m: date, pbt: Decimal, da: Decimal, adjustment: Decimal,
             new_allowances: Decimal, qualifying: Decimal) -> dict[str, Any]:  # fmt: skip
        y, k = m.year, m.month
        rule = self.rules[y]
        rate = D(rule["rate"])
        if self.year != y:
            self.year, self.sum, self.accrued = y, D(0), ZERO
            self.paid[y], self.owed[y] = ZERO, ZERO
        self.sum += pbt + da + adjustment
        allowances = self.allowances.get(y, ZERO) + new_allowances
        taxable = self.sum - allowances * k / 12
        losses = self.usable(y)
        to_date = c(max(taxable - losses, ZERO) * rate)
        current = to_date - self.accrued
        self.accrued = to_date
        self.owed[y] += current
        payments = []
        # The balance owed for earlier years, then instalments, then final payments.
        if self.prior and (self.prior_date.year, self.prior_date.month) == (y, k):
            payments.append(("PRIOR", self.prior))
            self.prior = ZERO
        share = D(0)
        for day_month, part in rule["instalments"]:
            share += D(part)
            month = int(day_month.split("-")[0])
            if month != k:
                continue
            target = c(share * to_date * 12 / k)
            amount = max(target - self.paid[y], ZERO)
            if amount:
                self.paid[y] += amount
                self.owed[y] -= amount
                payments.append(("PROVISIONAL", amount))
        for year in sorted(self.owed):
            if year == y or year not in self.rules:
                continue
            due = self.final_date(year)
            if (due.year, due.month) == (y, k) and self.owed[year]:
                payments.append(("FINAL", self.owed[year]))
                self.owed[year] = ZERO
        # Deferred tax.
        self.temporary += allowances / 12 - qualifying
        liability = c(self.temporary * rate)
        position = losses + max(-taxable, ZERO) - min(losses, max(taxable, ZERO))
        asset = c(position * rate) - self.asset_start if self.recognise else ZERO
        balance = self.opening_deferred + liability - asset
        deferred = balance - self.deferred
        self.deferred = balance
        closed: dict[str, Decimal] = {}
        if k == 12:
            closed = self.close(y, taxable)
        return {"current": current, "deferred": deferred, "paid": sum((a for _, a in payments),
                ZERO), "payments": payments, "income_tax": self.prior + sum(self.owed.values(),
                ZERO), "deferred_tax": balance, "taxable_ytd": c(taxable), **closed}  # fmt: skip

    def close(self, year: int, taxable: Decimal) -> dict[str, Decimal]:
        before = sum((a for _, a in self.pool), ZERO)
        taxable = c(taxable)
        used = arising = expired = ZERO
        if taxable > 0:
            left = taxable
            for entry in self.pool:
                y = entry[0]
                if not y < year <= y + self.carry(y):
                    continue
                take = min(entry[1], left)
                entry[1] -= take
                used += take
                left -= take
        elif taxable < 0:
            arising = -taxable
            self.pool.append([year, arising])
        kept = []
        for entry in self.pool:
            if entry[1] > 0 and entry[0] + self.carry(entry[0]) > year:
                kept.append(entry)
            else:
                expired += entry[1]
        self.pool = kept
        after = sum((a for _, a in self.pool), ZERO)
        return {"losses_before": before, "losses_arising": arising, "losses_used": used,
                "losses_expired": expired, "losses_after": after}  # fmt: skip


# --- the model -----------------------------------------------------------------------------------


@dataclass
class Month:
    month: date
    pl: dict[str, Decimal]
    bs: dict[str, Decimal]
    cf: dict[str, Decimal]
    tax: dict[str, Any] = field(default_factory=dict)
    loans: dict[str, LoanRow] = field(default_factory=dict)


def run(s: Scenario) -> list[Month]:
    """The three statements month by month, in doc 10 §4.1's order."""
    bs = {k: c(s.opening.get(k, ZERO)) for k in ASSETS + LIABILITIES + EQUITY}
    dep_new, qualifying_new, allowances_new = capex_plan(s)
    tax = (Tax(s.tax, s.first, bs["BS.INCOME_TAX"], bs["BS.DEFERRED_TAX"]) if s.tax
           else None)  # fmt: skip
    schedules = {loan["code"]: loan_rows(loan, s.months) for loan in s.loans}
    existing = [loan for loan in s.loans if loan.get("drawdown_month") is None]
    loans_current0 = sum((opening_current(loan, s.months) for loan in existing), ZERO)
    loans_total0 = sum((c(D(loan["opening"])) for loan in existing), ZERO)
    if s.split_opening_debt:  # the books show the loans' current portion as current debt
        total = bs["BS.DEBT.CURRENT"] + bs["BS.DEBT.NONCURRENT"]
        bs["BS.DEBT.CURRENT"], bs["BS.DEBT.NONCURRENT"] = loans_current0, total - loans_current0
    other_cur = bs["BS.DEBT.CURRENT"] - loans_current0
    other_non = bs["BS.DEBT.NONCURRENT"] - (loans_total0 - loans_current0)
    revolver = ZERO
    out: list[Month] = []
    for m in s.months:
        prev = dict(bs)
        days = D(calendar.monthrange(m.year, m.month)[1])
        loans = {code: rows[m] for code, rows in schedules.items()}
        # 1. Income statement to EBIT.
        pl = {f"PL.{x}": c(s.get(f"revenue:{x}", m)) for x in REVENUE}
        pl["PL.REVENUE"] = sum((pl[f"PL.{x}"] for x in REVENUE), ZERO)
        sales = pl["PL.REV.SALES"] + pl["PL.REV.SERVICES"]
        pl["PL.COGS"] = c(sales * (100 - s.get("gross_margin:", m)) / 100)
        pl["PL.GROSS_PROFIT"] = pl["PL.REVENUE"] - pl["PL.COGS"]
        for x in OPEX:
            pl[f"PL.{x}"] = c(s.get(f"opex:{x}", m))
        pl["PL.OPEX"] = sum((pl[f"PL.{x}"] for x in OPEX), ZERO)
        pl["PL.EBITDA"] = pl["PL.GROSS_PROFIT"] - pl["PL.OPEX"]
        dep = c(s.register_dep.get(m, ZERO) + dep_new.get(m, ZERO))
        pl["PL.DA"] = dep
        pl["PL.EBIT"] = pl["PL.EBITDA"] - dep
        # 2. Interest on the opening balances.
        other_open = other_cur + other_non
        other_interest = c(other_open * s.get("interest_rate:", m) / 1200)
        revolver_interest = c(revolver * s.get("revolver_rate:", m) / 1200)
        pl["PL.INTEREST"] = (other_interest + revolver_interest
                             + sum((r.interest for r in loans.values()), ZERO))  # fmt: skip
        pl["PL.PBT"] = pl["PL.EBIT"] - pl["PL.INTEREST"]
        # 3. Corporate tax.
        t: dict[str, Any] = {}
        if tax is not None:
            t = tax.step(m, pl["PL.PBT"], dep, c(s.get("tax_adjustment:", m)),
                         allowances_new.get(m.year, ZERO),
                         D(s.tax.get("qualifying_dep", {}).get(m.isoformat()[:7], "0"))
                         + qualifying_new.get(m, ZERO))  # fmt: skip
        pl["PL.TAX.CURRENT"] = t.get("current", ZERO)
        pl["PL.TAX.DEFERRED"] = t.get("deferred", ZERO)
        pl["PL.TAX"] = pl["PL.TAX.CURRENT"] + pl["PL.TAX.DEFERRED"]
        pl["PL.NET_INCOME"] = pl["PL.PBT"] - pl["PL.TAX"]
        # 4. Working capital and fixed assets.
        bs["BS.AR"] = c(pl["PL.REVENUE"] * s.get("dso:", m) / days)
        bs["BS.INVENTORY"] = c(pl["PL.COGS"] * s.get("dio:", m) / days)
        bs["BS.AP"] = c(pl["PL.COGS"] * s.get("dpo:", m) / days)
        capex = c(s.get("capex:", m))
        bs["BS.PPE.GROSS"] = prev["BS.PPE.GROSS"] + capex
        bs["BS.PPE.ACCDEP"] = prev["BS.PPE.ACCDEP"] - dep
        if tax is not None:
            bs["BS.INCOME_TAX"], bs["BS.DEFERRED_TAX"] = t["income_tax"], t["deferred_tax"]
        # 5. Debt: other debt (repayments capped, current first), then the loans.
        borrowing = c(s.get("borrowing:", m))
        repayment = max(min(c(s.get("repayment:", m)), other_open + borrowing), ZERO)
        from_current = min(repayment, max(other_cur, ZERO))
        other_cur -= from_current
        other_non += borrowing - (repayment - from_current)
        drawn = sum((r.drawdown for r in loans.values()), ZERO)
        repaid = sum((r.principal + r.prepayment for r in loans.values()), ZERO)
        # 6. Equity.
        dividends, issued = c(s.get("dividends:", m)), c(s.get("share_capital:", m))
        bs["BS.EQUITY.SHARE_CAPITAL"] = prev["BS.EQUITY.SHARE_CAPITAL"] + issued
        bs["BS.EQUITY.RETAINED"] = prev["BS.EQUITY.RETAINED"] + pl["PL.NET_INCOME"] - dividends
        # 7. Cash flow statement (indirect).
        paid = t.get("paid", ZERO)
        cf = {"CF.NET_INCOME": pl["PL.NET_INCOME"], "CF.DA": dep,
              "CF.TAX_EXPENSE": pl["PL.TAX"],
              "CF.WC.AR": prev["BS.AR"] - bs["BS.AR"],
              "CF.WC.INVENTORY": prev["BS.INVENTORY"] - bs["BS.INVENTORY"],
              "CF.WC.AP": bs["BS.AP"] - prev["BS.AP"], "CF.TAX_PAID": -paid}  # fmt: skip
        cf["CF.OPERATING"] = sum(cf.values(), ZERO)
        cf["CF.CAPEX"] = -capex
        cf["CF.INVESTING"] = -capex
        cf["CF.BORROWING"] = borrowing + drawn
        cf["CF.REPAYMENT"] = -(repayment + repaid)
        cf["CF.SHARE_CAPITAL"], cf["CF.DIVIDENDS"] = issued, -dividends
        # 8. Cash before the facility, then the facility.
        before = (prev["BS.CASH"] + cf["CF.OPERATING"] + cf["CF.INVESTING"] + cf["CF.BORROWING"]
                  + cf["CF.REPAYMENT"] + issued - dividends)  # fmt: skip
        minimum, limit = c(s.get("minimum_cash:", m)), c(s.get("revolver_limit:", m))
        movement = ZERO
        if before < minimum and limit > revolver:
            movement = min(minimum - before, limit - revolver)
        elif before > minimum and revolver > 0:
            movement = -min(revolver, before - minimum)
        revolver += movement
        cf["CF.REVOLVER"] = movement
        cf["CF.FINANCING"] = (cf["CF.BORROWING"] + cf["CF.REPAYMENT"] + issued - dividends
                              + movement)  # fmt: skip
        cf["CF.NET_CHANGE"] = cf["CF.OPERATING"] + cf["CF.INVESTING"] + cf["CF.FINANCING"]
        cf["CF.OPENING_CASH"] = prev["BS.CASH"]
        cf["CF.CLOSING_CASH"] = prev["BS.CASH"] + cf["CF.NET_CHANGE"]
        # 9. Balance sheet.
        bs["BS.CASH"] = before + movement
        loans_closing = sum((r.closing for r in loans.values()), ZERO)
        loans_current = sum((r.current for r in loans.values()), ZERO)
        bs["BS.DEBT.NONCURRENT"] = other_non + loans_closing - loans_current
        bs["BS.DEBT.CURRENT"] = other_cur + loans_current + revolver
        out.append(Month(m, pl, dict(bs), cf, t, loans))
    return out


# --- the model's own reconciliation --------------------------------------------------------------


def opening_balance_sheet(s: Scenario) -> dict[str, Decimal]:
    bs = {k: c(s.opening.get(k, ZERO)) for k in ASSETS + LIABILITIES + EQUITY}
    if s.split_opening_debt:
        current = sum((opening_current(loan, s.months) for loan in s.loans
                       if loan.get("drawdown_month") is None), ZERO)  # fmt: skip
        total = bs["BS.DEBT.CURRENT"] + bs["BS.DEBT.NONCURRENT"]
        bs["BS.DEBT.CURRENT"], bs["BS.DEBT.NONCURRENT"] = current, total - current
    return bs


def reconcile(s: Scenario, months: list[Month]) -> list[tuple[str, str, bool]]:
    """Month by month: (month, check, holds). The checks of method §4."""
    found = []
    prev = opening_balance_sheet(s)
    for mo in months:
        bs, pl, cf = mo.bs, mo.pl, mo.cf
        tag = mo.month.isoformat()[:7]
        assets = sum((bs[k] for k in ASSETS), ZERO)
        claims = sum((bs[k] for k in LIABILITIES + EQUITY), ZERO)
        debt = bs["BS.DEBT.NONCURRENT"] + bs["BS.DEBT.CURRENT"]
        debt0 = prev["BS.DEBT.NONCURRENT"] + prev["BS.DEBT.CURRENT"]
        checks = {
            "C1 assets = liabilities + equity": assets == claims,
            "C2 cash flow closing cash = balance sheet cash": cf["CF.CLOSING_CASH"] == bs["BS.CASH"]
            and cf["CF.OPENING_CASH"] == prev["BS.CASH"],
            "C3 retained earnings roll forward": bs["BS.EQUITY.RETAINED"]
            == prev["BS.EQUITY.RETAINED"] + pl["PL.NET_INCOME"] + cf["CF.DIVIDENDS"],
            "C4 fixed assets roll forward": bs["BS.PPE.GROSS"] - prev["BS.PPE.GROSS"]
            == -cf["CF.CAPEX"] and bs["BS.PPE.ACCDEP"] - prev["BS.PPE.ACCDEP"] == -cf["CF.DA"],
            "C5 debt roll forward": debt - debt0 == cf["CF.BORROWING"] + cf["CF.REPAYMENT"]
            + cf["CF.REVOLVER"],
            "C6 working capital movements": cf["CF.WC.AR"] == prev["BS.AR"] - bs["BS.AR"]
            and cf["CF.WC.AP"] == bs["BS.AP"] - prev["BS.AP"]
            and cf["CF.WC.INVENTORY"] == prev["BS.INVENTORY"] - bs["BS.INVENTORY"],
            "C7 income tax roll forward": bs["BS.INCOME_TAX"] - prev["BS.INCOME_TAX"]
            == pl["PL.TAX.CURRENT"] + cf["CF.TAX_PAID"]
            and bs["BS.DEFERRED_TAX"] - prev["BS.DEFERRED_TAX"] == pl["PL.TAX.DEFERRED"],
            "C8 each loan rolls forward": all(r.opening + r.drawdown - r.principal - r.prepayment
                                              == r.closing and 0 <= r.current <= r.closing
                                              for r in mo.loans.values()),
            "C9 net income = profit before tax - tax": pl["PL.NET_INCOME"]
            == pl["PL.PBT"] - pl["PL.TAX.CURRENT"] - pl["PL.TAX.DEFERRED"],
        }  # fmt: skip
        if mo.tax.get("losses_before") is not None:
            t = mo.tax
            checks["C10 tax losses roll forward"] = (t["losses_before"] + t["losses_arising"]
                                                     - t["losses_used"] - t["losses_expired"]
                                                     == t["losses_after"])  # fmt: skip
        found += [(tag, name, ok) for name, ok in checks.items()]
        prev = dict(bs)
    return found


def main(argv: list[str]) -> int:
    s = load(argv[1])
    months = run(s)
    for mo in months:
        print(mo.month.isoformat()[:7], " ".join(f"{k}={v}" for k, v in
                                                {**mo.pl, **mo.bs, **mo.cf}.items()))  # fmt: skip
    failed = [r for r in reconcile(s, months) if not r[2]]
    print(f"{s.name}: {len(months)} months; reconciliation failures: {len(failed)}")
    for tag, name, _ in failed:
        print("  FAILED", tag, name)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
