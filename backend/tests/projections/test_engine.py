"""The three-statement engine (M6-3, AC-PJ1, AC-PJ2, AC-PJ3, AC-PJ6), pure: no database.

Every expected figure is worked out by hand in the comments; the property tests check the six
invariants of doc 10 §4.2 for random assumption sets and opening balance sheets."""

from datetime import date
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.modules.calendar.api import add_months
from fcp.modules.projections import engine
from fcp.modules.projections.drivers import OPEX_LINES, REVENUE_LINES
from fcp.modules.projections.engine import EngineInput, project

D = Decimal
JAN = date(2027, 1, 1)
FEB = date(2027, 2, 1)
OPENING = {  # assets 25,000 = liabilities 9,000 + equity 16,000
    "BS.CASH": D(10000), "BS.AR": D(5000), "BS.PPE.GROSS": D(12000), "BS.PPE.ACCDEP": D(-2000),
    "BS.AP": D(3000), "BS.DEBT.NONCURRENT": D(6000),
    "BS.EQUITY.SHARE_CAPITAL": D(1000), "BS.EQUITY.RETAINED": D(15000),
}  # fmt: skip


def flat(value: str | int, months: list[date]) -> dict[date, Decimal]:
    return dict.fromkeys(months, D(value))


def hand_input() -> EngineInput:
    months = [JAN, FEB]
    drivers = {
        ("revenue", "REV.SALES"): flat(31000, months),
        ("gross_margin", ""): flat(40, months),
        ("opex", "OPEX.RENT"): flat(2000, months),
        ("opex", "OPEX.PAYROLL"): flat(5000, months),
        ("capex", ""): {JAN: D(6000)},
        ("capex_life", ""): flat(60, months),
        ("interest_rate", ""): flat(6, months),
        ("revolver_rate", ""): flat(12, months),
        ("tax_rate", ""): flat("12.5", months),
        ("dso", ""): flat(30, months),
        ("dio", ""): flat(31, months),
        ("dpo", ""): flat(15, months),
        ("repayment", ""): {JAN: D(1000)},
        ("dividends", ""): {JAN: D(500)},
        ("minimum_cash", ""): flat(1000, months),
        ("revolver_limit", ""): flat(50000, months),
    }
    return EngineInput("set-1", date(2026, 12, 31), months, OPENING, drivers,
                       {JAN: D(200), FEB: D(200)}, {JAN})  # fmt: skip


def test_one_month_by_hand() -> None:
    p = project(hand_input())
    jan = p.months[0]
    # Revenue 31,000; cost of sales 31,000 x 60% = 18,600; operating costs 7,000; depreciation
    # 200 (the capex is depreciated from February); interest 6,000 x 6% / 12 = 30;
    # tax (5,400 - 200 - 30) x 12.5% = 646.25.
    assert {k: jan.pl[k] for k in ("PL.REVENUE", "PL.COGS", "PL.OPEX", "PL.EBITDA", "PL.DA",
                                   "PL.INTEREST", "PL.PBT", "PL.TAX", "PL.NET_INCOME")} == {
        "PL.REVENUE": D(31000), "PL.COGS": D(18600), "PL.OPEX": D(7000), "PL.EBITDA": D(5400),
        "PL.DA": D(200), "PL.INTEREST": D(30), "PL.PBT": D(5170), "PL.TAX": D("646.25"),
        "PL.NET_INCOME": D("4523.75"),
    }  # fmt: skip
    # Receivables 31,000 x 30 / 31 = 30,000; stock 18,600 x 31 / 31; payables 18,600 x 15 / 31.
    assert (jan.bs["BS.AR"], jan.bs["BS.INVENTORY"], jan.bs["BS.AP"]) == (
        D(30000),
        D(18600),
        D(9000),
    )
    # Operating cash 4,523.75 + 200 - 25,000 - 18,600 + 6,000 + 646.25 = -32,230; capex 6,000;
    # repayment 1,000 and dividends 500: 10,000 - 39,730 = -29,730, so the facility draws
    # 30,730 to keep the minimum cash of 1,000.
    assert jan.cf["CF.OPERATING"] == D(-32230)
    assert jan.cf["CF.REVOLVER"] == D(30730)
    assert jan.bs["BS.CASH"] == jan.cf["CF.CLOSING_CASH"] == D(1000)
    assert jan.bs["BS.DEBT.NONCURRENT"] == D(5000)  # no current term debt: the rest is repaid
    assert jan.bs["BS.DEBT.CURRENT"] == D(30730)  # the facility
    assert jan.bs["BS.EQUITY.RETAINED"] == D("19023.75")  # 15,000 + 4,523.75 - 500
    assert jan.bs["BS.TAX_PAY"] == D("646.25")
    assert (jan.bs["BS.PPE.GROSS"], jan.bs["BS.PPE.ACCDEP"]) == (D(18000), D(-2200))
    assets, liabilities, equity = engine.totals(jan.bs)
    assert (assets, liabilities, equity) == (D(65400), D("45376.25"), D("20023.75"))

    feb = p.months[1]
    # Depreciation 200 + 6,000 / 60 = 300; interest 5,000 x 6% / 12 = 25 plus 30,730 x 12% / 12
    # = 307.30 on the facility drawn at the start of the month.
    assert (feb.pl["PL.DA"], feb.pl["PL.INTEREST"]) == (D(300), D("332.30"))
    assert all(p.invariants.values()), p.invariants
    assert p.opening == {line: OPENING.get(line, D("0.00")) for line in engine.BS_LINES}  # PJ2


