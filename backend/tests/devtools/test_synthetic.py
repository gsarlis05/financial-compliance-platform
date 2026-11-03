"""Synthetic data generator tests (AC-M0-5 of the M0 brief: determinism and fictional data)."""

import csv
import io
import json
import random
from collections import Counter
from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fcp.core.money import Money
from fcp.devtools.synthetic import (
    BusinessProfile,
    HouseholdProfile,
    generate_business,
    generate_household,
)
from fcp.devtools.synthetic.__main__ import main as cli
from fcp.devtools.synthetic.identifiers import (
    cy_vat_check_letter,
    fictional_cy_iban,
    fictional_cy_vat,
    iban_mod97,
)
from fcp.devtools.synthetic.profiles import load_business_profile, load_household_profile
from fcp.devtools.synthetic.schedules import add_months, annuity_schedule
from tools.fcp_lint.no_float import check_paths

SMALL_BUSINESS = BusinessProfile(years=1, customers=8, suppliers=4, invoices_per_month=(5, 8))
SMALL_HOUSEHOLD = HouseholdProfile(months=6)


def rows(content: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(content.decode("utf-8"))))


@pytest.fixture(scope="module")
def business() -> dict[str, bytes]:
    return generate_business(BusinessProfile(), seed=42).all_files()


@pytest.fixture(scope="module")
def household() -> dict[str, bytes]:
    return generate_household(HouseholdProfile(), seed=7).all_files()


# --- determinism ---------------------------------------------------------------------------


def test_same_seed_is_byte_identical() -> None:
    first = generate_business(SMALL_BUSINESS, seed=1)
    second = generate_business(SMALL_BUSINESS, seed=1)
    assert first.all_files() == second.all_files()
    assert first.fingerprint() == second.fingerprint()
    assert generate_household(SMALL_HOUSEHOLD, 3).fingerprint() == (
        generate_household(SMALL_HOUSEHOLD, 3).fingerprint()
    )


def test_different_seed_differs() -> None:
    assert generate_business(SMALL_BUSINESS, 1).fingerprint() != (
        generate_business(SMALL_BUSINESS, 2).fingerprint()
    )


def test_manifest_records_seed_profile_and_hashes(business: dict[str, bytes]) -> None:
    manifest = json.loads(business["manifest.json"])
    assert manifest["synthetic"] is True
    assert "SYNTHETIC DATA" in manifest["disclaimer"]
    assert manifest["seed"] == 42
    assert manifest["profile"]["annual_revenue"] == "1200000.00"
    assert set(manifest["files"]) == set(business) - {"manifest.json"}


# --- fictional identifiers -------------------------------------------------------------------


def test_vat_numbers_have_invalid_check_letters(business: dict[str, bytes]) -> None:
    parties = json.loads(business["counterparties.json"])
    vat_numbers = [p["vat_no"] for p in parties] + [json.loads(business["company.json"])["vat_no"]]
    for vat in vat_numbers:
        assert vat.startswith("CY")
        assert len(vat) == 11
        digits, letter = vat[2:10], vat[10]
        assert digits.isdigit()
        assert cy_vat_check_letter(digits) != letter, f"{vat} is a valid VAT number"


def test_ibans_have_invalid_check_digits(business: dict[str, bytes]) -> None:
    for party in json.loads(business["counterparties.json"]):
        iban = party["iban"]
        assert iban.startswith("CY")
        assert len(iban) == 28
        assert iban_mod97(iban) != 1, f"{iban} is a valid IBAN"


@pytest.mark.parametrize("seed", range(200))
def test_identifier_generators_never_produce_valid_numbers(seed: int) -> None:
    rng = random.Random(seed)  # noqa: S311
    vat = fictional_cy_vat(rng)
    assert cy_vat_check_letter(vat[2:10]) != vat[10]
    assert iban_mod97(fictional_cy_iban(rng)) != 1


def test_check_algorithms_accept_known_valid_examples() -> None:
    # Published specimen values (not real accounts): the standard Cyprus IBAN example and a
    # VAT number constructed with the documented check algorithm.
    assert iban_mod97("CY17002001280000001200527600") == 1
    assert cy_vat_check_letter("10259033") == "P"


