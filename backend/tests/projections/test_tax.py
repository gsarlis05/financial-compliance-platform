"""Corporate tax in projections (M6F-5, #150; owner decision D4). The tax book is stepped month
by month as the engine does; every figure is worked out by hand in the comments."""

from datetime import date
from decimal import Decimal

from fcp.modules.calendar.api import add_months
from fcp.modules.projections.tax import TaxBook, TaxInputs, TaxMonth, TaxYearRule

D = Decimal


def rule(year: int, rate: str, carry: int) -> TaxYearRule:
    return TaxYearRule(year, D(rate), carry,
                       ((date(year, 7, 31), D("0.5")), (date(year, 12, 31), D("0.5"))),
                       date(year + 1, 8, 1), f"CY:{year}", False)  # fmt: skip


# Cyprus-like (pending verification): 12.5% and 5 years to 2025; 15% and 7 years from 2026.
RULES = {y: rule(y, "0.125" if y <= 2025 else "0.15", 5 if y <= 2025 else 7)
         for y in range(2019, 2036)}  # fmt: skip


ZERO = D(0)


def run(inputs: TaxInputs, pbt_by_year: dict[int, Decimal], *, start: date = date(2026, 1, 1),
        cutover: date = date(2025, 12, 31), opening: Decimal = ZERO,
        qualifying: Decimal = ZERO) -> list[TaxMonth]:  # fmt: skip
    """Step the book with each year's profit spread evenly over its months (no depreciation)."""
    book = TaxBook(inputs, cutover, start, opening, D(0))
    out = []
    month = start
    while month.year in pbt_by_year:
        per_month = pbt_by_year[month.year] / 12
        out.append(book.step(month, pbt=per_month, da=D(0), adjustment=D(0), new_allowances=D(0),
                             qualifying_dep=qualifying))  # fmt: skip
        month = add_months(month, 1)
    return out


def test_rate_change_losses_and_their_use() -> None:
    # 2026: a loss of 120,000; 2027: profit 50,000 (all covered by the loss, no tax); 2028: profit
    # 100,000, of which the remaining 70,000 of loss is used: tax 15% x 30,000 = 4,500.
    months = run(TaxInputs(rules=RULES), {2026: D(-120000), 2027: D(50000), 2028: D(100000)})
    dec26, dec27, dec28 = months[11], months[23], months[35]
    assert (dec26.losses_arising, dec26.losses_available) == (D(120000), D(120000))
    assert sum(m.current for m in months[12:24]) == 0
    assert (dec27.losses_used, dec27.losses_available) == (D(50000), D(70000))
    assert sum(m.current for m in months[24:36]) == D(4500)
    assert (dec28.losses_used, dec28.losses_available) == (D(70000), D(0))
    # Year to date: by June 2028 the profit to date 50,000 is all covered by the 70,000 of loss.
    assert months[29].current == 0
    assert months[29].taxable_ytd == D(50000)
    # 2025 profit taxed at 12.5% (the rule of 2025), 2026 at 15%.
    two = run(TaxInputs(rules=RULES), {2025: D(12000), 2026: D(12000)}, start=date(2025, 1, 1),
              cutover=date(2024, 12, 31))  # fmt: skip
    assert sum(m.current for m in two[:12]) == D(1500)
    assert sum(m.current for m in two[12:]) == D(1800)


def test_losses_expire_by_the_rule_of_the_year_they_arose() -> None:
    # A 2020 loss of 10,000 (5 years: usable 2021-2025) is unused at the start of 2026: expired.
    # A 2022 loss of 8,000 (usable to 2027) covers part of the 2026 profit of 20,000: tax 15% x
    # 12,000 = 1,800. Both are in the pool brought forward.
    inputs = TaxInputs(rules=RULES, losses_bf={2020: D(10000), 2022: D(8000)})
    months = run(inputs, {2026: D(20000)})
    dec = months[11]
    assert sum(m.current for m in months) == D(1800)
    assert (dec.losses_used, dec.losses_expired, dec.losses_available) == (D(8000), D(10000),
                                                                           D(0))  # fmt: skip
    assert dec.pool_before + dec.losses_arising - dec.losses_used - dec.losses_expired == (
        dec.pool_after)  # fmt: skip


def test_instalments_final_payment_and_the_opening_balance() -> None:
    # 2026 profit 24,000 (2,000 a month), 15%: tax 3,600. July: tax to date 7 x 2,000 x 15% =
    # 2,100; annualised 3,600; half = 1,800. December: the year's 3,600 less 1,800 = 1,800.
    # The opening 500 owed for 2025 is paid on 1 August 2026 (2025's final date).
    months = run(TaxInputs(rules=RULES), {2026: D(24000), 2027: D(0)}, opening=D(500))
    paid = {(m.year, i + 1): m.payments for i, m in enumerate(months) if m.payments}
    assert [(p.kind, p.amount) for p in paid[(2026, 7)]] == [("PROVISIONAL", D(1800))]
    assert [(p.kind, p.amount) for p in paid[(2026, 8)]] == [("PRIOR", D(500))]
    assert [(p.kind, p.amount) for p in paid[(2026, 12)]] == [("PROVISIONAL", D(1800))]
    assert months[11].income_tax == 0
    # A profit that falls after July: the July instalment (on the year to date) was too high and
    # the final payment on 1 August 2027 is a refund.
    drop = TaxBook(TaxInputs(rules=RULES), date(2025, 12, 31), date(2026, 1, 1), D(0), D(0))
    steps = [drop.step(add_months(date(2026, 1, 1), n), pbt=D(2000) if n < 7 else D(-2400),
                       da=D(0), adjustment=D(0), new_allowances=D(0), qualifying_dep=D(0))
             for n in range(20)]  # fmt: skip
    # Year: 7 x 2,000 - 5 x 2,400 = 2,000; tax 300. July paid 1,800; December nothing (never a
    # negative instalment); 1 August 2027 refunds 1,500.
    assert sum(s.current for s in steps[:12]) == D(300)
    final = [p for s in steps for p in s.payments if p.kind == "FINAL"]
    assert [(p.year, p.amount) for p in final] == [(2026, D(-1500))]


