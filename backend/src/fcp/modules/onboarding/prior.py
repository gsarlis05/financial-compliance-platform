"""The prior year by month, as comparatives (R-4, #247; brief 26).

The file is a monthly trial balance of the months before the books start: one row per account,
one column per month, each cell the account's balance at the end of that month (debit positive).
Income and expense are read year to date, as a monthly trial balance shows them (or, on request,
as each month's own amount).

They become each account's movement per month and are kept by ``reporting`` as comparatives:
budget variance against the prior year, KPIs and statements read them for those months. No
entry is created, and no fiscal year is opened or closed for them.

Checks, every problem listed by row and column:
- every month is before the first fiscal year (so no posting can ever fall in it), and the months
  follow one another;
- each month balances (debits equal credits), with the difference shown;
- the last month's balances agree with the opening entry, account by account, for assets and
  liabilities (equity differs by the year's result carried into it).
"""

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from itertools import pairwise
from uuid import UUID

from fcp.modules.ledger.api import Account, JournalEntry, JournalLine, account_list
from fcp.modules.reporting.api import Fact, books_start, replace_comparatives
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import tables, templates
from .opening import PROFIT_AND_LOSS, Chart
from .services import OPENING, ZERO, Outcome, UnknownAccount, Upload, cell, read_upload, run
from .tables import Problem, Table

MAX_MONTHS = 24
_MONTH = re.compile(r"^(\d{4})[-/.](\d{1,2})$|^(\d{1,2})[-/.](\d{4})$")
_NAMED = ("%b %Y", "%B %Y", "%b-%y", "%b-%Y", "%b %y")


def month_key(month: date) -> str:
    return f"{month.year:04d}-{month.month:02d}"


def _month_of(value: object) -> date | None:
    """A header cell as a month: 2025-01, 01/2025, Jan 2025, January 2025, Jan-25, or a date."""
    if isinstance(value, datetime):
        return date(value.year, value.month, 1)
    if isinstance(value, date):
        return value.replace(day=1)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if found := _MONTH.match(text):
        year = int(found.group(1) or found.group(4))
        month = int(found.group(2) or found.group(3))
        return date(year, month, 1) if 1 <= month <= 12 else None
    for fmt in _NAMED:
        try:
            parsed = datetime.strptime(text, fmt)  # noqa: DTZ007 - a calendar month
        except ValueError:
            continue
        return date(parsed.year, parsed.month, 1)
    return None


def _dynamic(value: object) -> str | None:
    month = _month_of(value)
    return f"m:{month_key(month)}" if month else None


def _previous(month: date) -> date:
    return date(month.year - (month.month == 1), (month.month - 2) % 12 + 1, 1)


def template_months(start: date | None) -> tuple[str, ...]:
    """The 12 months before the books start (none without a fiscal year)."""
    if start is None:
        return ()
    months, month = [], start.replace(day=1)
    for _ in range(12):
        month = _previous(month)
        months.append(month_key(month))
    return tuple(reversed(months))


@dataclass(frozen=True)
class PriorRequest:
    upload: Upload
    account_map: dict[str, str]
    year_to_date: bool = True  # income and expense: year to date (else each month's own amount)


def _months(table: Table) -> list[date] | None:
    keys = sorted(k for k in table.columns if k.startswith("m:"))
    months = [date(int(k[2:6]), int(k[7:9]), 1) for k in keys]
    if not months:
        table.problem(table.header_row, "", "No month columns (such as 2025-01) were found in the "
                                            "header row.")  # fmt: skip
        return None
    if len(months) > MAX_MONTHS:
        table.problem(table.header_row, "", f"At most {MAX_MONTHS} months are read.")
        return None
    for earlier, later in pairwise(months):
        if _previous(later) != earlier:
            table.problem(table.header_row, f"m:{month_key(later)}",
                          f"The months must follow one another: {month_key(earlier)} is followed "
                          f"by {month_key(later)}.")  # fmt: skip
            return None
    return months


