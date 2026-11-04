"""Natures, series and canonical hashing (M3-2, AC-CF1, AC-CF2, doc 10 P2-P4)."""

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st
from mypy import api as mypy_api

from fcp.modules.metrics.api import (
    ActualSeries,
    BlendedSeries,
    Nature,
    NatureMixError,
    PlanSeries,
    Point,
    blend,
)
from fcp.modules.metrics.hashing import canonical, canonical_decimal, digest

JAN, FEB, MAR = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)


def test_actuals_add_only_to_actuals() -> None:
    a = ActualSeries({JAN: Decimal("10"), FEB: Decimal("20")})
    b = ActualSeries({FEB: Decimal("5"), MAR: Decimal("1")})
    assert (a + b).values == {JAN: Decimal("10"), FEB: Decimal("25"), MAR: Decimal("1")}
    assert (a - b).values[FEB] == Decimal("15")
    assert a.total() == Decimal("30")
    assert [p.nature for p in a.points()] == [Nature.ACTUAL, Nature.ACTUAL]
    plan = PlanSeries(Nature.FORECAST, {MAR: Decimal("7")})
    with pytest.raises(NatureMixError, match="blend"):
        a + plan  # type: ignore[operator]
    with pytest.raises(NatureMixError):
        plan + a  # type: ignore[operator]
    with pytest.raises(NatureMixError):
        a - plan  # type: ignore[operator]


def test_plans_add_only_to_the_same_nature() -> None:
    committed = PlanSeries(Nature.COMMITTED, {JAN: Decimal("1")})
    expected = PlanSeries(Nature.EXPECTED, {JAN: Decimal("2")})
    assert (committed + committed).values == {JAN: Decimal("2")}
    with pytest.raises(NatureMixError, match="COMMITTED with EXPECTED"):
        committed + expected
    combined = committed.relabel(Nature.FORECAST) + expected.relabel(Nature.FORECAST)
    assert combined.nature is Nature.FORECAST
    assert combined.values == {JAN: Decimal("3")}
    with pytest.raises(NatureMixError, match="cannot be ACTUAL"):
        PlanSeries(Nature.ACTUAL, {})


def test_series_are_decimal_and_immutable() -> None:
    with pytest.raises(TypeError, match="Decimal"):
        ActualSeries({JAN: 1.5})  # type: ignore[arg-type]
    series = ActualSeries([(FEB, Decimal("2")), (JAN, Decimal("1"))])
    assert series.periods() == [JAN, FEB]
    with pytest.raises(AttributeError, match="immutable"):
        series._items = ()
    values = series.values
    values[MAR] = Decimal("3")
    assert MAR not in series.values
    assert series == ActualSeries({JAN: Decimal("1"), FEB: Decimal("2")})
    assert series != PlanSeries(Nature.BUDGET, series.values)
    assert len({series, ActualSeries(series.values)}) == 1
    assert "ActualSeries" in repr(series)
    budget = PlanSeries(Nature.BUDGET, series.values)
    assert budget == PlanSeries(Nature.BUDGET, series.values)
    assert budget != budget.relabel(Nature.TARGET)
    assert len({budget, budget.relabel(Nature.BUDGET)}) == 1
    assert "BUDGET" in repr(budget)


def test_blend_keeps_each_points_nature() -> None:
    actual = ActualSeries({JAN: Decimal("10"), FEB: Decimal("20"), MAR: Decimal("99")})
    plan = PlanSeries(Nature.FORECAST, {JAN: Decimal("-1"), MAR: Decimal("30")})
    blended = blend(actual, plan, MAR)
    assert blended.points == (
        Point(JAN, Decimal("10"), Nature.ACTUAL),
        Point(FEB, Decimal("20"), Nature.ACTUAL),
        Point(MAR, Decimal("30"), Nature.FORECAST),
    )
    assert blended.total() == Decimal("60")
    with pytest.raises(NatureMixError, match="no arithmetic"):
        blended + blended
    with pytest.raises(NatureMixError, match="takes an ActualSeries"):
        blend(plan, actual, MAR)  # type: ignore[arg-type]
    assert isinstance(blended, BlendedSeries)


amounts = st.decimals(min_value=-(10**12), max_value=10**12, places=2, allow_nan=False)
periods = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31))


@given(st.dictionaries(periods, amounts, max_size=30), st.dictionaries(periods, amounts,
       max_size=30), periods)  # fmt: skip
