"""Opening balances and the invoices still open behind them (R-2, #245; R-3, #246).

Sources, any mix:
- the opening trial balance: the template, an accountant's year-end trial balance as delivered or
  a package's trial balance report (account, name, debit and credit, or a signed balance, "Dr"
  and "Cr" included). Subtotal and total rows are skipped, and the file's last total is checked
  against its lines; rows with no balance (headings, zero accounts) are skipped;
- the open invoices template (with an account column);
- a package's aged receivables or aged payables report: the customer or supplier named (by code
  or by name), the invoice, its dates and the amount outstanding, on the entity's receivables or
  payables account unless the report has an account column.

The result is **one draft entry** (see ``services``). Optionally the year's income and expense
balances are carried into an equity account (retained earnings), as when an accountant's
year-end trial balance opens the next year. Customers or suppliers a report names that are not
set up are listed; on request they are created with the import (set-up data).
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction

from fcp.core.errors import DomainError
from fcp.modules.ledger.api import (
    Account,
    EntryInput,
    JournalEntry,
    JournalLine,
    LineInput,
    account_list,
    create_entry_draft,
    fiscal_year_list,
)
from fcp.modules.registers.api import CounterpartyInput, add_counterparty, counterparty_list
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import tables, templates
from .services import (
    OPENING,
    ZERO,
    Outcome,
    PlannedLine,
    UnknownAccount,
    UnknownCounterparty,
    Upload,
    cell,
    read_upload,
    run,
)
from .tables import Problem, Table

RECEIVABLE, PAYABLE = "RECEIVABLE", "PAYABLE"
PROFIT_AND_LOSS = ("INCOME", "EXPENSE")


@dataclass(frozen=True)
class OpeningRequest:
    as_of: date
    trial_balance: Upload
    open_items: Upload | None = None
    aged_receivables: Upload | None = None
    aged_payables: Upload | None = None
    account_map: dict[str, str] = field(default_factory=dict)
    results_account: str = ""  # carry income and expense into this equity account
    day_first: bool = True
    create_counterparties: bool = False


@dataclass
class _Party:
    """A customer or supplier: set up already (``id``), or to be created with the import."""

    code: str
    name: str
    payment_terms_days: int
    id: UUID | None = None
    kind: str = ""


@dataclass
class _Item:
    row: int
    file: str
    account: Account
    party: _Party
    invoice: str
    invoice_date: date | None
    due_date: date | None
    amount: Decimal  # positive: what the customer owes, or what is owed to the supplier


@dataclass
class _Chart:
    by_code: dict[str, Account]
    by_name: dict[str, list[Account]]
    account_map: dict[str, str]

    def resolve(self, code: str, name: str) -> Account | None:
        """The chart account for a file's account: as mapped, by code, by the code at the start
        of "1200 Trade receivables", or by a name only one account has."""
        key = code or name
        mapped = self.account_map.get(key)
        if mapped:
            return self.by_code.get(mapped.strip().upper())
        if code:
            first = code.split(maxsplit=1)[0].upper()
            found = self.by_code.get(code.upper()) or self.by_code.get(first)
            if found:
                return found
        same = self.by_name.get(tables.normalise(name or code), [])
        return same[0] if len(same) == 1 else None


# --- the trial balance --------------------------------------------------------------------------


def _check_file_total(table: Table, sums: tuple[Decimal, Decimal],
                      total: tuple[int, Decimal, Decimal, Decimal] | None) -> None:  # fmt: skip
    """The file's last total row, if it has amounts, must equal its lines."""
    if total is None:
        return
    number, debit, credit, balance = total
    lines_debit, lines_credit = sums
    if debit or credit:
        if (debit, credit) != (lines_debit, lines_credit):
            table.problem(number, "debit", f"The file's total ({debit:.2f} / {credit:.2f}) "
                                           f"differs from its lines ({lines_debit:.2f} / "
                                           f"{lines_credit:.2f}).")  # fmt: skip
    elif balance and balance != lines_debit - lines_credit:
        table.problem(number, "balance", f"The file's total ({balance:.2f}) differs from its "
                                         f"lines ({lines_debit - lines_credit:.2f}).")  # fmt: skip