def test_the_cut_over_year_counts_the_actual_months() -> None:
    # Cut-over 30 June 2026: the books show profit 60,000 and tax 7,500 booked to date, and the
    # first instalment is not yet due. July to December: 2,000 a month. Year: 72,000 x 15% =
    # 10,800, so July carries the catch-up: (62,000 x 15%) - 7,500 = 1,800.
    inputs = TaxInputs(rules=RULES, ytd_pbt=D(60000), ytd_tax=D(7500))
    book = TaxBook(inputs, date(2026, 6, 30), date(2026, 7, 1), D(7500), D(0))
    steps = [book.step(add_months(date(2026, 7, 1), n), pbt=D(2000), da=D(0), adjustment=D(0),
                       new_allowances=D(0), qualifying_dep=D(0)) for n in range(6)]  # fmt: skip
    assert steps[0].current == D(1800)
    assert sum(s.current for s in steps) + D(7500) == D(10800)
    # July instalment: tax to date 9,300 x 12/7 / 2 = 7,971.43; December: 10,800 - 7,971.43.
    paid = [p.amount for s in steps for p in s.payments]
    assert paid == [D("7971.43"), D("2828.57")]
    assert steps[-1].income_tax == 0  # the opening 7,500 was this year's booked tax


def test_deferred_tax_on_allowances_and_losses() -> None:
    # Capital allowances of 12,000 for 2026 (1,000 a month) against depreciation of 400 a month on
    # the same assets: the temporary difference grows by 600 a month; at 15% the deferred tax
    # liability is 90 x month. Taxable profit is 24,000 - 12,000 = 12,000: current tax 1,800.
    inputs = TaxInputs(rules=RULES, allowances={2026: D(12000)})
    months = run(inputs, {2026: D(24000)}, qualifying=D(400))
    assert [m.deferred for m in months[:3]] == [D(90)] * 3
    assert months[11].deferred_tax == D(1080)
    assert sum(m.current for m in months) == D(1800)
    # A deferred tax asset on losses, only when recognised: a 2026 loss of 12,000 -> 1,800.
    kept = run(TaxInputs(rules=RULES, recognise_loss_dta=True), {2026: D(-12000)})
    assert kept[11].deferred_tax == D(-1800)
    assert run(TaxInputs(rules=RULES), {2026: D(-12000)})[11].deferred_tax == 0


def test_deferred_tax_asset_on_losses_brought_forward_moves_from_the_books() -> None:
    # 10,000 of 2022 losses at the cut-over, with a deferred tax asset recognised: its 1,500 (15%)
    # is in the books' opening balance, so the projection carries only its use. 2026 profit
    # 24,000 (2,000 a month): the losses cover January to May; current tax (24,000 - 10,000) x
    # 15% = 2,100; deferred tax 1,500 as the asset is used; total 3,600 = 15% of the profit.
    inputs = TaxInputs(rules=RULES, losses_bf={2022: D(10000)}, recognise_loss_dta=True)
    book = TaxBook(inputs, date(2025, 12, 31), date(2026, 1, 1), D(0), D(-1500))
    months = [book.step(add_months(date(2026, 1, 1), n), pbt=D(2000), da=D(0), adjustment=D(0),
                        new_allowances=D(0), qualifying_dep=D(0)) for n in range(12)]  # fmt: skip
    assert [m.deferred for m in months[:6]] == [D(300)] * 5 + [D(0)]
    assert months[11].deferred_tax == D(0)  # the asset is used up
    assert sum(m.current for m in months) == D(2100)
    assert sum(m.current + m.deferred for m in months) == D(3600)


def test_a_newly_recognised_loss_asset_is_credited_in_the_first_month() -> None:
    # The same losses, but the books carry no deferred tax asset: recognising one credits 1,500 to
    # profit in January; it is then used, and the year ends with no deferred tax (never a
    # liability out of nothing).
    inputs = TaxInputs(rules=RULES, losses_bf={2022: D(10000)}, recognise_loss_dta=True)
    book = TaxBook(inputs, date(2025, 12, 31), date(2026, 1, 1), D(0), D(0))
    months = [book.step(add_months(date(2026, 1, 1), n), pbt=D(2000), da=D(0), adjustment=D(0),
                        new_allowances=D(0), qualifying_dep=D(0)) for n in range(12)]  # fmt: skip
    assert months[0].deferred == D(-1200)  # 1,500 recognised less January's use of 300
    assert months[11].deferred_tax == D(0)
    assert sum(m.deferred for m in months) == D(0)
