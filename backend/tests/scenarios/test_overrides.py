"""The eight typed overrides (M7-1, AC-SC1): valid parameters are normalised; every problem is
refused against its parameter, in plain words; nothing outside the base's horizon is accepted."""

from datetime import date
from typing import Any

import pytest

from fcp.core.errors import ValidationFailedError
from fcp.modules.projections.api import OPEX_LINES, REVENUE_LINES
from fcp.modules.scenarios.overrides import TYPES, Base, clean

BASE = Base(
    months=[date(2027, m, 1) for m in range(1, 13)],
    loan_codes=frozenset({"TERM-1"}),
    revenue_lines=REVENUE_LINES,
    opex_lines=OPEX_LINES,
)

VALID: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "PCT_CHANGE",
        {
            "driver": "revenue",
            "lines": ["REV.SERVICES", "REV.SALES"],
            "percent": "-15",
            "start_month": "2027-03",
        },
        {
            "driver": "revenue",
            "lines": ["REV.SALES", "REV.SERVICES"],
            "percent": "-15",
            "start_month": "2027-03-01",
            "end_month": "2027-12-01",
        },
    ),
    (
        "PCT_CHANGE",
        {"driver": "opex", "percent": "12.5"},
        {
            "driver": "opex",
            "lines": [],
            "percent": "12.5",
            "start_month": "2027-01-01",
            "end_month": "2027-12-01",
        },
    ),
    (
        "ABS_CHANGE",
        {
            "driver": "opex",
            "line": "OPEX.PAYROLL",
            "amount": "8000",
            "start_month": "2027-02-01",
            "end_month": "2027-06",
        },
        {
            "driver": "opex",
            "line": "OPEX.PAYROLL",
            "amount": "8000.00",
            "start_month": "2027-02-01",
            "end_month": "2027-06-01",
        },
    ),
    (
        "TIMING_SHIFT",
        {"driver": "dso", "days": 60},
        {
            "mode": "DAYS",
            "driver": "dso",
            "days": 60,
            "start_month": "2027-01-01",
            "end_month": "2027-12-01",
        },
    ),
    (
        "TIMING_SHIFT",
        {"mode": "MONTHS", "driver": "revenue", "line": "REV.SALES", "months": "-2"},
        {
            "mode": "MONTHS",
            "driver": "revenue",
            "line": "REV.SALES",
            "months": -2,
            "start_month": "2027-01-01",
            "end_month": "2027-12-01",
        },
    ),
    (
        "NEW_DEBT",
        {
            "code": "new-1",
            "amount": "200000",
            "drawdown_month": "2027-04",
            "term_months": 60,
            "annual_rate": "6.5",
        },
        {
            "code": "NEW-1",
            "name": "",
            "amount": "200000.00",
            "drawdown_month": "2027-04-01",
            "term_months": 60,
            "annual_rate": "6.5",
            "structure": "ANNUITY",
            "interest_only_months": 0,
        },
    ),
    (
        "NEW_HIRE",
        {
            "role": "Sales assistant",
            "headcount": 2,
            "gross_monthly_salary": "2100",
            "employer_cost_percent": "12",
            "employer_cost_source": "Payroll adviser letter",
            "start_month": "2027-03",
        },
        {
            "role": "Sales assistant",
            "department": "",
            "headcount": 2,
            "gross_monthly_salary": "2100.00",
            "employer_cost_percent": "12",
            "employer_cost_source": "Payroll adviser letter",
            "start_month": "2027-03-01",
            "end_month": "2027-12-01",
        },
    ),
    (
        "CAPEX",
        {
            "amount": "150000",
            "month": "2027-05",
            "useful_life_months": 96,
            "funding": "LOAN",
            "term_months": 48,
            "annual_rate": "5",
            "structure": "BULLET",
        },
        {
            "amount": "150000.00",
            "month": "2027-05-01",
            "useful_life_months": 96,
            "funding": "LOAN",
            "term_months": 48,
            "annual_rate": "5",
            "structure": "BULLET",
        },
    ),
    (
        "ONE_OFF",
        {
            "amount": "40000",
            "month": "2027-07",
            "treatment": "LIABILITY_SETTLEMENT",
            "liability": "BS.TAX_PAY",
        },
        {
            "amount": "40000.00",
            "month": "2027-07-01",
            "treatment": "LIABILITY_SETTLEMENT",
            "liability": "BS.TAX_PAY",
        },
    ),
    (
        "ONE_OFF",
        {"amount": "999.99", "month": "2027-01", "treatment": "EXPENSE"},
        {"amount": "999.99", "month": "2027-01-01", "treatment": "EXPENSE", "line": "OPEX.OTHER"},
    ),
    (
        "RATE_CHANGE",
        {"target": "LOANS", "loans": ["TERM-1"], "points": "2", "from_month": "2027-06"},
        {"target": "LOANS", "loans": ["TERM-1"], "points": "2", "from_month": "2027-06-01"},
    ),
    (
        "RATE_CHANGE",
        {"target": "ALL", "points": "-0.5"},
        {"target": "ALL", "points": "-0.5", "from_month": "2027-01-01"},
    ),
]