def _balances(table: Table, chart: _Chart, out: Outcome) -> dict[str, Decimal]:
    """Net debit balance per chart account (several file accounts may map to one)."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    unknown: dict[str, tuple[str, list[int]]] = {}
    sums = [ZERO, ZERO]
    last_total: tuple[int, Decimal, Decimal, Decimal] | None = None
    for number, cells in table.rows:
        code = cell(table, number, "account", tables.text(cells.get("account"), 200))
        name = cell(table, number, "name", tables.text(cells.get("name"), 200)) or ""
        debit = cell(table, number, "debit", tables.amount(cells.get("debit")))
        credit = cell(table, number, "credit", tables.amount(cells.get("credit")))
        balance = cell(table, number, "balance", tables.amount(cells.get("balance")))
        if None in (code, debit, credit, balance):
            continue
        if templates.is_total(code, name):
            last_total = (number, debit, credit, balance) if debit or credit or balance else None
            continue
        net = debit - credit + balance
        if not net:  # a heading, or an account with no balance
            continue
        if (debit or credit) and balance:
            table.problem(number, "balance", "Use Debit and Credit, or Balance, not both.")
            continue
        sums[0] += max(net, ZERO)
        sums[1] += max(-net, ZERO)
        if not code and not name:
            table.problem(number, "account", "Enter the account code.")
            continue
        account = chart.resolve(code, name)
        if account is None:
            seen = unknown.setdefault(code or name, (name, []))
            seen[1].append(number)
            continue
        if not account.is_postable or account.status != Account.Status.ACTIVE:
            table.problem(number, "account", f"{account.code} is a heading or inactive; map this "
                                             "line to a postable account.")  # fmt: skip
            continue
        totals[account.code] += net
    _check_file_total(table, (sums[0], sums[1]), last_total)
    for code, (name, rows) in unknown.items():
        out.unknown_accounts.append(UnknownAccount(code, name, tuple(rows)))
        table.problem(rows[0], "account", f"{code} is not in the chart: map it to an account, or "
                                          "import the chart first.")  # fmt: skip
    return totals


def _carry_results(totals: dict[str, Decimal], chart: _Chart, code: str, table: Table) -> None:
    """Move the income and expense balances into ``code`` (retained earnings)."""
    target = chart.by_code.get(code.strip().upper())
    if target is None or target.type != "EQUITY" or not target.is_postable:
        table.problem(0, "", f"{code} is not a postable equity account of the chart; choose the "
                             "retained earnings account.")  # fmt: skip
        return
    result = ZERO
    for account_code in [c for c in totals if chart.by_code[c].type in PROFIT_AND_LOSS]:
        result += totals.pop(account_code)
    totals[target.code] = totals.get(target.code, ZERO) + result


# --- the open invoices --------------------------------------------------------------------------


class _Parties:
    def __init__(self, existing: list[Any], create: bool) -> None:
        self.by_code = {c.code: _Party(c.code, c.name, c.payment_terms_days, c.id)
                        for c in existing}  # fmt: skip
        self.by_name: dict[str, list[_Party]] = defaultdict(list)
        for party in self.by_code.values():
            self.by_name[tables.normalise(party.name)].append(party)
        self.create = create
        self.new: dict[str, _Party] = {}  # normalised name -> to be created
        self.unknown: dict[tuple[str, str], list[tuple[str, int]]] = {}

    def _new_code(self, name: str) -> str:
        stem = re.sub(r"[^0-9A-Z]+", "-", tables.normalise(name).upper()).strip("-")[:24] or "P"
        code, n = stem, 1
        taken = set(self.by_code) | {p.code for p in self.new.values()}
        while code in taken:
            n += 1
            code = f"{stem}-{n}"
        return code

    def find(self, text: str, side: str, where: tuple[str, int]) -> _Party | None:
        found = self.by_code.get(text.upper())
        if found:
            return found
        same = self.by_name.get(tables.normalise(text), [])
        if len(same) == 1:
            return same[0]
        key = tables.normalise(text)
        if key in self.new:
            return self.new[key]
        if self.create and not same and side:
            kind = "CUSTOMER" if side == RECEIVABLE else "SUPPLIER"
            self.new[key] = _Party(self._new_code(text), text, 30, None, kind)
            return self.new[key]
        self.unknown.setdefault((text, side), []).append(where)
        return None


def _default_account(chart: _Chart, side: str) -> Account | None:
    found = [
        a
        for a in chart.by_code.values()
        if a.control_type == side and a.is_postable and a.status == Account.Status.ACTIVE
    ]
    return found[0] if len(found) == 1 else None  # fmt: skip


def _items(table: Table, chart: _Chart, parties: _Parties, side: str | None,
           day_first: bool, seen: dict[tuple[str, str, str], int]) -> list[_Item]:  # fmt: skip
    """``side``: None for the template (an account column), else the report's side."""
    found: list[_Item] = []
    default = _default_account(chart, side) if side else None
    if side and default is None and "account" not in table.columns:
        label = "receivables" if side == RECEIVABLE else "payables"
        table.problem(0, "", f"The chart has no single {label} account; add an Account code "
                             "column to the report.")  # fmt: skip
        return found
    for number, cells in table.rows:
        code = cell(table, number, "account", tables.text(cells.get("account"), 200))
        party = cell(table, number, "counterparty", tables.text(cells.get("counterparty"), 200))
        invoice = cell(table, number, "invoice", tables.text(cells.get("invoice"), 60))
        issued = cell(
            table,
            number,
            "invoice_date",
            tables.day(cells.get("invoice_date"), day_first=day_first),
        )
        due = cell(table, number, "due_date", tables.day(cells.get("due_date"),
                                                          day_first=day_first))  # fmt: skip
        value = cell(table, number, "amount", tables.amount(cells.get("amount")))
        if None in (code, party, invoice, value):
            continue
        if templates.is_total(party, invoice) or (side and not value):
            continue
        account = chart.resolve(code, "") if code else default
        wanted = side or (account.control_type if account else "")
        where = (table.file, number)
        counterparty = parties.find(party, wanted, where) if party else None
        invoice = invoice or ("" if side is None else "Opening balance")
        problems = (
            ("account", "Enter the account code." if not code and side is None else
             f"{code} is not a receivables or payables account of the chart."
             if account is None or not account.control_type else ""),
            ("counterparty", "Enter the customer or supplier." if not party else ""),
            ("invoice", "Enter the invoice number." if not invoice else ""),
            ("amount", "Enter the amount outstanding." if not value else ""),
        )  # fmt: skip
        if any(message for _, message in problems) or counterparty is None:
            for key, message in problems:
                if message:
                    table.problem(number, key, message)
            continue
        assert account is not None  # noqa: S101 - checked above
        ident = (account.code, counterparty.code, invoice.upper())
        if ident in seen:
            table.problem(number, "invoice", f"Invoice {invoice} of {counterparty.code} is also "
                                             f"on row {seen[ident]}.")  # fmt: skip
            continue
        seen[ident] = number
        found.append(_Item(number, table.file, account, counterparty, invoice, issued, due, value))
    return found


