"""The sandboxed Decimal expression language (M3-3, doc 10 §2.2, doc 06 §3, ADR-0009).

Formulas for KPIs, drivers and goals (and later tax rules) are written in a small language that is
parsed by hand into a tree and evaluated here. There is no ``eval``, no Python ``ast``, no loops,
no attribute access and no I/O. What a formula can reach is exactly the variables and functions
given to ``compile_expression``.

Syntax:
- numbers (``0.15``), strings (``"REV.SALES"``, only as keys for reference functions), ``true`` and
  ``false``;
- ``+ - * /``, unary ``-``, comparisons ``< <= > >= == !=``, ``and``, ``or``, ``not``,
  parentheses;
- function calls with positional and ``name=value`` arguments.

Built-in functions: ``min``, ``max``, ``abs``, ``round(x, places)`` (HALF_UP), ``if(c, a, b)``,
``sum(list)`` and ``divide_positive(a, b)`` (not meaningful unless ``b > 0``, e.g. ROE with
negative equity). Reference functions (``metric``, ``balance``, ``driver``, ``days``, ...) are
supplied by the caller with a signature and an implementation.

Units are checked before evaluating:
- ``+``, ``-``, comparisons, ``min``, ``max`` and the two branches of ``if`` need the same unit;
- a bare number takes the unit of the other side;
- ``ratio`` and ``percent`` scale anything (``EUR * ratio`` is EUR);
- ``EUR * count`` is EUR (price times quantity);
- dividing two values of the same unit gives a ``ratio``, and ``EUR / count`` is EUR;
- anything else, such as ``EUR + days`` or ``EUR * EUR``, is rejected.

Division by zero, and any operation on a value that is not meaningful, gives ``NotMeaningful``
with a reason: never 0 and never infinity.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import (
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Any

MAX_LENGTH = 2000
MAX_TOKENS = 400  # every tree node takes at least one token, so this also bounds the tree
MAX_DEPTH = 24
MAX_DIGITS = 28
MAX_ARGS = 20
MAX_ROUND_PLACES = 10

NUMBER = "number"  # a bare literal: takes the unit of the other operand
SCALERS = {NUMBER: 0, "ratio": 1, "percent": 2}
UNITS = frozenset({"EUR", "ratio", "percent", "days", "count", "times", NUMBER})

_CONTEXT = Context(prec=28, rounding=ROUND_HALF_EVEN, Emax=10**6, Emin=-(10**6),
                   traps=[InvalidOperation, DivisionByZero, Overflow])  # fmt: skip


class ExpressionError(ValueError):
    """A formula that is not valid: bad syntax, an unknown name, a unit mismatch, too large."""

    def __init__(self, code: str, message: str, position: int | None = None) -> None:
        super().__init__(message if position is None else f"{message} (at {position + 1})")
        self.code = code
        self.message = message
        self.position = position


class EvaluationError(ValueError):
    """A formula that is valid but could not be evaluated with the values supplied (a missing
    variable, a reference function returning a non-Decimal)."""


@dataclass(frozen=True)
class NotMeaningful:
    reason: str


# --- types and signatures -------------------------------------------------------------------------


@dataclass(frozen=True)
class Type:
    kind: str  # "scalar" | "list" | "bool" | "key" | "period"
    unit: str = NUMBER

    def __str__(self) -> str:
        if self.kind == "scalar":
            return self.unit
        return f"list[{self.unit}]" if self.kind == "list" else self.kind


def scalar(unit: str) -> Type:
    if unit not in UNITS:
        raise ValueError(f"unknown unit {unit}")
    return Type("scalar", unit)


def series(unit: str) -> Type:
    if unit not in UNITS:
        raise ValueError(f"unknown unit {unit}")
    return Type("list", unit)


BOOL = Type("bool", "bool")
KEY = Type("key", "key")
PERIOD = Type("period", "period")


@dataclass(frozen=True)
class Param:
    name: str
    type: Type  # for "scalar", unit NUMBER means "any unit"
    optional: bool = False


@dataclass(frozen=True)
class Function:
    """A reference function supplied by the caller: ``impl`` gets the evaluated arguments (keys as
    strings, periods as given in the variables) and returns a Decimal, a list of Decimals or
    ``NotMeaningful``."""

    name: str
    params: tuple[Param, ...]
    result: Type
    impl: Callable[..., Any]


# --- lexing ---------------------------------------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<ws>[ \t\r\n]+)
  | (?P<number>\d+(?:\.\d+)?)
  | (?P<string>"[A-Za-z0-9_.:\- ]{0,100}")
  | (?P<name>[A-Za-z_][A-Za-z0-9_]{0,63})
  | (?P<op><=|>=|==|!=|[-+*/(),<>=])
""", re.VERBOSE)  # fmt: skip
_KEYWORDS = {"and", "or", "not", "true", "false"}


