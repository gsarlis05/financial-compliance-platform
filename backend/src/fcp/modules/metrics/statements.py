"""Basic financial statements: P&L, balance sheet and indirect cash flow (M2-8, AC-M2-8).

Figures come from the ``reporting.actuals`` read model through the reporting gateway (ADR-0007)
and are grouped by the account → taxonomy mapping (M2-6). Statements are **management
statements**, not statutory filings (those arrive in M10).

Conventions
- ``bal(d)`` is the net debit balance of an account from every posting dated *before* ``d``.
- Balance sheet rows are shown on their natural side: assets as debit balances, equity and
  liabilities as credit balances. P&L rows are shown as their effect on profit (income positive,
  expenses negative), so every subtotal is a plain sum.
- Profit or loss is not closed to retained earnings until year end (M2-9), so the balance sheet's
  equity adds two computed rows: the result of the current fiscal year to date, and any result
  of earlier years not yet closed. Both come straight from the income and expense accounts.
- The cash flow statement is derived from balance-sheet movements (indirect method) with a
  versioned classification per taxonomy (``CASH_FLOW_RULES``). Every balance-sheet line is
  classified exactly once, so the statement reconciles to the movement in cash by construction;
  the reconciliation is still checked and reported.
- An account without a mapping blocks the statements if it has a balance at either end of a
  period shown (doc 05 §7), because its amount would otherwise be missing.

Every statement carries checks (balance sheet balances; P&L result = movement in equity less
contributions and distributions; cash flow = movement in cash). A failed check is a defect: it is
reported with the statements and logged, never hidden.
"""

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from importlib import resources
from typing import Literal
from uuid import UUID

import structlog

from fcp.core.errors import ConflictError, ValidationFailedError
from fcp.modules.reporting.api import AccountRef, accounts, balances_before, fiscal_year_start
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import TaxonomyLine
from .services import current_mapping
from .taxonomy import DEFAULT_TAXONOMY

log = structlog.get_logger(__name__)

ZERO = Decimal(0)
PL_TYPES = frozenset({"INCOME", "EXPENSE"})
RowKind = Literal["heading", "line", "subtotal", "total"]
Column = Literal["current", "comparative"]


class MappingIncompleteError(ConflictError):
    code = "metrics.statements.mapping_incomplete"
    title = "Statements are blocked by unmapped accounts"


# --- result types ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Period:
    date_from: date
    date_to: date


@dataclass(frozen=True)
class AccountAmount:
    """Drill-down: one account's contribution to a row (``account_id`` None: a computed part)."""

    account_id: UUID | None
    code: str
    name: str
    name_el: str
    current: Decimal
    comparative: Decimal | None


@dataclass(frozen=True)
class Row:
    kind: RowKind
    code: str
    name: str
    name_el: str
    current: Decimal | None = None
    comparative: Decimal | None = None
    accounts: tuple[AccountAmount, ...] = ()


@dataclass(frozen=True)
class Check:
    code: str
    column: Column
    ok: bool
    values: dict[str, Decimal]


@dataclass(frozen=True)
class Statement:
    kind: Literal["PL", "BS", "CF"]
    name: str
    name_el: str
    rows: list[Row]
    checks: list[Check]

    def row(self, code: str) -> Row:
        return next(r for r in self.rows if r.code == code)


@dataclass(frozen=True)
class Statements:
    entity_name: str
    taxonomy: str
    watermark: int
    current: Period
    comparative: Period | None
    profit_and_loss: Statement
    balance_sheet: Statement
    cash_flow: Statement

    @property
    def all(self) -> list[Statement]:
        return [self.profit_and_loss, self.balance_sheet, self.cash_flow]

    @property
    def ok(self) -> bool:
        return all(c.ok for s in self.all for c in s.checks)


# --- layout (labels in English and Greek) ---------------------------------------------------------


def _load_labels() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    text = (
        resources.files(__package__).joinpath("taxonomy/statement_labels.json").read_text("utf-8")
    )
    data = json.loads(text)
    rows = {k: (v["en"], v["el"]) for k, v in data["rows"].items()}
    names = {k: (v["en"], v["el"]) for k, v in data["statements"].items()}
    return rows, names