def _already_booked(entity_id: UUID, items: list[_Item], tables_by_file: dict[str, Table]) -> None:
    """An invoice already among the entity's entries (not void) would be counted twice."""
    known = [i for i in items if i.party.id is not None]
    if not known:
        return
    booked = {
        (a, c, r.upper())
        for a, c, r in JournalLine.objects.filter(
            entry__legal_entity_id=entity_id, account_id__in={i.account.id for i in known},
            counterparty_id__in={i.party.id for i in known},
        )
        .exclude(entry__status=JournalEntry.Status.VOID)
        .exclude(reference="")
        .values_list("account_id", "counterparty_id", "reference")
    }  # fmt: skip
    for item in known:
        if (item.account.id, item.party.id, item.invoice.upper()) in booked:
            tables_by_file[item.file].problem(
                item.row, "invoice",
                f"Invoice {item.invoice} of {item.party.code} is already in the books.",
            )  # fmt: skip


# --- the entry ----------------------------------------------------------------------------------


def _plan_lines(totals: dict[str, Decimal], items: list[_Item], chart: _Chart,
                tb: Table) -> list[PlannedLine]:  # fmt: skip
    by_account: dict[str, list[_Item]] = defaultdict(list)
    for item in items:
        by_account[item.account.code].append(item)
    lines: list[PlannedLine] = []
    for code in sorted(set(totals) | set(by_account)):
        account, net = chart.by_code[code], totals.get(code, ZERO)
        if not account.control_type:
            if net:
                lines.append(PlannedLine(code, account.name, max(net, ZERO), max(-net, ZERO)))
            continue
        sign = 1 if account.control_type == RECEIVABLE else -1
        listed = sum((i.amount for i in by_account[code]), ZERO) * sign
        if listed != net:
            files = ", ".join(sorted({i.file for i in by_account[code]}))
            tb.problem(0, "account", f"{code} {account.name}: the trial balance shows "
                                     f"{net:.2f} (debit positive) but " + (
                f"the open invoices ({files}) add up to {listed:.2f}. List the invoices behind "
                "this balance." if files else "no open invoices are listed for it: add the open "
                "invoices file or an aged report."))  # fmt: skip
            continue
        for item in by_account[code]:
            value = item.amount * sign
            due = item.due_date or (item.invoice_date and item.invoice_date + timedelta(
                days=item.party.payment_terms_days))  # fmt: skip
            lines.append(PlannedLine(
                code, account.name, max(value, ZERO), max(-value, ZERO),
                item.party.code, item.invoice, due or None,
            ))  # fmt: skip
    return lines