@dataclass(frozen=True)
class Token:
    kind: str  # number | string | name | op | keyword | end
    text: str
    position: int


def tokenize(source: str) -> list[Token]:
    if not isinstance(source, str):
        raise ExpressionError("expr.syntax", "The formula must be text.")
    if len(source) > MAX_LENGTH:
        raise ExpressionError("expr.too_large", f"Formulas are at most {MAX_LENGTH} characters.")
    tokens: list[Token] = []
    position = 0
    while position < len(source):
        match = _TOKEN.match(source, position)
        if match is None:
            raise ExpressionError("expr.syntax", f"Unexpected character {source[position]!r}.",
                                  position)  # fmt: skip
        kind = match.lastgroup or ""
        text = match.group()
        if kind != "ws":
            if kind == "name" and text in _KEYWORDS:
                kind = "keyword"
            whole, _, fraction = text.partition(".")
            if kind == "number" and len(whole.lstrip("0")) + len(fraction) > MAX_DIGITS:
                raise ExpressionError("expr.too_large", f"Numbers have at most {MAX_DIGITS} "
                                      "digits.", position)  # fmt: skip
            tokens.append(Token(kind, text, position))
            if len(tokens) > MAX_TOKENS:
                raise ExpressionError("expr.too_large", "The formula is too long.", position)
        position = match.end()
    tokens.append(Token("end", "", len(source)))
    return tokens


# --- parsing --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    position: int


@dataclass(frozen=True)
class Num(Node):
    value: Decimal


@dataclass(frozen=True)
class Str(Node):
    value: str


@dataclass(frozen=True)
class Bool(Node):
    value: bool


@dataclass(frozen=True)
class Name(Node):
    id: str


@dataclass(frozen=True)
class Unary(Node):
    op: str  # "-" | "not"
    operand: Node


@dataclass(frozen=True)
class Binary(Node):
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Call(Node):
    function: str
    args: tuple[Node, ...]
    kwargs: tuple[tuple[str, Node], ...]


