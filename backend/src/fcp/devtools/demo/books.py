"""Turn the synthetic business dataset (M0-6) into monthly summary journal entries.

Pure functions, no database: the result is a list of balanced entries keyed by account code
(``cy_business`` chart). One entry per month and source keeps the demo fast while every euro of
the dataset is booked, so the bank account's closing balance must equal the dataset's bank
statement closing balance. The demo checks this.

Simplifications (demo data only): VAT payments are debited to output VAT without netting input VAT
(VAT returns arrive in M3), and the whole loan stays non-current.
"""

import csv
import io
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from fcp.devtools.synthetic import generate_business
from fcp.devtools.synthetic.profiles import BusinessProfile

BANK = "1300"

# Bank transactions with one counter-account: description -> (entry title, account code).
_BANK_COUNTER_ACCOUNT = {
    "Customer receipt": ("Customer receipts", "1200"),
    "Supplier payment": ("Supplier payments", "2100"),
    "Payroll (Demo)": ("Payroll", "6000"),
    "Office rent (Demo)": ("Office rent", "6100"),
    "Operating expenses (Demo)": ("Operating expenses", "6900"),
    "VAT payment (Demo)": ("VAT payments", "2120"),
    "Term loan drawdown (Demo)": ("Term loan drawdown", "2010"),
}


_CONTROL_ACCOUNTS = {"1200", "2100"}


@dataclass(frozen=True)
class DemoCounterparty:
    code: str
    kind: str
    name: str
    payment_terms_days: int


@dataclass
class DemoEntry:
    accounting_date: date
    description: str
    # line key -> (debit, credit). The key is an account code, or "code@counterparty" for
    # control-account lines (trade receivables and payables need a counterparty, M2-2).
    lines: dict[str, list[Decimal]] = field(default_factory=dict)

    def add(self, code: str, debit: Decimal = Decimal(0), credit: Decimal = Decimal(0)) -> None:
        line = self.lines.setdefault(code, [Decimal(0), Decimal(0)])
        line[0] += debit
        line[1] += credit

    def signed(self, code: str, amount: Decimal) -> None:
        """Debit a positive amount, credit a negative one."""
        if amount >= 0:
            self.add(code, debit=amount)
        else:
            self.add(code, credit=-amount)

    def netted(self) -> list[tuple[str, Decimal, Decimal]]:
        """Lines as (code, debit, credit), each account netted to one side, zero lines dropped."""
        result = []
        for code, (debit, credit) in sorted(self.lines.items()):
            net = debit - credit
            if net > 0:
                result.append((code, net, Decimal(0)))
            elif net < 0:
                result.append((code, Decimal(0), -net))
        return result

    def is_balanced(self) -> bool:
        rows = self.netted()
        return sum(r[1] for r in rows) == sum(r[2] for r in rows)


@dataclass(frozen=True)
class DemoBooks:
    company: str
    fiscal_year_start: date
    opening_cash: Decimal
    bank_closing_balance: Decimal
    entries: list[DemoEntry]
    fingerprint: str
    counterparties: list[DemoCounterparty] = field(default_factory=list)


def _month_end(day: date) -> date:
    following = date(day.year + day.month // 12, day.month % 12 + 1, 1)
    return date.fromordinal(following.toordinal() - 1)


def _rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))


def _month_key(value: str) -> date:
    return _month_end(date.fromisoformat(value))


def _require_in_year(days: Iterable[date], start: date) -> None:
    end = date(start.year + 1, start.month, 1)
    outside = sorted({d for d in days if not start <= d < end})
    if outside:
        raise ValueError(f"Dataset has dates outside the fiscal year: {outside[:3]}")


def build_demo_books(seed: int = 42, year: int = 2026) -> DemoBooks:  # noqa: PLR0915 - linear
    """Generate one year of synthetic trading for ``year`` and summarise it into entries."""
    profile = BusinessProfile(start_date=date(year, 1, 1), years=1)
    dataset = generate_business(profile, seed)
    files = dataset.files
    company = json.loads(files["company.json"])
    start = date.fromisoformat(company["fiscal_year_start"])
    opening_cash = Decimal(company["opening_cash"])

    sales = _rows(files["sales_invoices.csv"])
    purchases = _rows(files["purchase_invoices.csv"])
    bank = _rows(files["bank_transactions.csv"])
    loan = {f"LOAN-1-{int(r['number']):03d}": r for r in _rows(files["loan_schedule.csv"])}
    _require_in_year(
        [date.fromisoformat(r["issue_date"]) for r in sales + purchases]
        + [date.fromisoformat(r["date"]) for r in bank],
        start,
    )

    opening = DemoEntry(start, "Opening balance: share capital paid in (Demo)")
    opening.add(BANK, debit=opening_cash)
    opening.add("3000", credit=opening_cash)
    entries = [opening]

    monthly: dict[tuple[date, str], DemoEntry] = {}

    def entry(month: date, title: str) -> DemoEntry:
        key = (month, title)
        if key not in monthly:
            label = f"{title} — {month:%B %Y} (Demo, monthly summary)"
            monthly[key] = DemoEntry(month, label)
        return monthly[key]

    for row in sales:
        e = entry(_month_key(row["issue_date"]), "Sales invoices")
        e.add(f"1200@{row['counterparty_id']}", debit=Decimal(row["gross"]))
        e.add("4000", credit=Decimal(row["net"]))
        e.add("2120", credit=Decimal(row["vat"]))
    for row in purchases:
        e = entry(_month_key(row["issue_date"]), "Purchase invoices")
        e.add("5000", debit=Decimal(row["net"]))
        e.add("1220", debit=Decimal(row["vat"]))
        e.add(f"2100@{row['counterparty_id']}", credit=Decimal(row["gross"]))
    for row in bank:
        amount = Decimal(row["amount"])
        description = row["description"]
        if description == "Loan instalment (Demo)":
            instalment = loan[row["reference"]]
            if Decimal(instalment["payment"]) != -amount:
                raise ValueError(f"Loan instalment {row['reference']} does not match the schedule")
            e = entry(_month_key(row["date"]), "Loan instalments")
            e.add("7000", debit=Decimal(instalment["interest"]))
            e.add("2010", debit=Decimal(instalment["principal"]))
        elif description in _BANK_COUNTER_ACCOUNT:
            title, counter_account = _BANK_COUNTER_ACCOUNT[description]
            if counter_account in _CONTROL_ACCOUNTS:
                counter_account = f"{counter_account}@{row['counterparty_id']}"
            e = entry(_month_key(row["date"]), title)
            e.signed(counter_account, -amount)
        else:
            raise ValueError(f"Unmapped bank transaction: {description!r}")
        e.signed(BANK, amount)

    entries.extend(monthly[key] for key in sorted(monthly))
    unbalanced = [e.description for e in entries if not e.is_balanced()]
    if unbalanced:
        raise ValueError(f"Unbalanced demo entries: {unbalanced[:3]}")
    return DemoBooks(
        company=company["legal_name"],
        fiscal_year_start=start,
        opening_cash=opening_cash,
        bank_closing_balance=Decimal(bank[-1]["balance"]) if bank else opening_cash,
        entries=entries,
        fingerprint=dataset.fingerprint(),
        counterparties=[
            DemoCounterparty(c["id"], c["kind"], c["name"], c["payment_terms_days"])
            for c in json.loads(files["counterparties.json"])
        ],
    )