def _balances(table: Table, chart: Chart, months: list[date],
              out: Outcome) -> dict[str, dict[date | None, Decimal]]:  # fmt: skip
    """Per chart account: the balance at the end of each month (None: the opening)."""
    found: dict[str, dict[date | None, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    unknown: dict[str, tuple[str, list[int]]] = {}
    for number, cells in table.rows:
        code = cell(table, number, "account", tables.text(cells.get("account"), 200))
        name = cell(table, number, "name", tables.text(cells.get("name"), 200)) or ""
        keys = {m: f"m:{month_key(m)}" for m in months}
        values: dict[date | None, Decimal | None] = {
            m: cell(table, number, key, tables.amount(cells.get(key))) for m, key in keys.items()
        }
        values[None] = cell(table, number, "opening", tables.amount(cells.get("opening")))
        if code is None or None in values.values() or templates.is_total(code, name):
            continue
        if not any(values.values()):
            continue
        account = chart.resolve(code, name)
        if account is None:
            unknown.setdefault(code or name, (name, []))[1].append(number)
            continue
        if not account.is_postable:
            table.problem(number, "account", f"{account.code} is a heading; map this line to a "
                                             "postable account.")  # fmt: skip
            continue
        for month, value in values.items():
            found[account.code][month] += value or ZERO
    for code, (name, rows) in unknown.items():
        out.unknown_accounts.append(UnknownAccount(code, name, tuple(rows)))
        table.problem(rows[0], "account", f"{code} is not in the chart: map it to an account, or "
                                          "import the chart first.")  # fmt: skip
    return found


def _movements(balances: dict[str, dict[date | None, Decimal]], chart: Chart, months: list[date],
               req: PriorRequest, fiscal_month: int) -> list[Fact]:  # fmt: skip
    """Each account's movement per month. Balance-sheet accounts: the change in balance (the
    opening, if given, becomes the month before the first). Income and expense: the change in the
    year-to-date amount, which starts again in the fiscal year's first month."""
    facts: list[Fact] = []
    for code, by_month in balances.items():
        account = chart.by_code[code]
        result = account.type in PROFIT_AND_LOSS
        previous = ZERO if result else by_month.get(None, ZERO)
        if not result and previous:
            before = _previous(months[0])
            facts.append(Fact(account.id, before, max(previous, ZERO), max(-previous, ZERO)))
        for month in months:
            value = by_month.get(month, ZERO)
            if result and (not req.year_to_date or month.month == fiscal_month):
                previous = ZERO
            movement = value if (result and not req.year_to_date) else value - previous
            previous = value
            if movement:
                facts.append(Fact(account.id, month, max(movement, ZERO), max(-movement, ZERO)))
    return facts


def _check_balanced(facts: list[Fact], months: list[date], table: Table) -> None:
    net: dict[date, Decimal] = defaultdict(Decimal)
    for f in facts:
        net[f.period] += f.net_debit
    for month in months:
        if net[month]:
            table.problem(table.header_row, f"m:{month_key(month)}",
                          f"{month_key(month)} does not balance: the movements differ by "
                          f"{abs(net[month]):.2f}.")  # fmt: skip


def _check_opening(entity_id: UUID, facts: list[Fact], chart: Chart, out: Outcome,
                   table: Table) -> None:  # fmt: skip
    """The last month's asset and liability balances must equal the opening entry's."""
    entry = (JournalEntry.objects.filter(legal_entity_id=entity_id, description__startswith=OPENING,
                                         source=JournalEntry.Source.IMPORT)
             .exclude(status=JournalEntry.Status.VOID).first())  # fmt: skip
    if entry is None:
        out.warnings.append("No opening entry was imported yet, so the last month could not be "
                            "checked against the opening balances.")  # fmt: skip
        return
    by_id = {a.id: a for a in chart.by_code.values()}
    prior: dict[str, Decimal] = defaultdict(Decimal)
    for f in facts:
        prior[by_id[f.account_id].code] += f.net_debit
    opening: dict[str, Decimal] = defaultdict(Decimal)
    for ln in JournalLine.objects.filter(entry=entry).select_related("account"):
        opening[ln.account.code] += ln.debit - ln.credit
    for code in sorted(set(prior) | set(opening)):
        account = chart.by_code[code]
        if account.type not in ("ASSET", "LIABILITY") or prior[code] == opening[code]:
            continue
        table.problem(0, "account", f"{code} {account.name}: the last month ends at "
                                    f"{prior[code]:.2f} but the opening entry has "
                                    f"{opening[code]:.2f}.")  # fmt: skip


def import_prior_year(ctx: WorkspaceContext, entity_id: UUID, req: PriorRequest, *,
                      commit: bool = False) -> Outcome:  # fmt: skip
    out = Outcome("prior-year")
    entity = get_entity(ctx, entity_id, "ledger.entry.create")
    start = books_start(ctx, entity.id)
    accounts = account_list(ctx, entity.id)
    by_name: dict[str, list[Account]] = defaultdict(list)
    for a in accounts:
        if a.is_postable:
            by_name[tables.normalise(a.name)].append(a)
    chart = Chart(
        {a.code: a for a in accounts},
        by_name,
        {k.strip(): v.strip() for k, v in req.account_map.items() if v.strip()},
    )
    table = read_upload(req.upload, "prior-year",
                        lambda f: ("account" in f or "name" in f)
                        and any(k.startswith("m:") for k in f),
                        "No header row with an account column and month columns (such as "
                        "2025-01) was found in the first 10 rows.", out, _dynamic)  # fmt: skip
    if start is None:
        out.problems.append(Problem(0, "", "Create the first fiscal year first: the prior year is "
                                           "the months before it."))  # fmt: skip
    if table is None or start is None:
        return run(ctx, entity.id, out, commit, lambda: None)
    months = _months(table)
    facts: list[Fact] = []
    if months:
        late = [m for m in months if m >= start.replace(day=1)]
        if late:
            table.problem(table.header_row, f"m:{month_key(late[0])}",
                          f"{month_key(late[0])} is inside the books (from {start:%d/%m/%Y}); the "
                          "prior year is the months before.")  # fmt: skip
        out.months = [month_key(m) for m in months]
        balances = _balances(table, chart, months, out)
        out.accounts = sorted(balances)
        facts = _movements(balances, chart, months, req, start.month)
        _check_balanced(facts, months, table)
        if not late:
            _check_opening(entity.id, facts, chart, out, table)
    out.problems.extend(table.problems)
    if not facts and not out.problems:
        out.problems.append(Problem(0, "", "There are no balances to import.", req.upload.name))
    if any(f.period < (months or [start])[0] for f in facts):
        out.warnings.append("The opening column is kept as the month before the first, so the "
                            "first month shows its own movement.")  # fmt: skip

    def create() -> None:
        replace_comparatives(ctx, entity.id, facts, {
            "file": req.upload.name, "sha256": req.upload.sha256, "months": out.months,
            "accounts": len(out.accounts), "year_to_date": req.year_to_date,
        })  # fmt: skip

    return run(ctx, entity.id, out, commit, create)
