"""Synthetic business dataset: counterparties, sales and purchase invoices, bank transactions,
loan schedule and recurring obligations.

Invariants (asserted by tests):
- annual net revenue equals the profile target (with growth) exactly, to the cent;
- every invoice: gross = net + VAT, VAT = net x rate rounded HALF_UP;
- every paid invoice has exactly one bank transaction for its gross amount on its paid date;
- the bank running balance equals opening cash plus the sum of transactions;
- the loan schedule repays the principal exactly.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from fcp.core.money import Money, allocate

from .identifiers import email_for, fictional_company_name, fictional_cy_iban, fictional_cy_vat
from .output import Dataset, to_csv_bytes, to_json_bytes
from .profiles import BusinessProfile, profile_to_json
from .schedules import (
    Instalment,
    add_months,
    annuity_schedule,
    month_end,
    next_business_day,
    previous_business_day,
)


@dataclass(frozen=True)
class Counterparty:
    id: str
    kind: str
    name: str
    vat_no: str
    iban: str
    email: str
    payment_terms_days: int
    avg_days_late: int
    size_weight: int


@dataclass(frozen=True)
class Invoice:
    number: str
    side: str  # "SALE" or "PURCHASE"
    counterparty_id: str
    issue_date: date
    due_date: date
    net: Money
    vat: Money
    paid_date: date | None

    @property
    def gross(self) -> Money:
        return self.net + self.vat


@dataclass(frozen=True)
class BankTxn:
    date: date
    seq: int
    description: str
    amount: Money
    counterparty_id: str
    reference: str


def _counterparties(rng: random.Random, p: BusinessProfile) -> list[Counterparty]:
    used: set[str] = set()
    result = []
    lo_late, hi_late = p.customer_days_late
    for i in range(1, p.customers + 1):
        name = fictional_company_name(rng, used)
        result.append(
            Counterparty(
                id=f"C{i:03d}",
                kind="CUSTOMER",
                name=name,
                vat_no=fictional_cy_vat(rng),
                iban=fictional_cy_iban(rng),
                email=email_for(name),
                payment_terms_days=p.customer_payment_terms_days,
                avg_days_late=rng.randint(lo_late, hi_late),
                size_weight=rng.randint(1, 10),
            )
        )
    for i in range(1, p.suppliers + 1):
        name = fictional_company_name(rng, used)
        result.append(
            Counterparty(
                id=f"S{i:03d}",
                kind="SUPPLIER",
                name=name,
                vat_no=fictional_cy_vat(rng),
                iban=fictional_cy_iban(rng),
                email=email_for(name),
                payment_terms_days=p.supplier_payment_terms_days,
                avg_days_late=0,
                size_weight=rng.randint(1, 10),
            )
        )
    return result


def _random_day(rng: random.Random, month_start: date) -> date:
    return month_start + timedelta(days=rng.randint(0, month_end(month_start).day - 1))


def _bp(value: int) -> Decimal:
    return Decimal(value) / Decimal(10_000)


class _BusinessBuilder:
    """Builds the dataset step by step; every random draw comes from one seeded generator."""

    def __init__(self, profile: BusinessProfile, seed: int) -> None:
        self.p = profile
        self.rng = random.Random(seed)  # noqa: S311 - synthetic test data, not security-sensitive
        self.as_of = month_end(add_months(profile.start_date, 12 * profile.years - 1))
        self.parties = _counterparties(self.rng, profile)
        self.customers = [c for c in self.parties if c.kind == "CUSTOMER"]
        self.suppliers = [c for c in self.parties if c.kind == "SUPPLIER"]
        self.invoices: list[Invoice] = []
        self.txns: list[BankTxn] = []
        self._numbers = {"SALE": 0, "PURCHASE": 0}
        self.loan_schedule: list[Instalment] = []

    # --- helpers ---------------------------------------------------------------------------

    def _next_number(self, side: str, year: int) -> str:
        self._numbers[side] += 1
        prefix = "INV" if side == "SALE" else "PI"
        return f"{prefix}-{year}-{self._numbers[side]:05d}"

    def _bank(
        self, day: date, description: str, amount: Money, cp: str = "", ref: str = ""
    ) -> None:
        self.txns.append(BankTxn(day, len(self.txns) + 1, description, amount, cp, ref))

    def _pick(self, parties: list[Counterparty]) -> Counterparty:
        return self.rng.choices(parties, weights=[c.size_weight for c in parties])[0]

    # --- steps -------------------------------------------------------------------------------

    def trading(self) -> None:
        p = self.p
        growth = Decimal(1) + _bp(p.revenue_growth_bp)
        for year in range(p.years):
            year_revenue = p.money(p.annual_revenue).multiply(growth**year).round()
            for offset, month_revenue in enumerate(allocate(year_revenue, list(p.seasonality))):
                month_start = add_months(p.start_date, 12 * year + offset)
                count = self.rng.randint(*p.invoices_per_month)
                self._sales(month_start, month_revenue, count)
                cost = month_revenue.multiply(Decimal(1) - _bp(p.gross_margin_bp)).round()
                self._purchases(month_start, cost, max(3, count // 3))
                self._recurring_costs(month_start)

    def _sales(self, month_start: date, revenue: Money, count: int) -> None:
        weights = [self.rng.randint(1, 100) for _ in range(count)]
        for net in allocate(revenue, weights):
            customer = self._pick(self.customers)
            issue = _random_day(self.rng, month_start)
            due = issue + timedelta(days=customer.payment_terms_days)
            paid: date | None = None
            if self.rng.randint(1, 10_000) > self.p.customer_default_bp:
                late = customer.avg_days_late + self.rng.randint(-5, 10)
                candidate = next_business_day(max(issue, due + timedelta(days=late)))
                paid = candidate if candidate <= self.as_of else None
            self._add_invoice("SALE", customer, issue, due, net, paid)

    def _purchases(self, month_start: date, cost: Money, count: int) -> None:
        weights = [self.rng.randint(1, 100) for _ in range(count)]
        for net in allocate(cost, weights):
            supplier = self._pick(self.suppliers)
            issue = _random_day(self.rng, month_start)
            due = issue + timedelta(days=supplier.payment_terms_days)
            pay_day = max(issue, previous_business_day(due + timedelta(self.rng.randint(-3, 3))))
            self._add_invoice(
                "PURCHASE", supplier, issue, due, net, pay_day if pay_day <= self.as_of else None
            )

    def _add_invoice(
        self, side: str, cp: Counterparty, issue: date, due: date, net: Money, paid: date | None
    ) -> None:
        vat = net.multiply(_bp(self.p.vat_rate_bp)).round()
        number = self._next_number(side, issue.year)
        self.invoices.append(Invoice(number, side, cp.id, issue, due, net, vat, paid))

    def _recurring_costs(self, month_start: date) -> None:
        p = self.p
        for day, description, amount, ref in (
            (1, "Office rent (Demo)", p.monthly_rent, "RENT"),
            (15, "Operating expenses (Demo)", p.monthly_other_opex, "OPEX"),
            (28, "Payroll (Demo)", p.monthly_payroll, "PAYROLL"),
        ):
            pay_day = previous_business_day(month_start.replace(day=day))
            self._bank(pay_day, description, -p.money(amount), ref=ref)

    def settlements(self) -> None:
        for inv in self.invoices:
            if inv.paid_date is not None:
                sign = 1 if inv.side == "SALE" else -1
                label = "Customer receipt" if inv.side == "SALE" else "Supplier payment"
                self._bank(inv.paid_date, label, inv.gross * sign, inv.counterparty_id, inv.number)

    def vat(self) -> None:
        """Quarterly VAT settlement (illustrative timing): output minus input VAT, paid on the
        10th of the second month after quarter end; refunds are carried forward."""
        p = self.p
        carry = Money.zero(p.currency)
        for quarter in range(p.years * 4):
            q_start = add_months(p.start_date, quarter * 3)
            q_end = month_end(add_months(q_start, 2))
            in_quarter = [i for i in self.invoices if q_start <= i.issue_date <= q_end]
            output_vat = Money.total((i.vat for i in in_quarter if i.side == "SALE"), p.currency)
            input_vat = Money.total((i.vat for i in in_quarter if i.side == "PURCHASE"), p.currency)
            due_vat = output_vat - input_vat + carry
            pay_day = previous_business_day(add_months(q_start, 4).replace(day=10))
            if due_vat.is_positive() and pay_day <= self.as_of:
                self._bank(pay_day, "VAT payment (Demo)", -due_vat, "TAX", f"VAT-Q{quarter + 1}")
                carry = Money.zero(p.currency)
            elif not due_vat.is_positive():
                carry = due_vat

    def loan(self) -> None:
        p = self.p
        principal = p.money(p.loan_principal)
        first_due = add_months(p.start_date, 1).replace(day=20)
        self.loan_schedule = annuity_schedule(
            principal, p.loan_annual_rate_bp, p.loan_term_months, first_due
        )
        if not principal.is_positive():
            return
        self._bank(p.start_date, "Term loan drawdown (Demo)", principal, "LENDER", "LOAN-1")
        for inst in self.loan_schedule:
            if inst.due_date <= self.as_of:
                self._bank(
                    previous_business_day(inst.due_date),
                    "Loan instalment (Demo)",
                    -inst.payment,
                    "LENDER",
                    f"LOAN-1-{inst.number:03d}",
                )

    # --- output ------------------------------------------------------------------------------

    def _invoice_rows(self, side: str) -> list[list[str]]:
        return [
            [
                i.number,
                i.counterparty_id,
                i.issue_date.isoformat(),
                i.due_date.isoformat(),
                i.net.amount_str(),
                i.vat.amount_str(),
                i.gross.amount_str(),
                i.paid_date.isoformat() if i.paid_date else "",
            ]
            for i in self.invoices
            if i.side == side
        ]

    def _bank_rows(self) -> list[list[str]]:
        balance = self.p.money(self.p.opening_cash)
        result = []
        for t in sorted(self.txns, key=lambda t: (t.date, t.seq)):
            balance = balance + t.amount
            result.append(
                [
                    t.date.isoformat(),
                    t.description,
                    t.amount.amount_str(),
                    balance.amount_str(),
                    t.counterparty_id,
                    t.reference,
                ]
            )
        return result

    def files(self) -> dict[str, bytes]:
        p = self.p
        invoice_header = [
            "number", "counterparty_id", "issue_date", "due_date", "net", "vat", "gross",
            "paid_date",
        ]  # fmt: skip
        schedule_header = [
            "number",
            "due_date",
            "payment",
            "interest",
            "principal",
            "closing_balance",
        ]
        return {
            "company.json": to_json_bytes(
                {
                    "legal_name": p.name,
                    "registration_no": "DEMO-0001",
                    "jurisdiction": "CY",
                    "functional_currency": p.currency,
                    "vat_no": fictional_cy_vat(self.rng),
                    "fiscal_year_start": p.start_date.isoformat(),
                    "as_of": self.as_of.isoformat(),
                    "opening_cash": p.money(p.opening_cash).amount_str(),
                }
            ),
            "counterparties.json": to_json_bytes(
                [
                    {
                        "id": c.id,
                        "kind": c.kind,
                        "name": c.name,
                        "vat_no": c.vat_no,
                        "iban": c.iban,
                        "email": c.email,
                        "payment_terms_days": c.payment_terms_days,
                        "avg_days_late": c.avg_days_late,
                    }
                    for c in self.parties
                ]
            ),
            "sales_invoices.csv": to_csv_bytes(invoice_header, self._invoice_rows("SALE")),
            "purchase_invoices.csv": to_csv_bytes(invoice_header, self._invoice_rows("PURCHASE")),
            "bank_transactions.csv": to_csv_bytes(
                ["date", "description", "amount", "balance", "counterparty_id", "reference"],
                self._bank_rows(),
            ),
            "loan_schedule.csv": to_csv_bytes(
                schedule_header,
                [
                    [
                        str(i.number),
                        i.due_date.isoformat(),
                        i.payment.amount_str(),
                        i.interest.amount_str(),
                        i.principal.amount_str(),
                        i.closing_balance.amount_str(),
                    ]
                    for i in self.loan_schedule
                ],
            ),
            "recurring_obligations.json": to_json_bytes(
                [
                    {
                        "name": name,
                        "amount": p.money(amount).amount_str(),
                        "schedule": f"monthly, day {day}, previous business day",
                        "contractual": contractual,
                    }
                    for name, amount, day, contractual in (
                        ("Office rent (Demo)", p.monthly_rent, 1, True),
                        ("Operating expenses (Demo)", p.monthly_other_opex, 15, False),
                        ("Payroll (Demo)", p.monthly_payroll, 28, True),
                    )
                ]
            ),
        }


def generate_business(profile: BusinessProfile, seed: int) -> Dataset:
    """Generate the business dataset for ``profile`` deterministically from ``seed``."""
    profile.validate()
    builder = _BusinessBuilder(profile, seed)
    builder.trading()
    builder.settlements()
    builder.vat()
    builder.loan()
    dataset = Dataset(kind="business", seed=seed, profile=profile_to_json(profile))
    dataset.files = builder.files()
    return dataset