def test_a_broken_statement_fails_and_says_where() -> None:
    inp = hand_input()
    p = project(inp)
    p.months[1].bs["BS.CASH"] += D("0.01")
    found = engine.check(p, inp)
    assert found["balance_sheet_balances"] is False
    assert found["cash_ties"] is False
    assert found["balance_sheet_balances@2027-02"] is False
    assert found["cash_ties@2027-02"] is False
    assert "balance_sheet_balances@2027-01" not in found
    assert found["retained_earnings_roll"] is True


def test_capped_repayment_and_tax_paid_in_the_new_year() -> None:
    months = [date(2027, 12, 1), date(2028, 1, 1)]
    drivers = {
        ("revenue", "REV.SERVICES"): flat(1000, months),
        ("gross_margin", ""): flat(100, months),
        ("tax_rate", ""): flat(10, months),
        ("repayment", ""): flat(4000, months),
    }
    opening = {"BS.CASH": D(10000), "BS.DEBT.CURRENT": D(2500), "BS.DEBT.NONCURRENT": D(1000),
               "BS.TAX_PAY": D(50), "BS.EQUITY.RETAINED": D(6450)}  # fmt: skip
    inp = EngineInput("s", date(2027, 11, 30), months, opening, drivers, {}, {months[1]})
    p = project(inp)
    dec, jan = p.months
    # December: tax 100 accrued, nothing paid; 3,500 owed, so the repayment is capped at 3,500.
    assert (dec.bs["BS.TAX_PAY"], dec.cf["CF.REPAYMENT"]) == (D(150), D(-3500))
    assert dec.bs["BS.DEBT.CURRENT"] == dec.bs["BS.DEBT.NONCURRENT"] == 0
    assert "2027-12: repayment capped at the debt owed (3500.00)." in p.notes
    # January starts a fiscal year: the 150 owed is paid and January's 100 accrued.
    assert jan.bs["BS.TAX_PAY"] == D(100)
    assert jan.cf["CF.WC.TAX"] == D(-50)
    assert jan.cf["CF.REPAYMENT"] == 0
    assert all(p.invariants.values()), p.invariants