def test_blend_takes_each_period_from_exactly_one_side(
    a: dict[date, Decimal], p: dict[date, Decimal], cutover: date
) -> None:
    blended = blend(ActualSeries(a), PlanSeries(Nature.FORECAST, p), cutover)
    expected = sum((v for d, v in a.items() if d < cutover), Decimal(0)) + sum(
        (v for d, v in p.items() if d >= cutover), Decimal(0)
    )
    assert blended.total() == expected
    assert all((pt.nature is Nature.ACTUAL) == (pt.period < cutover) for pt in blended.points)


def test_mypy_rejects_actual_plus_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-CF2: the mix is a type error, not only a runtime error."""
    monkeypatch.setenv("MYPYPATH", str(Path(__file__).resolve().parents[2] / "src"))
    snippet = tmp_path / "mix.py"
    snippet.write_text(
        "from datetime import date\n"
        "from decimal import Decimal\n"
        "from fcp.modules.metrics.nature import ActualSeries, Nature, PlanSeries\n"
        "a = ActualSeries({date(2026, 1, 1): Decimal(1)})\n"
        "p = PlanSeries(Nature.FORECAST, {date(2026, 1, 1): Decimal(1)})\n"
        "ok = a + a\n"
        "bad = a + p\n"
        "worse = p + a\n"
    )
    out, _, status = mypy_api.run([
        str(snippet), "--strict", "--follow-imports=silent", "--config-file", "",
        "--cache-dir", str(tmp_path / "cache"),
    ])  # fmt: skip
    assert status == 1, out
    assert (
        'mix.py:7: error: Unsupported operand types for + ("ActualSeries" and "PlanSeries")' in out
    )
    assert (
        'mix.py:8: error: Unsupported operand types for + ("PlanSeries" and "ActualSeries")' in out
    )
    assert "mix.py:6" not in out


# --- canonical hashing ----------------------------------------------------------------------------


def test_canonical_form_is_independent_of_order_and_scale() -> None:
    assert digest({"b": Decimal("1.50"), "a": [1, "x"]}) == digest(
        {"a": [1, "x"], "b": Decimal("1.5")}
    )
    assert digest({"v": Decimal("1.5")}) != digest({"v": "1.5"})
    assert canonical_decimal(Decimal("-0.00")) == "0"
    assert canonical_decimal(Decimal("1E+3")) == "1000"
    wide = Decimal("1234567890123456789012.1234567890123456789012345678")
    assert canonical_decimal(wide) == str(wide)  # 50 digits: never rounded to 28
    assert canonical_decimal(Decimal("12.3400")) == "12.34"
    assert canonical(
        {"d": date(2026, 1, 2), "n": Nature.ACTUAL, "u": UUID(int=1), "z": None, "t": True}
    ) == (
        b'{"d":{"$date":"2026-01-02"},"n":"ACTUAL","t":true,'
        b'"u":"00000000-0000-0000-0000-000000000001","z":null}'
    )


@pytest.mark.parametrize(
    ("value", "error"),
    [
        (1.5, "floats"),
        (datetime(2026, 1, 1, tzinfo=UTC), "dates, not datetimes"),
        (Decimal("NaN"), "finite"),
        ({1, 2}, "cannot hash a set"),
    ],
)
def test_canonical_form_refuses_unsafe_values(value: object, error: str) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        digest({"v": value})


@given(st.decimals(allow_nan=False, allow_infinity=False, places=None))
def test_equal_decimals_hash_equally(value: Decimal) -> None:
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    padded = Decimal((sign, (*digits, 0, 0), exponent - 2))  # same number, two trailing zeros
    assert padded == value
    assert digest(value) == digest(padded)
    assert Decimal(canonical_decimal(value)) == value


def test_the_api_schema_requires_a_nature_on_every_value() -> None:
    """AC-CF1: the published OpenAPI document (kept current by ``make openapi-check``)."""
    spec = json.loads((Path(__file__).resolve().parents[3] / "docs/api/openapi.json").read_text())
    result = spec["components"]["schemas"]["ResultOut"]
    assert "nature" in result["required"]
    assert set(spec["components"]["schemas"]["Nature"]["enum"]) == {n.value for n in Nature}


def test_plan_subtraction_and_non_string_enums() -> None:
    a = PlanSeries(Nature.BUDGET, {JAN: Decimal("5")})
    assert (a - a).values == {JAN: Decimal("0")}

    class Level(Enum):
        HIGH = "high"

    assert canonical({"level": Level.HIGH}) == b'{"level":"high"}'
