"""The sandboxed expression language (M3-3, AC-CF5, doc 10 §2.2)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fcp.modules.metrics import calc as calc_module
from fcp.modules.metrics.api import Nature, Output, Source, formula_value
from fcp.modules.metrics.expr import (
    BOOL,
    KEY,
    MAX_DEPTH,
    MAX_LENGTH,
    MAX_TOKENS,
    PERIOD,
    EvaluationError,
    ExpressionError,
    Function,
    NotMeaningful,
    Param,
    Type,
    compile_expression,
    evaluate,
    scalar,
    series,
)

D = Decimal
VARIABLES: dict[str, Type] = {
    "revenue": scalar("EUR"), "cost": scalar("EUR"), "ar": scalar("EUR"), "equity": scalar("EUR"),
    "margin": scalar("ratio"), "growth": scalar("percent"), "headcount": scalar("count"),
    "dso": scalar("days"), "turns": scalar("times"), "flag": BOOL, "add_backs": series("EUR"),
    "period": PERIOD,
}  # fmt: skip
VALUES: dict[str, Any] = {
    "revenue": D("1000"), "cost": D("600"), "ar": D("250"), "equity": D("-50"),
    "margin": D("0.4"), "growth": D("0.15"), "headcount": D("4"), "dso": D("30"),
    "turns": D("6"), "flag": True, "add_backs": [D("10"), D("2.5")],
    "period": (date(2026, 1, 1), date(2026, 12, 31)),
}  # fmt: skip
CALLS: list[tuple[str, Any]] = []


def _metric(key: str, period: Any) -> Decimal:
    CALLS.append((key, period))
    return {"REV.SALES": D("1200"), "COGS": D("0")}.get(key, D("7"))


def _days(period: Any) -> Decimal:
    return D((period[1] - period[0]).days + 1)


FUNCTIONS = (
    Function("metric", (Param("key", KEY), Param("period", PERIOD)), scalar("EUR"), _metric),
    Function("balance", (Param("key", KEY), Param("at", PERIOD, optional=True)), scalar("EUR"),
             lambda key, at=None: D("300")),
    Function("days", (Param("period", PERIOD),), scalar("days"), _days),
    Function("driver", (Param("name", KEY),), scalar("count"), lambda name: D("12")),
    Function("weird", (), scalar("EUR"), lambda: 1.5),
    Function("missing", (), scalar("EUR"), lambda: NotMeaningful("no data")),
    Function("scaled", (Param("x", scalar("EUR")),), scalar("EUR"), lambda x: x * 2),
)  # fmt: skip


def calc(source: str, **overrides: Any) -> Any:
    compiled = compile_expression(source, VARIABLES, FUNCTIONS)
    return evaluate(compiled, {**VALUES, **overrides}).value


def unit(source: str) -> str:
    return compile_expression(source, VARIABLES, FUNCTIONS).unit


def error(source: str, variables: dict[str, Type] | None = None) -> ExpressionError:
    with pytest.raises(ExpressionError) as caught:
        compile_expression(source, VARIABLES if variables is None else variables, FUNCTIONS)
    return caught.value


# --- arithmetic -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("0.1 + 0.2", D("0.3")),
        ("1 + 2 * 3", D("7")),
        ("(1 + 2) * 3", D("9")),
        ("10 - 2 - 3", D("5")),
        ("8 / 2 / 2", D("2")),
        ("-2 * 3", D("-6")),
        ("--2", D("2")),
        ("1 / 3", D("0.3333333333333333333333333333")),
        ("revenue - cost", D("400")),
        ("revenue * margin", D("400.0")),
        ("sum(add_backs)", D("12.5")),
        ("abs(equity)", D("50")),
        ("min(revenue, cost, 700)", D("600")),
        ("max(dso, 45)", D("45")),
        ("round(1.005, 2)", D("1.01")),
        ("round(2.5, 0)", D("3")),
        ("round(1.234)", D("1.23")),
        ("round(1.25, places=1)", D("1.3")),
        ("if(revenue > cost, revenue, cost)", D("1000")),
        ("if(flag and not (dso > 60), 1, 2)", D("1")),
        ("revenue >= 1000 and cost != 600 or headcount == 4", True),
        ("not flag", False),
        ("false and revenue / 0 > 1", False),  # short-circuit: the right side is not evaluated
        ("true or revenue / 0 > 1", True),
        ("if(flag, true, false)", True),
        ("divide_positive(revenue, 4)", D("250")),
        ("ar / revenue * days(period)", D("91.25")),
        ('metric("REV.SALES", period) - metric("COGS", period)', D("1200")),
        ('balance("BS.AR", at=period) + balance("BS.AR")', D("600")),
        ('driver("headcount") * 4', D("48")),
        ("scaled(revenue)", D("2000")),
    ],
)
def test_evaluation(source: str, expected: object) -> None:
    result = calc(source)
    assert result == expected
    assert type(result) is type(expected)


def test_results_are_decimal_never_float() -> None:
    assert isinstance(calc("revenue * 1.1"), Decimal)
    assert calc("revenue * 1.1") == D("1100.0")


def test_reference_calls_are_recorded_for_lineage() -> None:
    compiled = compile_expression('metric("REV.SALES", period) / revenue', VARIABLES, FUNCTIONS)
    assert compiled.variables == frozenset({"period", "revenue"})
    result = evaluate(compiled, VALUES)
    assert result.unit == "ratio"
    assert result.calls == (
        "metric(key=REV.SALES, period=(datetime.date(2026, 1, 1), datetime.date(2026, 12, 31)))",
    )
    assert result.meaningful


# --- units ----------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("revenue + cost", "EUR"),
        ("revenue * margin", "EUR"),
        ("margin * revenue", "EUR"),
        ("revenue * growth", "EUR"),
        ("revenue / revenue", "ratio"),
        ("revenue / 12", "EUR"),
        ("revenue / headcount", "EUR"),
        ('driver("x") * margin', "count"),
        ("headcount * revenue", "EUR"),
        ("ar / revenue * 365", "ratio"),
        ("ar / revenue * days(period)", "days"),
        ("dso * margin", "days"),
        ("margin * growth", "percent"),
        ("margin * margin", "ratio"),
        ("2 * 3", "number"),
        ("revenue + 5", "EUR"),
        ("turns / turns", "ratio"),
        ("if(flag, revenue, 0)", "EUR"),
        ("revenue > cost", "bool"),
        ("-revenue", "EUR"),
    ],
)
def test_units(source: str, expected: str) -> None:
    assert unit(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "revenue + dso",
        "revenue * revenue",
        "revenue * dso",
        "dso / revenue",
        "12 / revenue",
        "margin + growth",
        "revenue > dso",
        "min(revenue, dso)",
        "if(flag, revenue, dso)",
        "revenue / dso",
        "headcount * headcount",
        "divide_positive(revenue, dso)",
    ],
)
def test_unit_mismatches_are_rejected_before_evaluation(source: str) -> None:
    assert error(source).code == "expr.unit"


@pytest.mark.parametrize(
    "source",
    [
        "flag + 1",
        "-flag",
        "not revenue",
        "revenue and flag",
        "if(revenue, 1, 2)",
        "sum(revenue)",
        "add_backs + 1",
        '"REV.SALES"',
        '"x" + 1',
        "abs(flag)",
        "round(flag)",
        "min(flag, 1)",
        "metric(1, period)",
        'metric("X", revenue)',
        "scaled(dso)",
        "scaled(flag)",
        "period",
        "flag < 1",
        "divide_positive(flag, 1)",
        "divide_positive(1, flag)",
    ],
)
def test_type_errors(source: str) -> None:
    assert error(source).code == "expr.type"


# --- not meaningful -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "reason"),
    [
        ("revenue / 0", "denominator zero"),
        ("revenue / (cost - 600)", "denominator zero"),
        ("(revenue / 0) + 1", "denominator zero"),
        ("-(revenue / 0)", "denominator zero"),
        ("revenue / 0 > 1", "denominator zero"),
        ("revenue / 0 > 1 and flag", "denominator zero"),
        ("not (revenue / 0 > 1)", "denominator zero"),
        ("if(revenue / 0 > 1, 1, 2)", "denominator zero"),
        ("min(revenue / 0, 1)", "denominator zero"),
        ("round(revenue / 0, 2)", "denominator zero"),
        ("scaled(revenue / 0)", "denominator zero"),
        ("divide_positive(revenue, equity)", "denominator not positive"),
        ("divide_positive(revenue, 0)", "denominator not positive"),
        ("missing() + 1", "no data"),
        ("round(1000000000000000000000000000, 10)", "out of range"),
    ],
)
def test_not_meaningful_never_zero_or_infinite(source: str, reason: str) -> None:
    assert calc(source) == NotMeaningful(reason)


def test_not_meaningful_inputs_propagate() -> None:
    assert calc("revenue + 1", revenue=NotMeaningful("unmapped")) == NotMeaningful("unmapped")
    assert calc("sum(add_backs)", add_backs=[D(1), NotMeaningful("gap")]) == NotMeaningful("gap")
    assert not evaluate(compile_expression("1 / 0")).meaningful


def test_bad_values_are_refused_at_evaluation() -> None:
    with pytest.raises(EvaluationError, match="no value for 'revenue'"):
        evaluate(compile_expression("revenue", VARIABLES), {})
    with pytest.raises(EvaluationError, match="must be EUR, not float"):
        calc("revenue", revenue=1.5)
    with pytest.raises(EvaluationError, match="must be EUR"):
        calc("revenue", revenue=D("Infinity"))
    with pytest.raises(EvaluationError, match="weird\\(\\) must be EUR, not float"):
        calc("weird()")
    with pytest.raises(EvaluationError, match="must be bool"):
        calc("flag", flag=D(1))
    with pytest.raises(EvaluationError, match="must be period"):
        calc("days(period)", period=D(1))


# --- syntax, names and limits ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "code", "position"),
    [
        ("1 +", "expr.syntax", 3),
        ("(1", "expr.syntax", 2),
        ("1 2", "expr.syntax", 2),
        ("revenue < cost < 1", "expr.syntax", 15),
        ("revenue @ 2", "expr.syntax", 8),
        ("revenue.amount", "expr.syntax", 7),
        ('__import__("os")', "expr.unknown_function", 0),
        ('eval("1")', "expr.unknown_function", 0),
        ("revenu + 1", "expr.unknown_name", 0),
        ("min(1)", "expr.arguments", 0),
        ("if(flag, 1)", "expr.arguments", 0),
        ("abs(1, 2)", "expr.arguments", 0),
        ("sum()", "expr.arguments", 0),
        ("min(a=1, b=2)", "expr.arguments", 0),
        ("round(1.5, 1.5)", "expr.arguments", 0),
        ("round(1.5, 11)", "expr.arguments", 0),
        ("round(1.5, headcount)", "expr.arguments", 0),
        ("round(1.5, digits=1)", "expr.arguments", 0),
        ("round(1.5, 1, 2)", "expr.arguments", 0),
        ("round()", "expr.arguments", 0),
        ('metric("X")', "expr.arguments", 0),
        ('metric("X", period, period)', "expr.arguments", 0),
        ('metric("X", when=period)', "expr.arguments", 0),
        ('metric(key="X", key="Y")', "expr.syntax", 0),
        ('metric(key="X", period)', "expr.syntax", 16),
        ('metric("X", key="Y", period=period)', "expr.arguments", 0),
        ('"unterminated', "expr.syntax", 0),
        ('"semi;colon"', "expr.syntax", 0),
        ("", "expr.syntax", 0),
    ],
)
def test_invalid_formulas(source: str, code: str, position: int) -> None:
    caught = error(source)
    assert caught.code == code, caught
    assert caught.position == position, caught


def test_limits() -> None:
    assert error("1" + " " * MAX_LENGTH).code == "expr.too_large"
    assert error("+".join(["1"] * (MAX_TOKENS // 2 + 1))).code == "expr.too_large"
    assert error("(" * (MAX_DEPTH + 1) + "1" + ")" * (MAX_DEPTH + 1)).code == "expr.too_large"
    assert error("-" * (MAX_DEPTH + 1) + "1").code == "expr.too_large"
    assert error("not " * (MAX_DEPTH + 1) + "true").code == "expr.too_large"
    assert error("1" * 29).code == "expr.too_large"
    assert error("0." + "0" * 30 + "1").code == "expr.too_large"
    assert calc("0" * 40 + "1") == D(1)  # leading zeros are not digits
    assert error("max(" + ",".join(["1"] * 21) + ")").code == "expr.too_large"
    assert calc("(" * (MAX_DEPTH - 1) + "1" + ")" * (MAX_DEPTH - 1)) == D(1)
    with pytest.raises(ExpressionError, match="must be text"):
        compile_expression(123)  # type: ignore[arg-type]


def test_reserved_names_and_units() -> None:
    with pytest.raises(ValueError, match="reserved"):
        compile_expression("1", {}, (Function("min", (), scalar("EUR"), lambda: D(1)),))
    with pytest.raises(ValueError, match="unknown unit"):
        scalar("USD")
    with pytest.raises(ValueError, match="unknown unit"):
        series("kg")
    assert str(series("EUR")) == "list[EUR]"
    assert str(BOOL) == "bool"


# --- fuzzing (AC-CF5: at least 10,000 cases, never a crash) ---------------------------------------

_ALPHABET = st.sampled_from([
    "revenue", "cost", "margin", "dso", "flag", "add_backs", "period", "headcount", "nope",
    "min", "max", "abs", "round", "if", "sum", "divide_positive", "metric", "balance", "days",
    "scaled", "missing", "and", "or", "not", "true", "false", '"REV.SALES"', '"', "0", "1", "2.5",
    "0.0", "99999999999999999999999999", "+", "-", "*", "/", "(", ")", ",", "=", "<", "<=", ">",
    ">=", "==", "!=", " ", "@", ".", "places", "at",
])  # fmt: skip
_FUZZ_VALUES = st.fixed_dictionaries({
    "revenue": st.sampled_from([D(0), D(-1), D("1E+20"), D("0.001"), NotMeaningful("x")]),
    "cost": st.sampled_from([D(0), D("12.34"), D("-1E+27")]),
    "margin": st.sampled_from([D(0), D("0.5")]),
    "dso": st.just(D(30)), "headcount": st.sampled_from([D(0), D(3)]),
    "flag": st.booleans(),
    "add_backs": st.lists(st.sampled_from([D(1), D(0), D("-2.5")]), max_size=3),
})  # fmt: skip


@settings(max_examples=10_000, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_ALPHABET, max_size=40).map("".join), _FUZZ_VALUES)
def test_fuzzed_formulas_never_crash(source: str, values: dict[str, Any]) -> None:
    try:
        compiled = compile_expression(source, VARIABLES, FUNCTIONS[:-3] + FUNCTIONS[-2:])
    except ExpressionError:
        return
    result = evaluate(compiled, {**VALUES, **values})
    assert isinstance(result.value, (Decimal, bool, NotMeaningful))


@settings(max_examples=2_000, deadline=None)
@given(st.text(max_size=300))
def test_arbitrary_text_never_crashes(source: str) -> None:
    try:
        compiled = compile_expression(source, VARIABLES, FUNCTIONS)
    except ExpressionError:
        return
    evaluate(compiled, VALUES)


_LEAVES = st.sampled_from(["revenue", "cost", "1", "0", "2.5", "headcount", "margin"])


def _combine(children: st.SearchStrategy[str]) -> st.SearchStrategy[str]:
    binary = st.tuples(children, st.sampled_from(["+", "-", "*", "/"]), children).map(
        lambda t: f"({t[0]} {t[1]} {t[2]})"
    )
    calls = st.tuples(st.sampled_from(["min", "max"]), children, children).map(
        lambda t: f"{t[0]}({t[1]}, {t[2]})"
    )
    return st.one_of(binary, calls, children.map(lambda c: f"-{c}"),
                     children.map(lambda c: f"round({c}, 2)"))  # fmt: skip


@settings(max_examples=2_000, deadline=None)
@given(st.recursive(_LEAVES, _combine, max_leaves=12))
def test_generated_valid_formulas_evaluate_or_are_rejected_cleanly(source: str) -> None:
    try:
        compiled = compile_expression(source, VARIABLES, FUNCTIONS)
    except ExpressionError as caught:
        code = caught.code
    else:
        code = ""
        result = evaluate(compiled, VALUES)
        assert isinstance(result.value, (Decimal, NotMeaningful))
    assert code in ("", "expr.unit", "expr.too_large")


# --- into calculation runs ------------------------------------------------------------------------


def test_formula_values_carry_reason_and_lineage() -> None:
    day = date(2026, 3, 31)
    formula = compile_expression('metric("REV.SALES", period) / revenue', VARIABLES, FUNCTIONS)
    value = formula_value("kpi.x", day, Nature.ACTUAL, "formula:x@1", evaluate(formula, VALUES),
                          lineage=(Source("ACTUAL", "account:1"),))  # fmt: skip
    assert (value.value, value.unit, value.nm_reason) == (D("1.2"), "ratio", "")
    assert [s.kind for s in value.lineage] == ["FORMULA", "FORMULA", "ACTUAL"]
    assert value.lineage[1].ref.startswith("metric(key=REV.SALES")
    nm = formula_value("kpi.y", day, Nature.FORECAST, "formula:y@1",
                       evaluate(compile_expression("revenue / 0", VARIABLES), VALUES))  # fmt: skip
    assert (nm.value, nm.nm_reason) == (None, "denominator zero")
    calc_module._check(Output((value, nm)))  # both are storable
    with pytest.raises(calc_module.EngineOutputError, match="true/false"):
        formula_value("kpi.z", day, Nature.ACTUAL, "f", evaluate(compile_expression("1 > 0")))


def test_unknown_tree_nodes_are_refused() -> None:
    from fcp.modules.metrics import expr  # noqa: PLC0415

    with pytest.raises(ExpressionError, match="Unknown expression"):
        expr._Checker({}, {}).check(expr.Node(0))
    compiled = compile_expression("1")
    with pytest.raises(EvaluationError, match="unknown expression"):
        evaluate(replace(compiled, tree=expr.Node(0)))