LABELS, STATEMENT_NAMES = _load_labels()


# P&L: sections in order; a subtotal after a section sums everything above it.
PL_LAYOUT: list[tuple[str, str | None]] = [
    ("REVENUE", None),
    ("COST_OF_SALES", "PL.GROSS_PROFIT"),
    ("OTHER_INCOME", None),
    ("OPERATING_EXPENSES", "PL.EBITDA"),
    ("DEPRECIATION_AMORTISATION", "PL.OPERATING_PROFIT"),
    ("FINANCE", "PL.PROFIT_BEFORE_TAX"),
    ("TAX", None),
]


@dataclass(frozen=True)
class CashFlowRules:
    """How each balance-sheet line moves cash (one taxonomy version). Investing groups combine
    lines (cost and accumulated depreciation); a non-cash P&L line is added back in operating
    activities and taken out of the investing group whose balance it reduced."""

    cash: frozenset[str]
    operating: tuple[str, ...]
    investing: tuple[tuple[str, tuple[str, ...], tuple[str, str]], ...]
    noncash: dict[str, str]  # P&L taxonomy line -> investing group
    financing: tuple[str, ...]

    def classified(self) -> list[str]:
        groups = [code for _, codes, _ in self.investing for code in codes]
        return [*self.cash, *self.operating, *groups, *self.financing]


CASH_FLOW_RULES: dict[str, CashFlowRules] = {
    "IFRS_SME_CY@1.0": CashFlowRules(
        cash=frozenset({"BS.CASH"}),
        operating=(
            "BS.INVENTORY",
            "BS.AR",
            "BS.OTHER_REC",
            "BS.TAX_REC",
            "BS.AP",
            "BS.OTHER_PAY",
            "BS.TAX_PAY",
        ),
        investing=(
            (
                "CF.INV.PPE",
                ("BS.PPE.GROSS", "BS.PPE.ACCDEP"),
                (
                    "Property, plant and equipment (purchases less disposals)",
                    "Ακίνητα, εγκαταστάσεις και εξοπλισμός (αγορές μείον πωλήσεις)",
                ),
            ),
            (
                "CF.INV.INTANGIBLES",
                ("BS.INTANGIBLES",),
                (
                    "Intangible assets (purchases less disposals)",
                    "Άυλα περιουσιακά στοιχεία (αγορές μείον πωλήσεις)",
                ),
            ),
            (
                "CF.INV.INVESTMENTS",
                ("BS.INVESTMENTS",),
                ("Investments (purchases less disposals)", "Επενδύσεις (αγορές μείον πωλήσεις)"),
            ),
        ),
        noncash={"DA.DEPRECIATION": "CF.INV.PPE", "DA.AMORTISATION": "CF.INV.INTANGIBLES"},
        financing=(
            "BS.DEBT.NONCURRENT",
            "BS.DEBT.CURRENT",
            "BS.EQUITY.SHARE_CAPITAL",
            "BS.EQUITY.SHARE_PREMIUM",
            "BS.EQUITY.RETAINED",
        ),
    ),
}


# --- inputs ---------------------------------------------------------------------------------------