def test_golden_24_months() -> None:
    """AC-PJ3: 24 months for a Demo Trading-like company, checked against figures worked out by
    hand (closed forms below). Professional sign-off is an owner item."""
    months = [add_months(JAN, n) for n in range(24)]
    drivers = {
        ("revenue", "REV.SALES"): flat(20000, months),
        ("revenue", "REV.OTHER"): flat(500, months),
        ("gross_margin", ""): flat(45, months),
        ("opex", "OPEX.PAYROLL"): flat(4000, months),
        ("opex", "OPEX.RENT"): flat(1200, months),
        ("capex", ""): {date(2027, 6, 1): D(12000)},
        ("capex_life", ""): flat(48, months),
        ("tax_rate", ""): flat("12.5", months),
        ("interest_rate", ""): flat(6, months),
        ("repayment", ""): flat(250, months),
        ("dso", ""): flat(30, months),
        ("dpo", ""): flat(30, months),
        ("dividends", ""): {date(2028, 6, 1): D(20000)},
    }
    opening = {"BS.CASH": D(30000), "BS.AR": D(18000), "BS.PPE.GROSS": D(24000),
               "BS.PPE.ACCDEP": D(-6000), "BS.AP": D(10000), "BS.DEBT.NONCURRENT": D(12000),
               "BS.TAX_PAY": D(3000), "BS.EQUITY.SHARE_CAPITAL": D(5000),
               "BS.EQUITY.RETAINED": D(36000)}  # fmt: skip
    register = flat(400, months[:15])  # the registered assets are fully depreciated in 2028-03
    starts = {JAN, date(2028, 1, 1)}
    p = project(EngineInput("golden", date(2026, 12, 31), months, opening, drivers, register,
                            starts))  # fmt: skip
    assert all(p.invariants.values()), {k: v for k, v in p.invariants.items() if not v}
    by = {m.month: m for m in p.months}
    # Every month: revenue 20,500; cost of sales 20,000 x 55% = 11,000; EBITDA 20,500 - 11,000 -
    # 5,200 = 4,300. New capex 12,000 / 48 = 250 a month from July 2027.
    # Debt n months in (opening of the month) = 12,000 - 250 n; interest = that x 0.5%.
    for n, m in enumerate(months):
        dep = (D(400) if n < 15 else 0) + (D(250) if m >= date(2027, 7, 1) else 0)
        interest = ((D(12000) - 250 * n) * D("0.005")).quantize(D("0.01"))
        pbt = D(4300) - dep - interest
        assert by[m].pl["PL.EBITDA"] == D(4300)
        assert by[m].pl["PL.INTEREST"] == interest, m
        assert by[m].pl["PL.TAX"] == (pbt * D("0.125")).quantize(D("0.01")), m
    # Interest over 24 months: 0.5% x (24 x 12,000 - 250 x (0 + ... + 23)) = 0.5% x 219,000.
    assert sum((m.pl["PL.INTEREST"] for m in p.months), D(0)) == D(1095)
    # Depreciation: 15 x 400 + 18 x 250 = 10,500. Profit before tax: 24 x 4,300 - 10,500 - 1,095
    # = 91,605; tax 12.5% = 11,450.625, rounded per month (no month has a half cent: see below).
    total_tax = sum((m.pl["PL.TAX"] for m in p.months), D(0))
    total_ni = sum((m.pl["PL.NET_INCOME"] for m in p.months), D(0))
    assert total_ni == D(91605) - total_tax
    assert abs(total_tax - D("11450.625")) <= D("0.12")  # 24 roundings of at most half a cent
    last = p.months[-1]
    # Retained earnings: 36,000 + net income - 20,000 dividends.
    assert last.bs["BS.EQUITY.RETAINED"] == D(16000) + total_ni
    # Receivables 20,500 x 30 / 31 in December 2028; payables 11,000 x 30 / 31.
    assert last.bs["BS.AR"] == D("19838.71")
    assert last.bs["BS.AP"] == D("10645.16")
    assert last.bs["BS.DEBT.NONCURRENT"] == D(6000)  # 12,000 - 24 x 250
    assert last.bs["BS.PPE.GROSS"] == D(36000)
    assert last.bs["BS.PPE.ACCDEP"] == D(-16500)  # 6,000 + 10,500
    # Tax payable at the end: 2028's tax (2027's was paid in January 2028, the opening 3,000 in
    # January 2027).
    tax_2028 = sum((m.pl["PL.TAX"] for m in p.months[12:]), D(0))
    assert last.bs["BS.TAX_PAY"] == tax_2028
    # Cash, independently of the cash flow statement: from the balance-sheet identity.
    _, liabilities, equity = engine.totals(last.bs)
    others = sum((last.bs[x] for x in engine.ASSETS if x != "BS.CASH"), D(0))
    assert last.bs["BS.CASH"] == liabilities + equity - others
    # Year and quarter totals are sums of their months (doc 10 §4.2 (6)).
    years = engine.aggregate(p, 12)
    assert [y[2]["PL.REVENUE"] for y in years] == [D(246000), D(246000)]
    assert years[1][2]["CF.CLOSING_CASH"] == last.bs["BS.CASH"]
    quarters = engine.aggregate(p, 3)
    assert len(quarters) == 8
    assert sum((q[2]["PL.NET_INCOME"] for q in quarters), D(0)) == total_ni