@pytest.mark.parametrize(("kind", "raw", "expected"), VALID)
def test_valid_overrides_are_normalised(
    kind: str, raw: dict[str, Any], expected: dict[str, Any]
) -> None:
    assert clean(kind, raw, BASE) == expected
    assert clean(kind, expected, BASE) == expected  # normalised parameters are stable


def test_every_type_is_covered() -> None:
    assert {kind for kind, _, _ in VALID} == set(TYPES)


INVALID: list[tuple[str, dict[str, Any], str, str]] = [
    ("MAGIC", {}, "type", "choose one of"),
    ("PCT_CHANGE", {"driver": "capex", "percent": "5"}, "params.driver", "choose one of"),
    ("PCT_CHANGE", {"driver": "revenue", "percent": "0"}, "params.percent", "must not be 0"),
    ("PCT_CHANGE", {"driver": "revenue", "percent": "-101"}, "params.percent", "-100 to 1000"),
    ("PCT_CHANGE", {"driver": "revenue", "percent": 5.5}, "params.percent", "number"),
    (
        "PCT_CHANGE",
        {"driver": "revenue", "lines": ["OPEX.RENT"], "percent": "5"},
        "params.lines",
        "choose from",
    ),
    (
        "PCT_CHANGE",
        {"driver": "revenue", "lines": ["REV.SALES", "REV.SALES"], "percent": "5"},
        "params.lines",
        "choose from",
    ),
    (
        "PCT_CHANGE",
        {"driver": "revenue", "percent": "5", "start_month": "2028-01"},
        "params.start_month",
        "outside the base's horizon (01/2027 to 12/2027)",
    ),
    (
        "PCT_CHANGE",
        {"driver": "revenue", "percent": "5", "start_month": "2027-06", "end_month": "2027-02"},
        "params.end_month",
        "not be before",
    ),
    (
        "PCT_CHANGE",
        {"driver": "revenue", "percent": "5", "start_month": "2027-13"},
        "params.start_month",
        "such as 2027-03",
    ),
    (
        "PCT_CHANGE",
        {"driver": "revenue", "percent": "5", "colour": "red"},
        "params.colour",
        "not a parameter",
    ),
    (
        "ABS_CHANGE",
        {"driver": "opex", "line": "OPEX.RENT", "amount": "10.001"},
        "params.amount",
        "2 decimals",
    ),
    (
        "ABS_CHANGE",
        {"driver": "opex", "line": "REV.SALES", "amount": "10"},
        "params.line",
        "choose one of",
    ),
    ("TIMING_SHIFT", {"driver": "dso", "days": 0}, "params.days", "must not be 0"),
    ("TIMING_SHIFT", {"driver": "dso", "days": 400}, "params.days", "-365 to 365"),
    ("TIMING_SHIFT", {"driver": "dso", "days": True}, "params.days", "whole number"),
    (
        "TIMING_SHIFT",
        {"mode": "MONTHS", "driver": "revenue", "line": "REV.SALES", "months": 13},
        "params.months",
        "-12 to 12",
    ),
    (
        "NEW_DEBT",
        {
            "code": "TERM-1",
            "amount": "1",
            "drawdown_month": "2027-01",
            "term_months": 12,
            "annual_rate": "5",
        },
        "params.code",
        "already has a loan",
    ),
    (
        "NEW_DEBT",
        {
            "code": "bad code!",
            "amount": "1",
            "drawdown_month": "2027-01",
            "term_months": 12,
            "annual_rate": "5",
        },
        "params.code",
        "letters, digits",
    ),
    (
        "NEW_DEBT",
        {
            "code": "N",
            "amount": "1",
            "drawdown_month": "2027-01",
            "term_months": 12,
            "annual_rate": "5",
            "interest_only_months": 12,
        },
        "params.interest_only_months",
        "fewer than",
    ),
    (
        "NEW_DEBT",
        {
            "code": "N",
            "amount": "0",
            "drawdown_month": "2027-01",
            "term_months": 12,
            "annual_rate": "5",
        },
        "params.amount",
        "0.01 to",
    ),
    (
        "NEW_HIRE",
        {"role": "Analyst", "gross_monthly_salary": "3000", "employer_cost_percent": "12"},
        "params.employer_cost_source",
        "the platform holds no social-insurance rate",
    ),
    ("NEW_HIRE", {"role": " ", "gross_monthly_salary": "3000"}, "params.role", "required"),
    (
        "CAPEX",
        {"amount": "1000", "month": "2027-01", "useful_life_months": 0},
        "params.useful_life_months",
        "1 to 1200",
    ),
    (
        "CAPEX",
        {"amount": "1000", "month": "2027-01", "useful_life_months": 60, "funding": "LOAN"},
        "params.term_months",
        "whole number",
    ),
    (
        "ONE_OFF",
        {
            "amount": "10",
            "month": "2027-01",
            "treatment": "LIABILITY_SETTLEMENT",
            "liability": "BS.CASH",
        },
        "params.liability",
        "choose one of",
    ),
    (
        "ONE_OFF",
        {"amount": "-10", "month": "2027-01", "treatment": "EXPENSE"},
        "params.amount",
        "0.01 to",
    ),
    (
        "RATE_CHANGE",
        {"target": "LOANS", "loans": ["OTHER"], "points": "1"},
        "params.loans",
        "TERM-1",
    ),
    ("RATE_CHANGE", {"target": "ALL", "points": "25"}, "params.points", "-20 to 20"),
]


@pytest.mark.parametrize(("kind", "raw", "field", "message"), INVALID)
def test_problems_are_refused_against_their_parameter(
    kind: str, raw: dict[str, Any], field: str, message: str
) -> None:
    with pytest.raises(ValidationFailedError) as refused:
        clean(kind, raw, BASE)
    assert list(refused.value.field_errors) == [field], refused.value.field_errors
    assert message in refused.value.detail, refused.value.detail


def test_params_must_be_an_object() -> None:
    with pytest.raises(ValidationFailedError, match="expected an object"):
        clean("PCT_CHANGE", ["revenue"], BASE)
    with pytest.raises(ValidationFailedError, match="enter text"):
        clean("NEW_HIRE", {"role": 5, "gross_monthly_salary": "1"}, BASE)
    no_loans = Base(BASE.months, frozenset(), REVENUE_LINES, OPEX_LINES)
    with pytest.raises(ValidationFailedError, match="it has none"):
        clean("RATE_CHANGE", {"target": "LOANS", "loans": ["X"], "points": "1"}, no_loans)
