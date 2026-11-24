"""Corporate income tax in projections (M6F-5, #150; owner decision D4): pure, no database.

The rules (rate, loss carry-forward, instalment dates, final payment) come from the versioned
rule sets (M6F-2) for each tax year and are pinned in the run; tax years are calendar years.
Every figure below is rounded to cents once; the roll-forwards tie exactly.

**Taxable profit** of a tax year = profit before tax + accounting depreciation (added back in full)
- capital allowances (the registered assets' allowances for the year, M6F-3, and those of new
capex) + tax adjustments (the ``tax_adjustment`` driver: non-deductible costs as positive
amounts, non-taxable income as negative). For the tax year containing the cut-over, the actual
months to the cut-over come from the books.

**Losses** are kept by the year they arose and can be used for the number of years the rule set of
that year allows; the oldest are used first. A loss of the year is added to the pool at the year
end; losses that can no longer be used expire then. ``losses_bf`` are the unused losses available
at the start of the first projected tax year, by the year they arose (an input of the set).

**Current tax** is accrued month by month on a **year-to-date** basis: tax on (taxable profit to
date - available losses), never below zero, at the year's rate; each month's expense is the
change in that figure. The year-end figure is therefore the year's tax exactly. For the tax year of
the cut-over, the tax already booked to the cut-over counts as accrued, so the first projected
month carries any catch-up.

**Payments:**
- provisional instalments on the rule set's dates (after the cut-over), each bringing the year's
  provisional total to the instalment's cumulative share of the year's tax **as projected to that
  month, annualised** (to date x 12 / months elapsed); never a negative instalment;
- the final balancing payment (or refund) of a year's remaining liability on its final date;
- the opening balance owed for earlier years (the books' income tax balance less the current year's
  booked tax and its instalments already paid) on the previous year's final date, or in the first
  projected month if that date has passed.
Late-payment interest, penalties and the underestimation charge are not modelled.

**Deferred tax** (IAS 12), on two temporary differences, at the year's rate:
- fixed assets that qualify for capital allowances: cumulative (allowances - their accounting
  depreciation) since the cut-over, allowances spread evenly over the months of the tax year;
- unused tax losses, only if the entity recognises a deferred tax asset on them (a judgement);
  the books' deferred tax asset (up to the losses' tax value) is taken to be the asset on the
  losses brought forward, so only its movement is projected; any rest is recognised in the first
  projected month (IAS 12: a newly recognised asset is credited to profit).
The opening deferred tax is the books' balance (often none); the projection adds the movement.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
TWELVE = Decimal(12)


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class TaxYearRule:
    year: int
    rate: Decimal  # fraction, 0.15 for 15%
    carry_years: int  # for losses arising in this year
    instalments: tuple[tuple[date, Decimal], ...]  # date and share of the year's tax
    final_date: date
    rule_id: str
    verified: bool


@dataclass(frozen=True)
class TaxInputs:
    rules: dict[int, TaxYearRule]
    losses_bf: dict[int, Decimal] = field(default_factory=dict)  # by the year the loss arose
    ytd_pbt: Decimal = ZERO  # actual, tax year of the cut-over, to the cut-over
    ytd_da: Decimal = ZERO
    ytd_tax: Decimal = ZERO  # current tax booked to the cut-over
    paid_ytd: Decimal = ZERO  # provisional tax paid for that year before the cut-over
    allowances: dict[int, Decimal] = field(default_factory=dict)  # registered assets, by year
    qualifying_dep: dict[date, Decimal] = field(default_factory=dict)  # registered, by month
    recognise_loss_dta: bool = False


@dataclass(frozen=True)
class Payment:
    year: int | None  # None: years before the first projected one
    kind: str  # PROVISIONAL, FINAL or PRIOR
    amount: Decimal  # positive: paid; negative: refunded


@dataclass(frozen=True)
class TaxMonth:
    year: int
    rule_id: str
    verified: bool
    taxable_ytd: Decimal
    current: Decimal  # current tax expense of the month
    deferred: Decimal  # deferred tax expense of the month
    payments: tuple[Payment, ...]
    income_tax: Decimal  # balance owed (negative: receivable)
    deferred_tax: Decimal  # net deferred tax liability (negative: asset)
    losses_available: Decimal  # unused losses at the month end
    losses_arising: Decimal  # at the year end
    losses_used: Decimal  # at the year end
    losses_expired: Decimal  # at the year end
    pool_before: Decimal = ZERO  # every unused loss before the year-end close
    pool_after: Decimal = ZERO  # and after it

    @property
    def paid(self) -> Decimal:
        return sum((p.amount for p in self.payments), ZERO)


class TaxBook:
    """The tax position, stepped month by month by the engine (see the module text)."""

    def __init__(self, inputs: TaxInputs, cutover: date, first_month: date,
                 opening_income_tax: Decimal, opening_deferred: Decimal) -> None:  # fmt: skip
        self.inp = inputs
        self.cutover = cutover
        self.pool: list[list[int | Decimal]] = [
            [year, cents(amount)] for year, amount in sorted(inputs.losses_bf.items()) if amount > 0
        ]  # [year arisen, amount left]
        self.year: int | None = None
        self.same_year = first_month.year == cutover.year
        booked_now = (inputs.ytd_tax - inputs.paid_ytd) if self.same_year else ZERO
        self.prior = cents(opening_income_tax - booked_now)
        previous = self.rule(first_month.year - 1, required=False)
        self.prior_date = previous.final_date if previous else first_month
        if self.prior_date <= cutover:
            self.prior_date = first_month
        self.owed: dict[int, Decimal] = {}  # liability per tax year (accrued - paid)
        self.paid: dict[int, Decimal] = {}  # provisional paid per tax year
        self.opening_deferred = cents(opening_deferred)
        self.deferred_balance = self.opening_deferred
        self.temporary = Decimal(0)  # cumulative (allowances - qualifying depreciation)
        # A deferred tax asset on the losses brought forward that the books already carry (their
        # deferred tax asset, up to the losses' tax value) is part of the opening balance sheet:
        # only its movement is projected. Any rest is recognised in the first projected month.
        first = self.rule(first_month.year, required=False)
        on_losses = (cents(self.available(first_month.year) * first.rate)
                     if inputs.recognise_loss_dta and first else ZERO)  # fmt: skip
        self.loss_asset_start = min(on_losses, max(-self.opening_deferred, ZERO))

    def rule(self, year: int, *, required: bool = True) -> TaxYearRule | None:
        found = self.inp.rules.get(year)
        if found is None and required:
            raise ValueError(f"No corporate tax rule set for tax year {year}.")
        return found

    def available(self, year: int) -> Decimal:
        """Unused losses that can still be used in ``year``."""
        total = ZERO
        for arisen, amount in self.pool:
            rule = self.rule(int(arisen), required=False)
            carry = rule.carry_years if rule else 0
            if int(arisen) < year <= int(arisen) + carry:
                total += Decimal(amount)
        return total

    def _start_year(self, year: int) -> None:
        self.year = year
        first = self.same_year and year == self.cutover.year
        self.base = (self.inp.ytd_pbt + self.inp.ytd_da) if first else ZERO
        self.accrued = cents(self.inp.ytd_tax) if first else ZERO
        self.paid[year] = cents(self.inp.paid_ytd) if first else ZERO
        self.owed[year] = self.accrued - self.paid[year]
        self.year_sum = Decimal(0)

    def step(self, month: date, *, pbt: Decimal, da: Decimal, adjustment: Decimal,
             new_allowances: Decimal, qualifying_dep: Decimal) -> TaxMonth:  # fmt: skip
        """``new_allowances``: capital allowances of new capex for this month's tax year (the
        whole year); ``qualifying_dep``: depreciation this month of assets with allowances."""
        year, k = month.year, month.month
        if self.year != year:
            self._start_year(year)
        rule = self.rule(year)
        assert rule is not None  # noqa: S101 (required above)
        self.year_sum += pbt + da + adjustment
        allowances = self.inp.allowances.get(year, ZERO) + new_allowances
        taxable = self.base + self.year_sum - allowances * k / TWELVE
        losses = self.available(year)
        tax_ytd = cents(max(taxable - losses, ZERO) * rule.rate)
        current = tax_ytd - self.accrued
        self.accrued = tax_ytd
        self.owed[year] += current
        payments = self._payments(month, rule, tax_ytd, k)
        # Deferred tax.
        self.temporary += allowances / TWELVE - qualifying_dep
        liability = cents(self.temporary * rule.rate)
        loss_position = losses + max(-taxable, ZERO) - min(losses, max(taxable, ZERO))
        asset = (cents(loss_position * rule.rate) - self.loss_asset_start
                 if self.inp.recognise_loss_dta else ZERO)  # fmt: skip
        balance = self.opening_deferred + liability - asset
        deferred = balance - self.deferred_balance
        self.deferred_balance = balance
        arising = used = expired = before = after = ZERO
        if k == 12:
            before = sum((Decimal(e[1]) for e in self.pool), ZERO)
            arising, used, expired = self._close_year(year, taxable)
            after = sum((Decimal(e[1]) for e in self.pool), ZERO)
        return TaxMonth(
            year=year, rule_id=rule.rule_id, verified=rule.verified, taxable_ytd=cents(taxable),
            current=current, deferred=deferred, payments=tuple(payments),
            income_tax=self.prior + sum(self.owed.values(), ZERO), deferred_tax=balance,
            losses_available=self.available(year + 1) if k == 12 else losses,
            losses_arising=arising, losses_used=used, losses_expired=expired,
            pool_before=before, pool_after=after,
        )  # fmt: skip

    def _payments(self, month: date, rule: TaxYearRule, tax_ytd: Decimal,
                  k: int) -> list[Payment]:  # fmt: skip
        payments: list[Payment] = []
        if self.prior and self.prior_date.year == month.year and \
                self.prior_date.month == month.month:  # fmt: skip
            payments.append(Payment(None, "PRIOR", self.prior))
            self.prior = ZERO
        cumulative = ZERO
        for day, share in rule.instalments:
            cumulative += share
            if day.year != month.year or day.month != month.month or day <= self.cutover:
                continue
            target = cents(cumulative * tax_ytd * TWELVE / k)
            amount = max(target - self.paid[rule.year], ZERO)
            if amount:
                self.paid[rule.year] += amount
                self.owed[rule.year] -= amount
                payments.append(Payment(rule.year, "PROVISIONAL", amount))
        for year in sorted(self.owed):
            earlier = self.rule(year, required=False)
            if earlier is None or year == month.year:
                continue
            final = earlier.final_date
            if final.year == month.year and final.month == month.month and self.owed[year]:
                payments.append(Payment(year, "FINAL", self.owed[year]))
                self.owed[year] = ZERO
        return payments

    def _close_year(self, year: int, taxable: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """At the year end: use losses (oldest first), add a new loss, expire old ones. The year's
        taxable profit is rounded to cents first, so the pool stays in cents."""
        taxable = cents(taxable)
        used = arising = expired = ZERO
        if taxable > 0:
            left = taxable
            for entry in self.pool:
                arisen = int(entry[0])
                rule = self.rule(arisen, required=False)
                if rule is None or not arisen < year <= arisen + rule.carry_years:
                    continue
                take = min(Decimal(entry[1]), left)
                entry[1] = Decimal(entry[1]) - take
                used += take
                left -= take
        elif taxable < 0:
            arising = cents(-taxable)
            self.pool.append([year, arising])
        kept = []
        for entry in self.pool:
            arisen = int(entry[0])
            rule = self.rule(arisen, required=False)
            carry = rule.carry_years if rule else 0
            if Decimal(entry[1]) > 0 and arisen + carry > year:
                kept.append(entry)
            else:
                expired += Decimal(entry[1])
        self.pool = kept
        return arising, cents(used), cents(expired)