def _read_items(req: OpeningRequest, chart: _Chart, parties: _Parties,
                out: Outcome) -> tuple[list[_Item], dict[str, Table]]:  # fmt: skip
    items: list[_Item] = []
    read: dict[str, Table] = {}
    seen: dict[tuple[str, str, str], int] = {}
    sources = ((req.open_items, None), (req.aged_receivables, RECEIVABLE),
               (req.aged_payables, PAYABLE))  # fmt: skip
    for upload, side in sources:
        if upload is None:
            continue
        if side is None:
            ready = lambda f: {"account", "counterparty", "invoice", "amount"} <= f  # noqa: E731
            missing = (
                "No header row with Account code, Customer or supplier code, Invoice "
                "number and Amount outstanding columns was found in the first 10 rows."
            )
        else:
            ready = lambda f: {"counterparty", "amount"} <= f  # noqa: E731
            missing = ("No header row with a customer or supplier column and an amount "
                       "outstanding column was found in the first 10 rows.")  # fmt: skip
        table = read_upload(upload, "open-items", ready, missing, out)
        if table is None:
            continue
        read[upload.name] = table
        items += _items(table, chart, parties, side, req.day_first, seen)
    for (name, side), where in parties.unknown.items():
        out.unknown_counterparties.append(
            UnknownCounterparty(name, side, tuple(n for _, n in where))
        )
        file, row = where[0]
        read[file].problem(row, "counterparty", f"{name} is not set up: import the customers and "
                                                "suppliers first, or choose to create them with "
                                                "this import.")  # fmt: skip
    return items, read


def _checks(ctx: WorkspaceContext, entity_id: UUID, as_of: date, out: Outcome) -> None:
    if not any(fy.start_date <= as_of <= fy.end_date for fy in fiscal_year_list(ctx, entity_id)):
        out.problems.append(Problem(0, "", f"No fiscal year contains {as_of:%d/%m/%Y}: create it "
                                           "first (Settings, fiscal years)."))  # fmt: skip
    earlier = JournalEntry.objects.filter(
        legal_entity_id=entity_id, source=JournalEntry.Source.IMPORT,
        description__startswith=OPENING,
    ).exclude(status=JournalEntry.Status.VOID).first()  # fmt: skip
    if earlier is not None:
        out.problems.append(Problem(0, "", f"Opening balances were already imported "
                                           f"({earlier.description}); void that entry first to "
                                           "import them again."))  # fmt: skip