def test_names_and_emails_are_marked_fictional(business: dict[str, bytes]) -> None:
    parties = json.loads(business["counterparties.json"])
    assert len({p["name"] for p in parties}) == len(parties)
    for party in parties:
        assert party["name"].endswith("(Demo)")
        assert party["email"].endswith(".example")
    assert json.loads(business["company.json"])["legal_name"].endswith("(Demo)")


# --- business invariants ---------------------------------------------------------------------


def test_annual_revenue_matches_profile_exactly(business: dict[str, bytes]) -> None:
    sales = rows(business["sales_invoices.csv"])
    totals: dict[str, Decimal] = {}
    for s in sales:
        year = s["issue_date"][:4]
        totals[year] = totals.get(year, Decimal(0)) + Decimal(s["net"])
    assert totals["2024"] == Decimal("1200000.00")
    assert totals["2025"] == Decimal("1296000.00")  # +8% growth
    assert totals["2026"] == Decimal("1399680.00")


def test_invoice_arithmetic(business: dict[str, bytes]) -> None:
    for name in ("sales_invoices.csv", "purchase_invoices.csv"):
        for inv in rows(business[name]):
            net, vat, gross = (Money.of(inv[k], "EUR") for k in ("net", "vat", "gross"))
            assert gross == net + vat
            assert vat == net.multiply("0.19").round()
            assert inv["due_date"] >= inv["issue_date"]
            if inv["paid_date"]:
                assert inv["paid_date"] >= inv["issue_date"]


def test_invoice_numbers_are_unique(business: dict[str, bytes]) -> None:
    numbers = [
        i["number"]
        for name in ("sales_invoices.csv", "purchase_invoices.csv")
        for i in rows(business[name])
    ]
    assert len(numbers) == len(set(numbers))


def test_each_paid_invoice_has_one_matching_bank_transaction(business: dict[str, bytes]) -> None:
    bank = rows(business["bank_transactions.csv"])
    by_reference = Counter(t["reference"] for t in bank)
    bank_by_ref = {t["reference"]: t for t in bank}
    for name, sign in (("sales_invoices.csv", 1), ("purchase_invoices.csv", -1)):
        for inv in rows(business[name]):
            if inv["paid_date"]:
                assert by_reference[inv["number"]] == 1
                txn = bank_by_ref[inv["number"]]
                assert Decimal(txn["amount"]) == sign * Decimal(inv["gross"])
                assert txn["date"] == inv["paid_date"]
            else:
                assert by_reference[inv["number"]] == 0


def test_bank_running_balance_reconciles(business: dict[str, bytes]) -> None:
    company = json.loads(business["company.json"])
    balance = Decimal(company["opening_cash"])
    previous_date = ""
    for txn in rows(business["bank_transactions.csv"]):
        balance += Decimal(txn["amount"])
        assert Decimal(txn["balance"]) == balance
        assert txn["date"] >= previous_date
        assert txn["date"] <= company["as_of"]
        assert date.fromisoformat(txn["date"]).weekday() < 5, "bank dates are business days"
        previous_date = txn["date"]


def test_some_receivables_remain_open_for_forecasting(business: dict[str, bytes]) -> None:
    sales = rows(business["sales_invoices.csv"])
    open_items = [s for s in sales if not s["paid_date"]]
    assert 0 < len(open_items) < len(sales) // 10


def test_loan_schedule_repays_principal_exactly(business: dict[str, bytes]) -> None:
    schedule = rows(business["loan_schedule.csv"])
    assert len(schedule) == 60
    assert sum(Decimal(r["principal"]) for r in schedule) == Decimal("250000.00")
    assert schedule[-1]["closing_balance"] == "0.00"


# --- household invariants --------------------------------------------------------------------


def test_household_salary_and_mortgage_each_month(household: dict[str, bytes]) -> None:
    txns = rows(household["transactions.csv"])
    salary_months = Counter(
        t["date"][:7] for t in txns if t["description"] == "Salary (Demo employer)"
    )
    mortgage_months = Counter(
        t["date"][:7] for t in txns if t["description"] == "Mortgage instalment (Demo bank)"
    )
    assert len(salary_months) == 24
    assert set(salary_months.values()) == {1}
    assert len(mortgage_months) == 24
    assert set(mortgage_months.values()) == {1}