money = st.decimals(min_value=0, max_value=10**7, places=2, allow_nan=False, allow_infinity=False)
percent = st.decimals(min_value=-50, max_value=100, places=4, allow_nan=False,
                      allow_infinity=False)  # fmt: skip
days = st.integers(min_value=0, max_value=120)


@st.composite
def projections(draw: st.DrawFn) -> EngineInput:
    n = draw(st.integers(min_value=1, max_value=24))
    start = date(2027, draw(st.integers(min_value=1, max_value=12)), 1)
    months = [add_months(start, i) for i in range(n)]

    def series(values: st.SearchStrategy[Decimal]) -> dict[date, Decimal]:
        return {m: draw(values) for m in months}

    drivers: dict[tuple[str, str], dict[date, Decimal]] = {
        ("revenue", line): series(money) for line in REVENUE_LINES
    }
    drivers |= {("opex", line): series(money) for line in OPEX_LINES[:3]}
    for key in ("capex", "borrowing", "repayment", "dividends", "share_capital", "minimum_cash",
                "revolver_limit"):  # fmt: skip
        drivers[(key, "")] = series(money)
    for key in ("gross_margin", "tax_rate", "interest_rate", "revolver_rate"):
        drivers[(key, "")] = series(percent)
    for key in ("dso", "dio", "dpo"):
        drivers[(key, "")] = {m: D(draw(days)) for m in months}
    drivers[("capex_life", "")] = {m: D(draw(st.integers(1, 120))) for m in months}
    opening = {line: draw(money) for line in engine.ASSETS if line != "BS.PPE.ACCDEP"}
    opening["BS.PPE.ACCDEP"] = -draw(money)
    for line in engine.LIABILITIES + engine.EQUITY[:-1]:
        opening[line] = draw(money)
    assets = sum((opening[x] for x in engine.ASSETS), D(0))
    others = sum((opening[x] for x in engine.LIABILITIES + engine.EQUITY[:-1]), D(0))
    opening["BS.EQUITY.RETAINED"] = assets - others  # balanced, possibly negative
    register = series(st.decimals(min_value=0, max_value=10**5, places=2, allow_nan=False,
                                  allow_infinity=False))  # fmt: skip
    starts = {m for m in months if m.month == draw(st.integers(1, 12))}
    return EngineInput("prop", add_months(start, -1), months, opening, drivers, register, starts)


@settings(max_examples=150, deadline=None)
@given(projections())
def test_every_valid_assumption_set_satisfies_the_six_invariants(inp: EngineInput) -> None:
    """AC-PJ1: exact, with no plug line, for any drivers and any balanced opening."""
    p = project(inp)
    assert all(p.invariants.values()), {k: v for k, v in p.invariants.items() if not v}
    assert set(engine.INVARIANTS) <= set(p.invariants)
    for m in p.months:
        assert all(v == v.quantize(D("0.01")) for v in (*m.pl.values(), *m.bs.values()))
    _, out = engine.output(inp)
    assert all(v.nature.value in ("ACTUAL", "FORECAST") for v in out.values)
    assert out.digest() == engine.output(inp)[1].digest()  # deterministic