def _shift_year(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def prior_year(period: Period) -> Period:
    return Period(_shift_year(period.date_from, -1), _shift_year(period.date_to, -1))


@dataclass
class _Column:
    """Balances needed for one column: P&L period, opening and closing cut-offs, fiscal year."""

    period: Period
    opening: dict[UUID, Decimal]  # bal(date_from)
    closing: dict[UUID, Decimal]  # bal(date_to + 1)
    fy_start: dict[UUID, Decimal]  # bal(start of the fiscal year containing date_to)

    def movement(self, account_id: UUID) -> Decimal:
        return self.closing.get(account_id, ZERO) - self.opening.get(account_id, ZERO)


@dataclass
class _Context:
    accounts: list[AccountRef]
    mapping: dict[UUID, TaxonomyLine]
    lines: list[TaxonomyLine]
    columns: list[_Column]  # current first, then the comparative (if any)
    by_line: dict[str, list[AccountRef]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        grouped: dict[str, list[AccountRef]] = defaultdict(list)
        for account in self.accounts:
            line = self.mapping.get(account.id)
            if line is not None:
                grouped[line.code].append(account)
        self.by_line = dict(grouped)

    @property
    def has_comparative(self) -> bool:
        return len(self.columns) > 1


def _blocking(
    postable: list[AccountRef],
    mapping: dict[UUID, TaxonomyLine],
    cutoffs: dict[date, dict[UUID, Decimal]],
    checked: Iterable[date],
) -> dict[str, list[str]]:
    errors: dict[str, list[str]] = {}
    for account in postable:
        if account.id in mapping:
            continue
        dates = sorted(d for d in set(checked) if cutoffs[d].get(account.id, ZERO) != 0)
        if dates:
            when = (dates[0] - timedelta(days=1)).isoformat()
            errors[account.code] = [f"unmapped and has a balance on {when}"]
    return errors


# --- assembly -------------------------------------------------------------------------------------


def _label(code: str) -> tuple[str, str]:
    return LABELS[code]


class _Value:
    """An account's amount in one column; rows and their drill-down share the same rule."""

    def __call__(self, column: _Column, account: AccountRef) -> Decimal:  # pragma: no cover
        raise NotImplementedError


class _Balance(_Value):
    """Balance on the natural side: assets as debits, equity and liabilities as credits."""

    def __init__(self, cutoff: Literal["opening", "closing"] = "closing") -> None:
        self.cutoff = cutoff

    def __call__(self, column: _Column, account: AccountRef) -> Decimal:
        balances = column.closing if self.cutoff == "closing" else column.opening
        net = balances.get(account.id, ZERO)
        return net if account.type == "ASSET" else -net


class _Inflow(_Value):
    """Minus the net debit movement: the effect on profit (P&L accounts) or on cash (balance-sheet
    accounts, indirect method)."""

    def __call__(self, column: _Column, account: AccountRef) -> Decimal:
        return -column.movement(account.id)


class _Addback(_Value):
    """A non-cash expense added back to profit."""

    def __call__(self, column: _Column, account: AccountRef) -> Decimal:
        return column.movement(account.id)


class _ResultYearToDate(_Value):
    def __call__(self, column: _Column, account: AccountRef) -> Decimal:
        return column.fy_start.get(account.id, ZERO) - column.closing.get(account.id, ZERO)


class _ResultEarlierYears(_Value):
    def __call__(self, column: _Column, account: AccountRef) -> Decimal:
        return -column.fy_start.get(account.id, ZERO)


def _amounts(ctx: _Context, accounts_: list[AccountRef], value: _Value) -> list[AccountAmount]:
    out = []
    for account in sorted(accounts_, key=lambda a: a.code):
        current = value(ctx.columns[0], account)
        comparative = value(ctx.columns[1], account) if ctx.has_comparative else None
        if current or comparative:
            out.append(
                AccountAmount(
                    account.id, account.code, account.name, account.name_el, current, comparative
                )
            )
    return out


def _sum(parts: Iterable[AccountAmount], column: Column) -> Decimal:
    if column == "current":
        return sum((p.current for p in parts), ZERO)
    return sum((p.comparative or ZERO for p in parts), ZERO)


def _line_row(ctx: _Context, code: str, name: tuple[str, str], parts: list[AccountAmount]) -> Row:
    comparative = _sum(parts, "comparative") if ctx.has_comparative else None
    return Row("line", code, name[0], name[1], _sum(parts, "current"), comparative, tuple(parts))


def _total(ctx: _Context, kind: RowKind, code: str, rows: Iterable[Row]) -> Row:
    rows = list(rows)
    current = sum((r.current or ZERO for r in rows), ZERO)
    comparative = sum((r.comparative or ZERO for r in rows), ZERO) if ctx.has_comparative else None
    name = _label(code)
    return Row(kind, code, name[0], name[1], current, comparative)


def _heading(code: str) -> Row:
    name = _label(code)
    return Row("heading", code, name[0], name[1])


def _section_rows(ctx: _Context, section: str, value: _Value) -> list[Row]:
    rows = []
    for line in ctx.lines:
        if line.section != section:
            continue
        parts = _amounts(ctx, ctx.by_line.get(line.code, []), value)
        if parts:
            rows.append(_line_row(ctx, line.code, (line.name, line.name_el), parts))
    return rows


def _nonzero(row: Row) -> bool:
    return bool(row.current) or bool(row.comparative)


def _profit_and_loss(ctx: _Context) -> Statement:
    rows: list[Row] = []
    lines_so_far: list[Row] = []
    for section, subtotal in PL_LAYOUT:
        section_rows = _section_rows(ctx, section, _Inflow())
        if section_rows:
            rows += [_heading(section), *section_rows]
            lines_so_far += section_rows
        if subtotal:
            rows.append(_total(ctx, "subtotal", subtotal, lines_so_far))
    rows.append(_total(ctx, "total", "PL.RESULT", lines_so_far))
    name = STATEMENT_NAMES["PL"]
    return Statement("PL", name[0], name[1], rows, [])


def _equity_computed(ctx: _Context) -> list[Row]:
    """Result of the current fiscal year to date and of earlier years not yet closed."""
    pl = [a for a in ctx.accounts if a.type in PL_TYPES]
    ytd = _line_row(
        ctx,
        "BS.EQUITY.RESULT_YTD",
        _label("BS.EQUITY.RESULT_YTD"),
        _amounts(ctx, pl, _ResultYearToDate()),
    )
    earlier = _line_row(
        ctx,
        "BS.EQUITY.PRIOR_UNCLOSED",
        _label("BS.EQUITY.PRIOR_UNCLOSED"),
        _amounts(ctx, pl, _ResultEarlierYears()),
    )
    return [ytd, earlier] if _nonzero(earlier) else [ytd]


def _balance_sheet(ctx: _Context) -> Statement:
    value = _Balance()
    rows: list[Row] = []
    totals: dict[str, Row] = {}
    for section in (
        "NON_CURRENT_ASSETS",
        "CURRENT_ASSETS",
        "EQUITY",
        "NON_CURRENT_LIABILITIES",
        "CURRENT_LIABILITIES",
    ):
        section_rows = _section_rows(ctx, section, value)
        if section == "EQUITY":
            section_rows += _equity_computed(ctx)
        totals[section] = _total(ctx, "subtotal", f"BS.TOTAL.{section}", section_rows)
        rows += [_heading(section), *section_rows, totals[section]]
        if section == "CURRENT_ASSETS":
            rows.append(
                _total(
                    ctx,
                    "total",
                    "BS.TOTAL_ASSETS",
                    [totals["NON_CURRENT_ASSETS"], totals["CURRENT_ASSETS"]],
                )
            )
    liabilities = _total(
        ctx,
        "subtotal",
        "BS.TOTAL_LIABILITIES",
        [totals["NON_CURRENT_LIABILITIES"], totals["CURRENT_LIABILITIES"]],
    )
    rows += [
        liabilities,
        _total(ctx, "total", "BS.TOTAL_EQUITY_LIABILITIES", [totals["EQUITY"], liabilities]),
    ]
    name = STATEMENT_NAMES["BS"]
    return Statement("BS", name[0], name[1], rows, [])


def _group_accounts(ctx: _Context, codes: Iterable[str]) -> list[AccountRef]:
    return [a for code in codes for a in ctx.by_line.get(code, [])]


def _cash_flow(ctx: _Context, rules: CashFlowRules, result: Row) -> Statement:
    rows: list[Row] = [
        _heading("CF.OPERATING"),
        Row("line", "CF.RESULT", *_label("CF.RESULT"), result.current, result.comparative),
    ]
    noncash_parts = _amounts(ctx, _group_accounts(ctx, rules.noncash), _Addback())
    operating = [rows[-1]]
    if noncash_parts:
        operating.append(_line_row(ctx, "CF.NONCASH", _label("CF.NONCASH"), noncash_parts))
    for code in rules.operating:
        parts = _amounts(ctx, ctx.by_line.get(code, []), _Inflow())
        if parts:
            line = next(ln for ln in ctx.lines if ln.code == code)
            operating.append(
                _line_row(
                    ctx,
                    f"CF.{code}",
                    (f"Change in {line.name.lower()}", f"Μεταβολή: {line.name_el}"),
                    parts,
                )
            )
    rows += operating[1:]
    operating_total = _total(ctx, "subtotal", "CF.TOTAL.OPERATING", operating)
    rows.append(operating_total)

    investing: list[Row] = []
    for group, codes, name in rules.investing:
        parts = _amounts(ctx, _group_accounts(ctx, codes), _Inflow())
        # The non-cash charge added back above reduced this group's balance: take it out here.
        charges = [code for code, target in rules.noncash.items() if target == group]
        addback = _amounts(ctx, _group_accounts(ctx, charges), _Addback())
        if addback:
            parts.append(
                AccountAmount(
                    None,
                    "",
                    "Less: " + _label("CF.NONCASH")[0].lower(),
                    "Μείον: αποσβέσεις",
                    -_sum(addback, "current"),
                    -_sum(addback, "comparative") if ctx.has_comparative else None,
                )
            )
        row = _line_row(ctx, group, name, parts)
        if parts and _nonzero(row):
            investing.append(row)
    investing_total = _total(ctx, "subtotal", "CF.TOTAL.INVESTING", investing)
    rows += [_heading("CF.INVESTING"), *investing, investing_total]

    financing: list[Row] = []
    for code in rules.financing:
        parts = _amounts(ctx, ctx.by_line.get(code, []), _Inflow())
        if parts:
            line = next(ln for ln in ctx.lines if ln.code == code)
            financing.append(
                _line_row(
                    ctx,
                    f"CF.{code}",
                    (f"Change in {line.name.lower()}", f"Μεταβολή: {line.name_el}"),
                    parts,
                )
            )
    financing_total = _total(ctx, "subtotal", "CF.TOTAL.FINANCING", financing)
    rows += [_heading("CF.FINANCING"), *financing, financing_total]

    net = _total(ctx, "total", "CF.NET_CHANGE", [operating_total, investing_total, financing_total])
    cash_accounts = _group_accounts(ctx, rules.cash)
    opening = _line_row(
        ctx,
        "CF.CASH_OPENING",
        _label("CF.CASH_OPENING"),
        _amounts(ctx, cash_accounts, _Balance("opening")),
    )
    closing = _line_row(
        ctx, "CF.CASH_CLOSING", _label("CF.CASH_CLOSING"), _amounts(ctx, cash_accounts, _Balance())
    )
    rows += [net, opening, closing]
    name = STATEMENT_NAMES["CF"]
    return Statement("CF", name[0], name[1], rows, [])


# --- checks ---------------------------------------------------------------------------------------


def _value(row: Row, column: Column) -> Decimal:
    return (row.current if column == "current" else row.comparative) or ZERO


def _equity_total(ctx: _Context, column: _Column, cutoff: Literal["opening", "closing"]) -> Decimal:
    """Total equity at a cut-off, from the accounts: credit balances of equity accounts plus
    every income and expense account's accumulated result."""
    balances = column.opening if cutoff == "opening" else column.closing
    return -sum(
        (
            balances.get(a.id, ZERO)
            for a in ctx.accounts
            if a.type == "EQUITY" or a.type in PL_TYPES
        ),
        ZERO,
    )


def _checks(ctx: _Context, pl: Statement, bs: Statement, cf: Statement) -> None:
    columns: list[Column] = ["current", "comparative"] if ctx.has_comparative else ["current"]
    for index, column in enumerate(columns):
        data = ctx.columns[index]
        assets = _value(bs.row("BS.TOTAL_ASSETS"), column)
        equity_liabilities = _value(bs.row("BS.TOTAL_EQUITY_LIABILITIES"), column)
        bs.checks.append(
            Check(
                "balance_sheet_balances",
                column,
                assets == equity_liabilities,
                {"total_assets": assets, "total_equity_and_liabilities": equity_liabilities},
            )
        )

        # Equity per the balance sheet must equal equity per the accounts ...
        closing = _value(bs.row("BS.TOTAL.EQUITY"), column)
        accounts_closing = _equity_total(ctx, data, "closing")
        bs.checks.append(
            Check(
                "equity_matches_accounts",
                column,
                closing == accounts_closing,
                {"statement": closing, "accounts": accounts_closing},
            )
        )
        # ... and its movement is the P&L result plus contributions and distributions.
        result = _value(pl.row("PL.RESULT"), column)
        opening = _equity_total(ctx, data, "opening")
        direct = -sum((data.movement(a.id) for a in ctx.accounts if a.type == "EQUITY"), ZERO)
        pl.checks.append(
            Check(
                "result_equals_equity_movement",
                column,
                result == closing - opening - direct,
                {
                    "result": result,
                    "equity_opening": opening,
                    "equity_closing": closing,
                    "contributions_and_distributions": direct,
                },
            )
        )

        net = _value(cf.row("CF.NET_CHANGE"), column)
        cash_change = _value(cf.row("CF.CASH_CLOSING"), column) - _value(
            cf.row("CF.CASH_OPENING"), column
        )
        cf.checks.append(
            Check(
                "cash_flow_reconciles",
                column,
                net == cash_change,
                {"net_change": net, "cash_movement": cash_change},
            )
        )


# --- entry point ----------------------------------------------------------------------------------


def build(
    wctx: WorkspaceContext,
    entity_id: UUID,
    *,
    date_from: date,
    date_to: date,
    comparative: Literal["prior_year", "none"] = "prior_year",
    version: str = DEFAULT_TAXONOMY,
) -> Statements:
    """Build the three statements for a period (the balance sheet is at ``date_to``)."""
    entity = get_entity(wctx, entity_id, "reports.read")
    if date_from > date_to:
        raise ValidationFailedError(
            "The period must not end before it starts.",
            field_errors={"date_to": ["before date_from"]},
        )
    rules = CASH_FLOW_RULES.get(version)
    if rules is None:
        raise ValidationFailedError(
            "Statements are not available for this taxonomy.",
            field_errors={"taxonomy": ["unsupported"]},
        )
    periods = [Period(date_from, date_to)]
    if comparative == "prior_year":
        periods.append(prior_year(periods[0]))
    fy_starts = [fiscal_year_start(wctx, entity_id, p.date_to) for p in periods]
    cutoffs = [d for p in periods for d in (p.date_from, p.date_to + timedelta(days=1))]
    watermark, balances = balances_before(wctx, entity_id, [*cutoffs, *fy_starts])

    all_accounts = [a for a in accounts(wctx, entity_id) if a.is_postable]
    mapping = current_mapping(entity_id, version)
    errors = _blocking(all_accounts, mapping, balances, cutoffs)
    if errors:
        raise MappingIncompleteError(
            f"{len(errors)} account(s) with a balance are not mapped to a statement line. Map "
            "them on the Statement mapping page, then try again.",
            field_errors=errors,
        )
    columns = [
        _Column(p, balances[p.date_from], balances[p.date_to + timedelta(days=1)], balances[fy])
        for p, fy in zip(periods, fy_starts, strict=True)
    ]
    lines = list(TaxonomyLine.objects.filter(version_id=version).order_by("order"))
    ctx = _Context(all_accounts, mapping, lines, columns)

    pl = _profit_and_loss(ctx)
    bs = _balance_sheet(ctx)
    cf = _cash_flow(ctx, rules, pl.row("PL.RESULT"))
    _checks(ctx, pl, bs, cf)
    result = Statements(
        entity.legal_name,
        version,
        watermark,
        periods[0],
        periods[1] if len(periods) > 1 else None,
        pl,
        bs,
        cf,
    )
    if not result.ok:
        failed = [f"{s.kind}.{c.code}.{c.column}" for s in result.all for c in s.checks if not c.ok]
        log.error("metrics.statements_check_failed", entity_id=str(entity_id), checks=failed)
    return result