def test_household_balances_reconcile_per_account(household: dict[str, bytes]) -> None:
    accounts = {
        a["id"]: Decimal(a["opening_balance"]) for a in json.loads(household["accounts.json"])
    }
    for txn in rows(household["transactions.csv"]):
        accounts[txn["account"]] += Decimal(txn["amount"])
        assert Decimal(txn["balance"]) == accounts[txn["account"]]


def test_savings_transfers_are_balanced_pairs(household: dict[str, bytes]) -> None:
    txns = rows(household["transactions.csv"])
    out = [t for t in txns if t["description"] == "Transfer to savings"]
    into = [t for t in txns if t["description"] == "Transfer from current account"]
    assert len(out) == len(into) == 24
    assert sum(Decimal(t["amount"]) for t in out) == -sum(Decimal(t["amount"]) for t in into)


# --- schedules and profiles ------------------------------------------------------------------


@pytest.mark.parametrize(("rate_bp", "months"), [(0, 12), (550, 60), (420, 300), (1, 1)])
def test_annuity_schedule_properties(rate_bp: int, months: int) -> None:
    principal = Money.of("100000.00", "EUR")
    schedule = annuity_schedule(principal, rate_bp, months, date(2025, 1, 31))
    assert len(schedule) == months
    assert Money.total((i.principal for i in schedule), "EUR") == principal
    assert schedule[-1].closing_balance.is_zero()
    for inst in schedule:
        assert inst.payment == inst.principal + inst.interest
    if months > 1:
        assert schedule[1].due_date == date(2025, 2, 28)  # month-end clamping
    with pytest.raises(ValueError, match="at least 1"):
        annuity_schedule(principal, rate_bp, 0, date(2025, 1, 1))


def test_add_months_handles_year_and_month_end() -> None:
    assert add_months(date(2025, 11, 30), 3) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


@pytest.mark.parametrize(
    "change",
    [
        {"years": 0},
        {"seasonality": (1,) * 11},
        {"gross_margin_bp": 10000},
        {"customers": 0},
        {"invoices_per_month": (5, 2)},
        {"start_date": date(2025, 1, 15)},
        {"monthly_rent": "-1.00"},
    ],
)
def test_invalid_business_profiles_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 - each case has its own message
        replace(BusinessProfile(), **change).validate()  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "change",
    [{"months": 0}, {"salary_day": 31}, {"bonus_month": 13}, {"start_date": date(2025, 1, 2)}],
)
def test_invalid_household_profiles_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        replace(HouseholdProfile(), **change).validate()  # type: ignore[arg-type]


def test_profile_round_trip_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli(["business", "--print-profile"]) == 0
    profile = json.loads(capsys.readouterr().out)
    profile.update({"years": 1, "customers": 5, "suppliers": 3, "annual_revenue": "250000.00"})
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    assert load_business_profile(profile_path).annual_revenue == "250000.00"

    out = tmp_path / "out"
    assert cli(["business", "--profile", str(profile_path), "--seed", "5", "--out", str(out)]) == 0
    assert "Wrote 8 files" in capsys.readouterr().out
    sales = rows((out / "sales_invoices.csv").read_bytes())
    assert sum(Decimal(s["net"]) for s in sales) == Decimal("250000.00")

    assert cli(["household", "--print-profile"]) == 0
    household_profile = json.loads(capsys.readouterr().out)
    household_profile["months"] = 3
    hp = tmp_path / "household.json"
    hp.write_text(json.dumps(household_profile))
    assert load_household_profile(hp).months == 3
    assert cli(["household", "--profile", str(hp), "--out", str(tmp_path / "h")]) == 0


def test_unknown_profile_fields_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"annual_revenu": "1.00"}))
    with pytest.raises(ValueError, match="Unknown profile fields: annual_revenu"):
        load_business_profile(path)


def test_cli_requires_out(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli(["business"])
    assert "--out is required" in capsys.readouterr().err


def test_generator_code_uses_no_floating_point() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "fcp" / "devtools"
    assert check_paths([package]) == []