def import_opening_balances(ctx: WorkspaceContext, entity_id: UUID, req: OpeningRequest, *,
                            commit: bool = False) -> Outcome:  # fmt: skip
    """One draft entry dated ``req.as_of``: a line per account of the trial balance, and for each
    receivables or payables account a line per open invoice instead (they must add up to the
    account's balance). The entry must balance; it is then approved and posted as usual."""
    out = Outcome("opening-balances")
    entity = get_entity(ctx, entity_id, "ledger.entry.create")
    accounts = account_list(ctx, entity.id)
    by_name: dict[str, list[Account]] = defaultdict(list)
    for a in accounts:
        if a.is_postable:
            by_name[tables.normalise(a.name)].append(a)
    chart = _Chart(
        {a.code: a for a in accounts},
        by_name,
        {k.strip(): v.strip() for k, v in req.account_map.items() if v.strip()},
    )
    tb = read_upload(req.trial_balance, "opening-balances",
                     lambda f: ("account" in f or "name" in f)
                     and ("balance" in f or {"debit", "credit"} <= f),
                     "No header row with an account column and Debit and Credit (or Balance) "
                     "columns was found in the first 10 rows.", out)  # fmt: skip
    _checks(ctx, entity.id, req.as_of, out)
    if tb is None:
        return run(ctx, entity.id, out, commit, lambda: None)
    totals = _balances(tb, chart, out)
    if req.results_account:
        _carry_results(totals, chart, req.results_account, tb)
    parties = _Parties(counterparty_list(ctx, entity.id), req.create_counterparties)
    items, read = _read_items(req, chart, parties, out)
    _already_booked(entity.id, items, read)
    for table in read.values():
        out.problems.extend(table.problems)
    out.counterparties = [p.code for p in parties.new.values()]
    out.lines = _plan_lines(totals, items, chart, tb)
    out.problems.extend(tb.problems)
    out.total_debit = sum((ln.debit for ln in out.lines), ZERO)
    out.total_credit = sum((ln.credit for ln in out.lines), ZERO)
    name = req.trial_balance.name
    if out.difference:
        out.problems.append(Problem(0, "", f"The trial balance does not balance: debits "
                                           f"{out.total_debit:.2f}, credits "
                                           f"{out.total_credit:.2f}, difference "
                                           f"{abs(out.difference):.2f}.", name))  # fmt: skip
    if not out.lines and not out.problems:
        out.problems.append(Problem(0, "", "There are no balances to import.", name))
    if any(chart.by_code[ln.account_code].type in PROFIT_AND_LOSS for ln in out.lines):
        out.warnings.append("Income and expense accounts have balances. At the start of a year "
                            "they are normally zero, with the result in retained earnings: "
                            "choose the account to carry them into, or keep them only if you "
                            "start part way through the year.")  # fmt: skip

    def create() -> None:
        ids = {p.code: p.id for p in parties.by_code.values()}
        for party in parties.new.values():
            try:
                with transaction.atomic():
                    made = add_counterparty(ctx, entity.id, CounterpartyInput(
                        code=party.code, name=party.name, kind=party.kind))  # fmt: skip
            except DomainError as refused:
                out.problems.append(Problem(0, "", f"{party.name}: {refused.detail}"))
                continue
            ids[party.code] = made.id
        settle = f"{entity.jurisdiction}:SETTLE:open"
        lines = [LineInput(
            account_id=chart.by_code[ln.account_code].id, debit=str(ln.debit),
            credit=str(ln.credit),
            memo=(f"Invoice {ln.reference}" if ln.reference else "Opening balance"),
            counterparty_id=ids.get(ln.counterparty_code), reference=ln.reference,
            due_date=ln.due_date,
            # A VAT account's opening balance is not a transaction of any VAT return.
            vat_code_id=settle if chart.by_code[ln.account_code].vat_role else None,
        ) for ln in out.lines]  # fmt: skip
        entry = create_entry_draft(ctx, entity.id, EntryInput(
            accounting_date=req.as_of, description=f"{OPENING} {req.as_of:%d/%m/%Y} (imported)",
            lines=lines,
        ))  # fmt: skip
        out.entry_id = entry.id

    return run(ctx, entity.id, out, commit, create)
