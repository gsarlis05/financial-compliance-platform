"""Parameter profiles for the synthetic data generators.

Profiles are plain JSON so you can describe a situation resembling your own business or household
(levels, seasonality, payment behaviour) **without entering any real records**. Keep personal
profile files outside the repository or in the git-ignored ``var/`` directory.

All monetary values are decimal strings; rates are integer basis points (1% = 100 bp).
Rates such as VAT are illustrative inputs for test data only, not authoritative tax rules.
"""

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any

from fcp.core.money import Money


@dataclass(frozen=True)
class BusinessProfile:
    name: str = "Demo Trading Ltd (Demo)"
    currency: str = "EUR"
    start_date: date = date(2024, 1, 1)
    years: int = 3
    annual_revenue: str = "1200000.00"
    revenue_growth_bp: int = 800
    gross_margin_bp: int = 4500
    # Relative revenue weight per calendar month (Jan..Dec).
    seasonality: tuple[int, ...] = (70, 75, 90, 95, 110, 120, 130, 125, 105, 95, 85, 100)
    customers: int = 40
    suppliers: int = 25
    invoices_per_month: tuple[int, int] = (35, 55)
    customer_payment_terms_days: int = 30
    supplier_payment_terms_days: int = 45
    # Average days late per customer is drawn from this inclusive range (negative = early).
    customer_days_late: tuple[int, int] = (-5, 45)
    # Share of customer invoices that are never paid within the horizon (bad debts), in bp.
    customer_default_bp: int = 80
    monthly_payroll: str = "26000.00"
    monthly_rent: str = "4500.00"
    monthly_other_opex: str = "6000.00"
    vat_rate_bp: int = 1900
    loan_principal: str = "250000.00"
    loan_annual_rate_bp: int = 550
    loan_term_months: int = 60
    opening_cash: str = "150000.00"

    def money(self, value: str) -> Money:
        return Money.of(value, self.currency)

    def validate(self) -> None:
        if self.years < 1 or self.years > 10:
            raise ValueError("years must be between 1 and 10")
        if len(self.seasonality) != 12 or any(w <= 0 for w in self.seasonality):
            raise ValueError("seasonality needs 12 positive monthly weights")
        if not 0 <= self.gross_margin_bp < 10000:
            raise ValueError("gross_margin_bp must be between 0 and 9999")
        if self.customers < 1 or self.suppliers < 1:
            raise ValueError("customers and suppliers must be at least 1")
        lo, hi = self.invoices_per_month
        if lo < 1 or hi < lo:
            raise ValueError("invoices_per_month must be (min >= 1, max >= min)")
        if self.start_date.day != 1:
            raise ValueError("start_date must be the first day of a month")
        for name in (
            "annual_revenue",
            "monthly_payroll",
            "monthly_rent",
            "monthly_other_opex",
            "loan_principal",
            "opening_cash",
        ):
            if self.money(getattr(self, name)).is_negative():
                raise ValueError(f"{name} must not be negative")


@dataclass(frozen=True)
class SpendingCategory:
    name: str
    monthly_budget: str
    transactions_per_month: int
    variability_bp: int = 2500


@dataclass(frozen=True)
class HouseholdProfile:
    name: str = "Demo Household (Demo)"
    currency: str = "EUR"
    start_date: date = date(2025, 1, 1)
    months: int = 24
    net_monthly_salary: str = "3400.00"
    salary_day: int = 25
    annual_bonus: str = "2500.00"
    bonus_month: int = 12
    mortgage_principal: str = "180000.00"
    mortgage_annual_rate_bp: int = 420
    mortgage_term_months: int = 300
    mortgage_payment_day: int = 5
    monthly_savings_transfer: str = "400.00"
    opening_current_account: str = "4200.00"
    opening_savings: str = "15000.00"
    categories: tuple[SpendingCategory, ...] = field(
        default_factory=lambda: (
            SpendingCategory("Groceries", "520.00", 9),
            SpendingCategory("Utilities", "190.00", 3, 1500),
            SpendingCategory("Transport", "210.00", 6),
            SpendingCategory("Health", "80.00", 1, 6000),
            SpendingCategory("Insurance", "95.00", 1, 0),
            SpendingCategory("Leisure", "260.00", 5, 5000),
            SpendingCategory("Telecoms", "65.00", 1, 0),
        )
    )

    def money(self, value: str) -> Money:
        return Money.of(value, self.currency)

    def validate(self) -> None:
        if not 1 <= self.months <= 120:
            raise ValueError("months must be between 1 and 120")
        if not 1 <= self.salary_day <= 28 or not 1 <= self.mortgage_payment_day <= 28:
            raise ValueError("payment days must be between 1 and 28")
        if not 1 <= self.bonus_month <= 12:
            raise ValueError("bonus_month must be between 1 and 12")
        if self.start_date.day != 1:
            raise ValueError("start_date must be the first day of a month")


def _coerce(cls: type[Any], data: dict[str, Any]) -> dict[str, Any]:
    known = {f.name for f in fields(cls)}
    unknown = set(data) - known
    if unknown:
        raise ValueError(f"Unknown profile fields: {', '.join(sorted(unknown))}")
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key == "start_date":
            out[key] = date.fromisoformat(value)
        elif key == "categories":
            out[key] = tuple(SpendingCategory(**c) for c in value)
        elif isinstance(value, list):
            out[key] = tuple(value)
        else:
            out[key] = value
    return out


def load_business_profile(path: Path) -> BusinessProfile:
    profile = BusinessProfile(**_coerce(BusinessProfile, json.loads(path.read_text("utf-8"))))
    profile.validate()
    return profile


def load_household_profile(path: Path) -> HouseholdProfile:
    profile = HouseholdProfile(**_coerce(HouseholdProfile, json.loads(path.read_text("utf-8"))))
    profile.validate()
    return profile


def profile_to_json(profile: BusinessProfile | HouseholdProfile) -> dict[str, Any]:
    data = asdict(profile)
    data["start_date"] = profile.start_date.isoformat()
    return data
