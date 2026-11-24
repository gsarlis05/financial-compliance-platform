"""The three-statement engine (M6-3, AC-PJ1, AC-PJ2, AC-PJ3, AC-PJ6), pure: no database.

Every expected figure is worked out by hand in the comments; the property tests check the six
invariants of doc 10 §4.2 for random assumption sets and opening balance sheets."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.modules.calendar.api import add_months
from fcp.modules.projections import engine
from fcp.modules.projections.drivers import OPEX_LINES, REVENUE_LINES
from fcp.modules.projections.engine import EngineInput, project
from fcp.modules.projections.tax import TaxInputs, TaxYearRule

D = Decimal
JAN = date(2027, 1, 1)
FEB = date(2027, 2, 1)
OPENING = {  # assets 25,000 = liabilities 9,000 + equity 16,000
    "BS.CASH": D(10000), "BS.AR": D(5000), "BS.PPE.GROSS": D(12000), "BS.PPE.ACCDEP": D(-2000),
    "BS.AP": D(3000), "BS.DEBT.NONCURRENT": D(6000),
    "BS.EQUITY.SHARE_CAPITAL": D(1000), "BS.EQUITY.RETAINED": D(15000),
}  # fmt: skip


def rules(rate: str, years: range = range(2025, 2031), carry: int = 7) -> TaxInputs:
    """Cyprus-like rules for tests: instalments of half on 31 July and 31 December, the balance
    by 1 August of the next year."""
    return TaxInputs(rules={
        y: TaxYearRule(y, D(rate), carry, ((date(y, 7, 31), D("0.5")), (date(y, 12, 31), D("0.5"))),
                       date(y + 1, 8, 1), f"TEST:{y}", False)
        for y in years
    })  # fmt: skip


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
        ("dso", ""): flat(30, months),
        ("dio", ""): flat(31, months),
        ("dpo", ""): flat(15, months),
        ("repayment", ""): {JAN: D(1000)},
        ("dividends", ""): {JAN: D(500)},
        ("minimum_cash", ""): flat(1000, months),
        ("revolver_limit", ""): flat(50000, months),
    }
    return EngineInput("set-1", date(2026, 12, 31), months, OPENING, drivers,
                       {JAN: D(200), FEB: D(200)}, {JAN}, tax=rules("0.125"))  # fmt: skip


def test_one_month_by_hand() -> None:
    p = project(hand_input())
    jan = p.months[0]
    # Revenue 31,000; cost of sales 31,000 x 60% = 18,600; operating costs 7,000; depreciation
    # 200 (the capex is depreciated from February); interest 6,000 x 6% / 12 = 30. Tax (M6F-5):
    # taxable = profit before tax 5,170 + depreciation added back 200 (no capital allowances) =
    # 5,370; 12.5% = 671.25, all current tax (no deferred tax without allowances).
    assert {k: jan.pl[k] for k in ("PL.REVENUE", "PL.COGS", "PL.OPEX", "PL.EBITDA", "PL.DA",
                                   "PL.INTEREST", "PL.PBT", "PL.TAX", "PL.NET_INCOME")} == {
        "PL.REVENUE": D(31000), "PL.COGS": D(18600), "PL.OPEX": D(7000), "PL.EBITDA": D(5400),
        "PL.DA": D(200), "PL.INTEREST": D(30), "PL.PBT": D(5170), "PL.TAX": D("671.25"),
        "PL.NET_INCOME": D("4498.75"),
    }  # fmt: skip
    # Receivables 31,000 x 30 / 31 = 30,000; stock 18,600 x 31 / 31; payables 18,600 x 15 / 31.
    assert (jan.bs["BS.AR"], jan.bs["BS.INVENTORY"], jan.bs["BS.AP"]) == (
        D(30000),
        D(18600),
        D(9000),
    )
    # Operating cash 4,498.75 + 200 + 671.25 (tax added back, none paid) - 25,000 - 18,600 + 6,000
    # = -32,230; capex 6,000;
    # repayment 1,000 and dividends 500: 10,000 - 39,730 = -29,730, so the facility draws
    # 30,730 to keep the minimum cash of 1,000.
    assert jan.cf["CF.OPERATING"] == D(-32230)
    assert jan.cf["CF.REVOLVER"] == D(30730)
    assert jan.bs["BS.CASH"] == jan.cf["CF.CLOSING_CASH"] == D(1000)
    assert jan.bs["BS.DEBT.NONCURRENT"] == D(5000)  # no current term debt: the rest is repaid
    assert jan.bs["BS.DEBT.CURRENT"] == D(30730)  # the facility
    assert jan.bs["BS.EQUITY.RETAINED"] == D("18998.75")  # 15,000 + 4,498.75 - 500
    assert (jan.bs["BS.INCOME_TAX"], jan.cf["CF.TAX_PAID"]) == (D("671.25"), D(0))
    assert (jan.bs["BS.PPE.GROSS"], jan.bs["BS.PPE.ACCDEP"]) == (D(18000), D(-2200))
    assets, liabilities, equity = engine.totals(jan.bs)
    assert (assets, liabilities, equity) == (D(65400), D("45401.25"), D("19998.75"))

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


def test_capped_repayment_and_tax_payments() -> None:
    months = [date(2027, 12, 1), date(2028, 1, 1)]
    drivers = {
        ("revenue", "REV.SERVICES"): flat(1000, months),
        ("gross_margin", ""): flat(100, months),
        ("repayment", ""): flat(4000, months),
    }
    opening = {"BS.CASH": D(10000), "BS.DEBT.CURRENT": D(2500), "BS.DEBT.NONCURRENT": D(1000),
               "BS.INCOME_TAX": D(50), "BS.EQUITY.RETAINED": D(6450)}  # fmt: skip
    inp = EngineInput("s", date(2027, 11, 30), months, opening, drivers, {}, {months[1]},
                      tax=rules("0.10"))  # fmt: skip
    p = project(inp)
    dec, jan = p.months
    # December: 3,500 owed, so the repayment is capped at 3,500.
    assert dec.cf["CF.REPAYMENT"] == D(-3500)
    assert dec.bs["BS.DEBT.CURRENT"] == dec.bs["BS.DEBT.NONCURRENT"] == 0
    assert "2027-12: repayment capped at the other debt owed (3500.00)." in p.notes
    # Tax: the 50 owed for earlier years is overdue (its 1 August 2027 date has passed), so it is
    # paid in December; December's tax 1,000 x 10% = 100 is accrued and, on 31 December, the
    # second instalment brings 2027's provisional tax to the year's 100: paid 150 in all.
    assert (dec.pl["PL.TAX"], dec.cf["CF.TAX_PAID"], dec.bs["BS.INCOME_TAX"]) == (
        D(100), D(-150), D(0))  # fmt: skip
    # January 2028: 100 accrued, nothing due until 31 July.
    assert (jan.pl["PL.TAX"], jan.cf["CF.TAX_PAID"], jan.bs["BS.INCOME_TAX"]) == (
        D(100), D(0), D(100))  # fmt: skip
    assert jan.cf["CF.REPAYMENT"] == 0
    assert all(p.invariants.values()), p.invariants


def test_golden_24_months() -> None:
    """AC-PJ3: 24 months for a Demo Trading-like company, checked against figures worked out by
    hand (closed forms below). Professional sign-off is an owner item (#153)."""
    months = [add_months(JAN, n) for n in range(24)]
    drivers = {
        ("revenue", "REV.SALES"): flat(20000, months),
        ("revenue", "REV.OTHER"): flat(500, months),
        ("gross_margin", ""): flat(45, months),
        ("opex", "OPEX.PAYROLL"): flat(4000, months),
        ("opex", "OPEX.RENT"): flat(1200, months),
        ("capex", ""): {date(2027, 6, 1): D(12000)},
        ("capex_life", ""): flat(48, months),
        ("interest_rate", ""): flat(6, months),
        ("repayment", ""): flat(250, months),
        ("dso", ""): flat(30, months),
        ("dpo", ""): flat(30, months),
        ("dividends", ""): {date(2028, 6, 1): D(20000)},
    }
    opening = {"BS.CASH": D(30000), "BS.AR": D(18000), "BS.PPE.GROSS": D(24000),
               "BS.PPE.ACCDEP": D(-6000), "BS.AP": D(10000), "BS.DEBT.NONCURRENT": D(12000),
               "BS.INCOME_TAX": D(3000), "BS.EQUITY.SHARE_CAPITAL": D(5000),
               "BS.EQUITY.RETAINED": D(36000)}  # fmt: skip
    register = flat(400, months[:15])  # the registered assets are fully depreciated in 2028-03
    starts = {JAN, date(2028, 1, 1)}
    p = project(EngineInput("golden", date(2026, 12, 31), months, opening, drivers, register,
                            starts, tax=rules("0.125")))  # fmt: skip
    assert all(p.invariants.values()), {k: v for k, v in p.invariants.items() if not v}
    by = {m.month: m for m in p.months}
    # Every month: revenue 20,500; cost of sales 20,000 x 55% = 11,000; EBITDA 20,500 - 11,000 -
    # 5,200 = 4,300. New capex 12,000 / 48 = 250 a month from July 2027.
    # Debt n months in (opening of the month) = 12,000 - 250 n; interest = that x 0.5%.
    # Taxable profit of a month = profit before tax + depreciation (no capital allowances) =
    # 4,300 - interest; tax to date = 12.5% of the year's taxable profit to date, rounded once.
    for year in (2027, 2028):
        taxable = D(0)
        before = D(0)
        for n, m in enumerate(months):
            if m.year != year:
                continue
            dep = (D(400) if n < 15 else 0) + (D(250) if m >= date(2027, 7, 1) else 0)
            interest = ((D(12000) - 250 * n) * D("0.005")).quantize(D("0.01"))
            assert by[m].pl["PL.EBITDA"] == D(4300)
            assert by[m].pl["PL.INTEREST"] == interest, m
            assert by[m].pl["PL.DA"] == dep, m
            taxable += D(4300) - interest
            to_date = (taxable * D("0.125")).quantize(D("0.01"), ROUND_HALF_UP)
            assert by[m].pl["PL.TAX"] == to_date - before, m
            assert by[m].pl["PL.TAX.DEFERRED"] == 0  # no allowances: no temporary difference
            before = to_date
    # Interest over 24 months: 0.5% x (24 x 12,000 - 250 x (0 + ... + 23)) = 0.5% x 219,000.
    assert sum((m.pl["PL.INTEREST"] for m in p.months), D(0)) == D(1095)
    # Taxable 2027 = 12 x 4,300 - 0.5% x (12 x 12,000 - 250 x 66) = 51,600 - 637.50 = 50,962.50;
    # tax 6,370.3125 -> 6,370.31. 2028: 51,600 - 0.5% x (144,000 - 250 x 210) = 51,142.50;
    # tax 6,392.8125 -> 6,392.81.
    tax_2027 = sum((m.pl["PL.TAX"] for m in p.months[:12]), D(0))
    tax_2028 = sum((m.pl["PL.TAX"] for m in p.months[12:]), D(0))
    assert (tax_2027, tax_2028) == (D("6370.31"), D("6392.81"))
    # Profit before tax: 24 x 4,300 - depreciation (15 x 400 + 18 x 250 = 10,500) - 1,095 = 91,605.
    total_ni = sum((m.pl["PL.NET_INCOME"] for m in p.months), D(0))
    assert total_ni == D(91605) - tax_2027 - tax_2028
    # Payments. July 2027: taxable to date 7 x 4,300 - 0.5% x (84,000 - 250 x 21) = 29,706.25;
    # tax to date 3,713.28; annualised x 12/7, half: 3,182.81. December 2027: the year's 6,370.31
    # less 3,182.81 = 3,187.50. The opening 3,000 (2026) on 1 August 2027. 2027's final balance
    # (1 August 2028) is nil. July 2028: 30,100 - 0.5% x (84,000 - 250 x 105) = 29,811.25; tax to
    # date 3,726.41; x 12/7 / 2 = 3,194.07. December 2028: 6,392.81 - 3,194.07 = 3,198.74.
    paid = {m.month: -m.cf["CF.TAX_PAID"] for m in p.months if m.cf["CF.TAX_PAID"]}
    assert paid == {date(2027, 7, 1): D("3182.81"), date(2027, 8, 1): D(3000),
                    date(2027, 12, 1): D("3187.50"), date(2028, 7, 1): D("3194.07"),
                    date(2028, 12, 1): D("3198.74")}  # fmt: skip
    last = p.months[-1]
    assert last.bs["BS.INCOME_TAX"] == 0  # every year's tax paid by its instalments
    # Retained earnings: 36,000 + net income - 20,000 dividends.
    assert last.bs["BS.EQUITY.RETAINED"] == D(16000) + total_ni
    # Receivables 20,500 x 30 / 31 in December 2028; payables 11,000 x 30 / 31.
    assert last.bs["BS.AR"] == D("19838.71")
    assert last.bs["BS.AP"] == D("10645.16")
    assert last.bs["BS.DEBT.NONCURRENT"] == D(6000)  # 12,000 - 24 x 250
    assert last.bs["BS.PPE.GROSS"] == D(36000)
    assert last.bs["BS.PPE.ACCDEP"] == D(-16500)  # 6,000 + 10,500
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
    for key in ("gross_margin", "interest_rate", "revolver_rate", "capex_allowance_rate"):
        drivers[(key, "")] = series(percent)
    drivers[("tax_adjustment", "")] = series(st.decimals(min_value=-(10**5), max_value=10**5,
                                                         places=2))  # fmt: skip
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
    return EngineInput("prop", add_months(start, -1), months, opening, drivers, register, starts,
                       tax=draw(tax_inputs(months)))  # fmt: skip


@st.composite
def tax_inputs(draw: st.DrawFn, months: list[date]) -> TaxInputs:
    """Random rules for every year from 2018, random losses brought forward (2019-2026), actual
    figures to the cut-over, allowances, qualifying depreciation and the loss-asset choice."""
    amount = st.decimals(min_value=0, max_value=10**6, places=2)
    rules = {
        y: TaxYearRule(
            y, draw(st.decimals(min_value=0, max_value=D("0.35"), places=4)),
            draw(st.integers(0, 10)),
            ((date(y, 7, 31), D("0.5")), (date(y, 12, 31), D("0.5"))),
            date(y + 1, draw(st.integers(1, 12)), 1), f"P:{y}", draw(st.booleans()),
        )
        for y in range(2018, 2032)
    }  # fmt: skip
    return TaxInputs(
        rules=rules,
        losses_bf={y: draw(amount) for y in range(2019, 2027) if draw(st.booleans())},
        ytd_pbt=draw(st.decimals(min_value=-(10**6), max_value=10**6, places=2)),
        ytd_da=draw(amount), ytd_tax=draw(amount), paid_ytd=draw(amount),
        allowances={y: draw(amount) for y in range(2027, 2030) if draw(st.booleans())},
        qualifying_dep={m: draw(amount) for m in months if draw(st.booleans())},
        recognise_loss_dta=draw(st.booleans()),
    )  # fmt: skip


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


def test_new_capex_commencement_and_method() -> None:
    """M6F-3 (#148): new capex depreciation starts ``capex_start`` months after it is spent (the
    default 1 keeps the earlier behaviour) and may be declining balance."""
    months = [add_months(JAN, n) for n in range(4)]
    base = {("capex", ""): {JAN: D(12000)}, ("capex_life", ""): flat(12, months)}

    def da(drivers: dict[tuple[str, str], dict[date, Decimal]]) -> list[Decimal]:
        inp = EngineInput("c", date(2026, 12, 31), months, {"BS.CASH": D(20000),
                          "BS.EQUITY.SHARE_CAPITAL": D(20000)}, drivers, {}, set())  # fmt: skip
        p = project(inp)
        assert all(p.invariants.values()), p.invariants
        return [m.pl["PL.DA"] for m in p.months]

    assert da(base) == [0, D(1000), D(1000), D(1000)]  # no capex_start row: the month after
    assert da({**base, ("capex_start", ""): flat(0, months)}) == [D(1000)] * 4
    assert da({**base, ("capex_start", ""): flat(2, months)}) == [0, 0, D(1000), D(1000)]
    # Declining balance 24% a year from the month after: 12,000 x 2% = 240; 11,760 x 2% = 235.20.
    db = da({**base, ("capex_db_rate", ""): flat(24, months)})
    assert db[:3] == [0, D(240), D("235.20")]