_COMPARISONS = {"<", "<=", ">", ">=", "==", "!="}


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    @property
    def token(self) -> Token:
        return self.tokens[self.index]

    def take(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def accept(self, *texts: str) -> Token | None:
        if self.token.kind in ("op", "keyword") and self.token.text in texts:
            return self.take()
        return None

    def expect(self, text: str) -> Token:
        token = self.accept(text)
        if token is None:
            found = self.token.text or "the end"
            raise ExpressionError("expr.syntax", f"Expected {text!r} but found {found!r}.",
                                  self.token.position)  # fmt: skip
        return token

    def nest(self) -> None:
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise ExpressionError("expr.too_large", f"Formulas nest at most {MAX_DEPTH} levels.",
                                  self.token.position)  # fmt: skip

    def parse(self) -> Node:
        tree = self.expression()
        if self.token.kind != "end":
            raise ExpressionError("expr.syntax", f"Unexpected {self.token.text!r}.",
                                  self.token.position)  # fmt: skip
        return tree

    def expression(self) -> Node:
        self.nest()
        try:
            return self.disjunction()
        finally:
            self.depth -= 1

    def disjunction(self) -> Node:
        left = self.conjunction()
        while op := self.accept("or"):
            left = Binary(op.position, "or", left, self.conjunction())
        return left

    def conjunction(self) -> Node:
        left = self.negation()
        while op := self.accept("and"):
            left = Binary(op.position, "and", left, self.negation())
        return left

    def negation(self) -> Node:
        if op := self.accept("not"):
            self.nest()
            try:
                return Unary(op.position, "not", self.negation())
            finally:
                self.depth -= 1
        return self.comparison()

    def comparison(self) -> Node:
        left = self.additive()
        if op := self.accept(*_COMPARISONS):
            left = Binary(op.position, op.text, left, self.additive())
            if self.token.kind == "op" and self.token.text in _COMPARISONS:
                raise ExpressionError("expr.syntax", "Comparisons cannot be chained; use 'and'.",
                                      self.token.position)  # fmt: skip
        return left

    def additive(self) -> Node:
        left = self.multiplicative()
        while op := self.accept("+", "-"):
            left = Binary(op.position, op.text, left, self.multiplicative())
        return left

    def multiplicative(self) -> Node:
        left = self.unary()
        while op := self.accept("*", "/"):
            left = Binary(op.position, op.text, left, self.unary())
        return left

    def unary(self) -> Node:
        if op := self.accept("-"):
            self.nest()
            try:
                return Unary(op.position, "-", self.unary())
            finally:
                self.depth -= 1
        return self.primary()

    def primary(self) -> Node:
        token = self.token
        if token.kind == "number":
            self.take()
            return Num(token.position, Decimal(token.text))
        if token.kind == "string":
            self.take()
            return Str(token.position, token.text[1:-1])
        if token.kind == "keyword" and token.text in ("true", "false"):
            self.take()
            return Bool(token.position, token.text == "true")
        if token.kind == "name":
            self.take()
            if self.accept("("):
                return self.call(token)
            return Name(token.position, token.text)
        if self.accept("("):
            inner = self.expression()
            self.expect(")")
            return inner
        found = token.text or "the end"
        raise ExpressionError("expr.syntax", f"Expected a value but found {found!r}.",
                              token.position)  # fmt: skip

    def call(self, name: Token) -> Node:
        args: list[Node] = []
        kwargs: list[tuple[str, Node]] = []
        if not self.accept(")"):
            while True:
                if len(args) + len(kwargs) >= MAX_ARGS:
                    raise ExpressionError("expr.too_large", "Too many arguments.",
                                          self.token.position)  # fmt: skip
                if (self.token.kind == "name" and self.tokens[self.index + 1].kind == "op"
                        and self.tokens[self.index + 1].text == "="):  # fmt: skip
                    key = self.take().text
                    self.take()
                    if any(k == key for k, _ in kwargs):
                        raise ExpressionError("expr.syntax", f"Argument {key!r} is given twice.",
                                              name.position)  # fmt: skip
                    kwargs.append((key, self.expression()))
                elif kwargs:
                    raise ExpressionError("expr.syntax", "Positional arguments come first.",
                                          self.token.position)  # fmt: skip
                else:
                    args.append(self.expression())
                if self.accept(")"):
                    break
                self.expect(",")
        return Call(name.position, name.text, tuple(args), tuple(kwargs))


def parse(source: str) -> Node:
    return _Parser(tokenize(source)).parse()


# --- unit and type checking -----------------------------------------------------------------------

_BUILTINS = frozenset({"min", "max", "abs", "round", "if", "sum", "divide_positive"})


def _unify(a: Type, b: Type, position: int, what: str) -> Type:
    if a.kind != "scalar" or b.kind != "scalar":
        raise ExpressionError("expr.type", f"{what} needs numbers, not {a} and {b}.", position)
    if b.unit in (a.unit, NUMBER):
        return a
    if a.unit == NUMBER:
        return b
    raise ExpressionError("expr.unit", f"{what} needs the same unit, not {a.unit} and {b.unit}.",
                          position)  # fmt: skip


def _multiply(a: str, b: str, position: int) -> str:
    if a in SCALERS and b in SCALERS:
        return a if SCALERS[a] >= SCALERS[b] else b
    if b in SCALERS:
        return a
    if a in SCALERS:
        return b
    if {a, b} == {"EUR", "count"}:
        return "EUR"
    raise ExpressionError("expr.unit", f"Cannot multiply {a} by {b}.", position)


def _divide(a: str, b: str, position: int) -> str:
    if a == b:
        return NUMBER if a == NUMBER else "ratio"
    if b in SCALERS:
        return a
    if (a, b) == ("EUR", "count"):
        return "EUR"
    raise ExpressionError("expr.unit", f"Cannot divide {a} by {b}.", position)


def _scalar(t: Type, position: int, what: str) -> Type:
    if t.kind != "scalar":
        raise ExpressionError("expr.type", f"{what} needs a number, not {t}.", position)
    return t


def _bool(t: Type, position: int, what: str) -> Type:
    if t.kind != "bool":
        raise ExpressionError("expr.type", f"{what} needs true or false, not {t}.", position)
    return t


class _Checker:
    def __init__(self, variables: Mapping[str, Type], functions: Mapping[str, Function]) -> None:
        self.variables = variables
        self.functions = functions
        self.references: set[str] = set()

    def check(self, node: Node) -> Type:  # noqa: PLR0911, PLR0912 (one branch per node kind)
        if isinstance(node, Num):
            return Type("scalar", NUMBER)
        if isinstance(node, Bool):
            return BOOL
        if isinstance(node, Str):
            return KEY
        if isinstance(node, Name):
            if node.id not in self.variables:
                raise ExpressionError("expr.unknown_name", f"Unknown name {node.id!r}.",
                                      node.position)  # fmt: skip
            self.references.add(node.id)
            return self.variables[node.id]
        if isinstance(node, Unary):
            operand = self.check(node.operand)
            if node.op == "not":
                return _bool(operand, node.position, "'not'")
            return _scalar(operand, node.position, "'-'")
        if isinstance(node, Binary):
            left, right = self.check(node.left), self.check(node.right)
            if node.op in ("and", "or"):
                _bool(left, node.position, f"'{node.op}'")
                _bool(right, node.position, f"'{node.op}'")
                return BOOL
            if node.op in _COMPARISONS:
                _unify(left, right, node.position, "A comparison")
                return BOOL
            _scalar(left, node.position, f"'{node.op}'")
            _scalar(right, node.position, f"'{node.op}'")
            if node.op in ("+", "-"):
                return _unify(left, right, node.position, f"'{node.op}'")
            if node.op == "*":
                return Type("scalar", _multiply(left.unit, right.unit, node.position))
            return Type("scalar", _divide(left.unit, right.unit, node.position))
        if isinstance(node, Call):
            return self.call(node)
        raise ExpressionError("expr.syntax", "Unknown expression.", node.position)

    def call(self, node: Call) -> Type:  # noqa: PLR0911, PLR0912 (one branch per builtin)
        name, args = node.function, node.args
        if name in _BUILTINS:
            if node.kwargs and name != "round":
                raise ExpressionError("expr.arguments", f"{name}() takes no named arguments.",
                                      node.position)  # fmt: skip
            types = [self.check(a) for a in args]
            if name in ("min", "max"):
                if len(types) < 2:
                    raise ExpressionError("expr.arguments", f"{name}() needs at least two values.",
                                          node.position)  # fmt: skip
                result = _scalar(types[0], node.position, f"{name}()")
                for t in types[1:]:
                    result = _unify(result, t, node.position, f"{name}()")
                return result
            if name == "if":
                if len(types) != 3:
                    raise ExpressionError("expr.arguments", "if() needs a condition and two "
                                          "values.", node.position)  # fmt: skip
                _bool(types[0], node.position, "if()")
                if types[1].kind == "bool" and types[2].kind == "bool":
                    return BOOL
                return _unify(types[1], types[2], node.position, "if()")
            if name == "round":
                return self.round(node, types)
            if len(types) != (2 if name == "divide_positive" else 1):
                raise ExpressionError("expr.arguments", f"Wrong number of arguments for {name}().",
                                      node.position)  # fmt: skip
            if name == "sum":
                if types[0].kind != "list":
                    raise ExpressionError("expr.type", f"sum() needs a list, not {types[0]}.",
                                          node.position)  # fmt: skip
                return Type("scalar", types[0].unit)
            if name == "abs":
                return _scalar(types[0], node.position, "abs()")
            _scalar(types[0], node.position, "divide_positive()")
            _scalar(types[1], node.position, "divide_positive()")
            return Type("scalar", _divide(types[0].unit, types[1].unit, node.position))
        function = self.functions.get(name)
        if function is None:
            raise ExpressionError("expr.unknown_function", f"Unknown function {name!r}.",
                                  node.position)  # fmt: skip
        self._bind(function, node)
        self.references.add(f"{name}()")
        return function.result

    def round(self, node: Call, types: list[Type]) -> Type:
        places_node: Node | None = None
        if len(node.args) == 2:
            places_node = node.args[1]
        elif node.kwargs:
            if [k for k, _ in node.kwargs] != ["places"] or len(node.args) != 1:
                raise ExpressionError("expr.arguments", "round(x, places) takes 'places' only.",
                                      node.position)  # fmt: skip
            places_node = node.kwargs[0][1]
        elif len(node.args) != 1:
            raise ExpressionError("expr.arguments", "round() takes a value and its places.",
                                  node.position)  # fmt: skip
        if places_node is not None and not (
            isinstance(places_node, Num) and places_node.value == places_node.value.to_integral()
            and 0 <= places_node.value <= MAX_ROUND_PLACES
        ):  # fmt: skip
            raise ExpressionError("expr.arguments", f"round() places is a whole number from 0 "
                                  f"to {MAX_ROUND_PLACES}.", node.position)  # fmt: skip
        return _scalar(types[0], node.position, "round()")

    def _bind(self, function: Function, node: Call) -> None:
        params = list(function.params)
        if len(node.args) > len(params):
            raise ExpressionError("expr.arguments", f"{function.name}() takes at most "
                                  f"{len(params)} arguments.", node.position)  # fmt: skip
        given: dict[str, Node] = {p.name: a for p, a in zip(params, node.args, strict=False)}
        for key, value in node.kwargs:
            if key not in {p.name for p in params} or key in given:
                raise ExpressionError("expr.arguments", f"{function.name}() has no argument "
                                      f"{key!r}, or it is given twice.",
                                      node.position)  # fmt: skip
            given[key] = value
        for param in params:
            if param.name not in given:
                if not param.optional:
                    raise ExpressionError("expr.arguments", f"{function.name}() needs "
                                          f"{param.name!r}.", node.position)  # fmt: skip
                continue
            actual = self.check(given[param.name])
            expected = param.type
            if actual.kind != expected.kind or (
                expected.kind in ("scalar", "list") and expected.unit != NUMBER
                and actual.unit not in (expected.unit, NUMBER)
            ):  # fmt: skip
                raise ExpressionError("expr.type", f"{function.name}() argument {param.name!r} "
                                      f"must be {expected}, not {actual}.",
                                      given[param.name].position)  # fmt: skip


@dataclass(frozen=True)
class Compiled:
    source: str
    tree: Node
    type: Type
    variables: frozenset[str]  # the variables the formula uses
    types: Mapping[str, Type] = field(repr=False)
    functions: Mapping[str, Function] = field(repr=False)

    @property
    def unit(self) -> str:
        return self.type.unit


def compile_expression(
    source: str,
    variables: Mapping[str, Type] | None = None,
    functions: Sequence[Function] = (),
) -> Compiled:
    """Parse and check a formula; raises ``ExpressionError`` (with a code and position)."""
    variables = dict(variables or {})
    catalogue = {f.name: f for f in functions}
    clash = set(catalogue) & (_BUILTINS | _KEYWORDS)
    if clash:
        raise ValueError(f"reserved function names: {sorted(clash)}")
    tree = parse(source)
    checker = _Checker(variables, catalogue)
    result = checker.check(tree)
    if result.kind not in ("scalar", "bool"):
        raise ExpressionError("expr.type", f"A formula gives a number or true/false, not {result}.",
                              0)  # fmt: skip
    used = frozenset(r for r in checker.references if not r.endswith("()"))
    return Compiled(source, tree, result, used, variables, catalogue)


# --- evaluation -----------------------------------------------------------------------------------


Result = Decimal | bool | NotMeaningful


@dataclass(frozen=True)
class Evaluation:
    value: Result
    unit: str
    calls: tuple[str, ...]  # the reference calls made, with their arguments (for lineage)

    @property
    def meaningful(self) -> bool:
        return not isinstance(self.value, NotMeaningful)


class _Evaluator:
    def __init__(self, compiled: Compiled, values: Mapping[str, Any]) -> None:
        self.compiled = compiled
        self.values = values
        self.calls: list[str] = []

    def eval(self, node: Node) -> Any:  # noqa: PLR0911 (one branch per node kind)
        if isinstance(node, (Num, Bool, Str)):
            return node.value
        if isinstance(node, Name):
            if node.id not in self.values:
                raise EvaluationError(f"no value for {node.id!r}")
            return _checked(self.values[node.id], node.id, self.compiled.types[node.id])
        if isinstance(node, Unary):
            operand = self.eval(node.operand)
            if isinstance(operand, NotMeaningful):
                return operand
            return (not operand) if node.op == "not" else -operand
        if isinstance(node, Binary):
            if node.op in ("and", "or"):
                left = self.eval(node.left)
                if isinstance(left, NotMeaningful):
                    return left
                if (node.op == "and" and not left) or (node.op == "or" and left):
                    return left
                return self.eval(node.right)
            left, right = self.eval(node.left), self.eval(node.right)
            for side in (left, right):
                if isinstance(side, NotMeaningful):
                    return side
            return _binary(node.op, left, right)
        if isinstance(node, Call):
            return self.call(node)
        raise EvaluationError("unknown expression")

    def call(self, node: Call) -> Any:  # noqa: PLR0911, PLR0912 (one branch per builtin)
        name = node.function
        if name == "if":
            condition = self.eval(node.args[0])
            if isinstance(condition, NotMeaningful):
                return condition
            return self.eval(node.args[1] if condition else node.args[2])
        if name in _BUILTINS:
            values = [self.eval(a) for a in node.args]
            for v in values:
                if isinstance(v, NotMeaningful):
                    return v
            if name == "min":
                return min(values)
            if name == "max":
                return max(values)
            if name == "abs":
                return abs(values[0])
            if name == "sum":
                items = values[0]
                bad = next((i for i in items if isinstance(i, NotMeaningful)), None)
                return bad or sum(items, Decimal(0))
            if name == "divide_positive":
                if values[1] <= 0:
                    return NotMeaningful("denominator not positive")
                return values[0] / values[1]
            places = node.args[1] if len(node.args) > 1 else dict(node.kwargs).get("places")
            exponent = Decimal(1).scaleb(-int(places.value)) if isinstance(places, Num) \
                else Decimal("0.01")  # fmt: skip
            return values[0].quantize(exponent, rounding=ROUND_HALF_UP)
        function = self.compiled.functions[name]
        params = list(function.params)
        kwargs: dict[str, Any] = {p.name: self.eval(a)
                                  for p, a in zip(params, node.args, strict=False)}  # fmt: skip
        kwargs.update({k: self.eval(v) for k, v in node.kwargs})
        for value in kwargs.values():
            if isinstance(value, NotMeaningful):
                return value
        self.calls.append(f"{name}({', '.join(f'{k}={v}' for k, v in kwargs.items())})")
        return _checked(function.impl(**kwargs), f"{name}()", function.result)


_NUMERIC = (int, float, Decimal)  # fcp-lint: allow-float (to refuse numbers as periods)


def _checked(value: Any, what: str, expected: Type) -> Any:
    """A supplied value (variable or reference function result) of the declared type."""
    if isinstance(value, NotMeaningful) and expected.kind in ("scalar", "list"):
        return value
    if expected.kind == "scalar" and isinstance(value, Decimal) and value.is_finite():
        return value
    if expected.kind == "list" and isinstance(value, (list, tuple)):
        return [_checked(v, what, Type("scalar", expected.unit)) for v in value]
    if expected.kind == "bool" and isinstance(value, bool):
        return value
    if expected.kind == "period" and not isinstance(value, _NUMERIC):
        return value  # opaque: only passed on to reference functions
    raise EvaluationError(f"{what} must be {expected}, not {type(value).__name__}")


def _binary(op: str, left: Any, right: Any) -> Any:
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if right == 0:
            return NotMeaningful("denominator zero")
        return left / right
    return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right,
            "==": left == right, "!=": left != right}[op]  # fmt: skip


def evaluate(compiled: Compiled, values: Mapping[str, Any] | None = None) -> Evaluation:
    """Evaluate with Decimal arithmetic (28 significant digits). It never raises for a compiled
    formula and values of the declared types; a value that cannot be represented (e.g. rounding
    1E+30 to 2 places) is ``NotMeaningful("out of range")``."""
    evaluator = _Evaluator(compiled, values or {})
    with localcontext(_CONTEXT):
        try:
            value = evaluator.eval(compiled.tree)
        except (Overflow, InvalidOperation):
            value = NotMeaningful("out of range")
        if isinstance(value, Decimal):
            value = +value  # rounded to the context's 28 significant digits
    return Evaluation(value, compiled.unit, tuple(evaluator.calls))
