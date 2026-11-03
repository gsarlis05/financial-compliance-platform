"""Synthetic household dataset: accounts and categorised transactions for a personal workspace.

Invariants (asserted by tests):
- every month has exactly one salary credit and one mortgage payment (within the term);
- the current account running balance equals the opening balance plus the sum of its transactions;
- each savings transfer appears as a pair (debit current, credit savings) of equal amounts;
- the mortgage schedule repays the principal exactly.
"""

import random
from datetime import date, timedelta
from decimal import Decimal

from fcp.core.money import Money, allocate

from .output import Dataset, to_csv_bytes, to_json_bytes
from .profiles import HouseholdProfile, profile_to_json
from .schedules import add_months, annuity_schedule, month_end, previous_business_day

CURRENT = "current"
SAVINGS = "savings"
MORTGAGE = "mortgage"


def generate_household(profile: HouseholdProfile, seed: int) -> Dataset:
    profile.validate()
    rng = random.Random(seed)  # noqa: S311 - synthetic test data, not security-sensitive
    p = profile
    rows: list[tuple[date, int, str, str, str, Money]] = []
    seq = 0

    def txn(day: date, account: str, category: str, description: str, amount: Money) -> None:
        nonlocal seq
        seq += 1
        rows.append((day, seq, account, category, description, amount))

    mortgage = annuity_schedule(
        p.money(p.mortgage_principal),
        p.mortgage_annual_rate_bp,
        p.mortgage_term_months,
        p.start_date.replace(day=p.mortgage_payment_day),
    )

    for m in range(p.months):
        month_start = add_months(p.start_date, m)
        salary_day = previous_business_day(month_start.replace(day=p.salary_day))
        txn(salary_day, CURRENT, "Salary", "Salary (Demo employer)", p.money(p.net_monthly_salary))
        if month_start.month == p.bonus_month:
            txn(salary_day, CURRENT, "Salary", "Annual bonus (Demo)", p.money(p.annual_bonus))

        if m < len(mortgage):
            inst = mortgage[m]
            txn(inst.due_date, CURRENT, "Housing", "Mortgage instalment (Demo bank)", -inst.payment)
            txn(inst.due_date, MORTGAGE, "Housing", "Mortgage principal repaid", inst.principal)

        transfer_day = salary_day + timedelta(days=1)
        savings = p.money(p.monthly_savings_transfer)
        if savings.is_positive():
            txn(transfer_day, CURRENT, "Transfer", "Transfer to savings", -savings)
            txn(transfer_day, SAVINGS, "Transfer", "Transfer from current account", savings)

        last_day = month_end(month_start).day
        for category in p.categories:
            budget = p.money(category.monthly_budget)
            swing = rng.randint(-category.variability_bp, category.variability_bp)
            actual = budget.multiply(Decimal(10_000 + swing) / Decimal(10_000)).round()
            if actual.is_zero() or actual.is_negative() or category.transactions_per_month < 1:
                continue
            weights = [rng.randint(1, 100) for _ in range(category.transactions_per_month)]
            for amount in allocate(actual, weights):
                day = month_start + timedelta(days=rng.randint(0, last_day - 1))
                txn(day, CURRENT, category.name, f"{category.name} (Demo merchant)", -amount)

    rows.sort(key=lambda r: (r[0], r[1]))
    balances = {
        CURRENT: p.money(p.opening_current_account),
        SAVINGS: p.money(p.opening_savings),
        MORTGAGE: -p.money(p.mortgage_principal),
    }
    out_rows = []
    for day, _seq, account, category_name, description, amount in rows:
        balances[account] = balances[account] + amount
        out_rows.append(
            [
                day.isoformat(),
                account,
                category_name,
                description,
                amount.amount_str(),
                balances[account].amount_str(),
            ]
        )

    dataset = Dataset(kind="household", seed=seed, profile=profile_to_json(p))
    dataset.files = {
        "accounts.json": to_json_bytes(
            [
                {
                    "id": CURRENT,
                    "type": "BANK_CURRENT",
                    "name": "Current account (Demo)",
                    "opening_balance": p.money(p.opening_current_account).amount_str(),
                },
                {
                    "id": SAVINGS,
                    "type": "BANK_SAVINGS",
                    "name": "Savings account (Demo)",
                    "opening_balance": p.money(p.opening_savings).amount_str(),
                },
                {
                    "id": MORTGAGE,
                    "type": "LOAN",
                    "name": "Mortgage (Demo)",
                    "opening_balance": (-p.money(p.mortgage_principal)).amount_str(),
                },
            ]
        ),
        "transactions.csv": to_csv_bytes(
            ["date", "account", "category", "description", "amount", "balance"], out_rows
        ),
        "mortgage_schedule.csv": to_csv_bytes(
            ["number", "due_date", "payment", "interest", "principal", "closing_balance"],
            [
                [
                    str(i.number),
                    i.due_date.isoformat(),
                    i.payment.amount_str(),
                    i.interest.amount_str(),
                    i.principal.amount_str(),
                    i.closing_balance.amount_str(),
                ]
                for i in mortgage
            ],
        ),
    }
    return dataset
