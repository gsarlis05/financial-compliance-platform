"""Bringing existing books in from spreadsheets (R-2, #245; brief 26).

Three imports, done in this order:
1. the chart of accounts: accounts are created directly (set-up data);
2. customers and suppliers: created directly (set-up data);
3. the opening trial balance, with the open customer and supplier invoices behind the balances of
   the receivables and payables accounts: **one draft entry**, which follows the normal approval
   and posting workflow. Nothing is posted by an import.

Every import is checked in full first, and every problem is listed with its file, row and column.
Then the import runs inside a transaction: a preview always rolls it back, so it shows exactly what
would be created (the services' own checks included). Nothing is created while any problem
remains. A completed import is audited with the file's SHA-256.
"""

import hashlib
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from fcp.core.errors import DomainError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger.api import (
    Account,
    AccountInput,
    EntryInput,
    JournalEntry,
    JournalLine,
    LineInput,
    account_list,
    add_account,
    create_entry_draft,
    fiscal_year_list,
)
from fcp.modules.registers.api import (
    CounterpartyInput,
    add_counterparty,
    counterparty_list,
)
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from . import tables, templates
from .tables import Problem, Table, TableError

ZERO = Decimal(0)
MAX_TERMS = 365
OPENING = "Opening balances at"

ACCOUNT_TYPES = {"asset": "ASSET", "assets": "ASSET", "liability": "LIABILITY",
                 "liabilities": "LIABILITY", "equity": "EQUITY", "capital": "EQUITY",
                 "income": "INCOME", "revenue": "INCOME", "expense": "EXPENSE",
                 "expenses": "EXPENSE", "cost": "EXPENSE"}  # fmt: skip
CONTROLS = {"": "", "receivable": "RECEIVABLE", "receivables": "RECEIVABLE",
            "payable": "PAYABLE", "payables": "PAYABLE"}  # fmt: skip
VAT_ROLES = {"": "", "input": "INPUT", "output": "OUTPUT"}
KINDS = {"customer": "CUSTOMER", "supplier": "SUPPLIER", "both": "BOTH",
         "vendor": "SUPPLIER", "customer and supplier": "BOTH"}  # fmt: skip


@dataclass(frozen=True)
class Upload:
    name: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True)
class UnknownAccount:
    code: str
    name: str
    rows: tuple[int, ...]


@dataclass(frozen=True)
class PlannedLine:
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    counterparty_code: str = ""
    reference: str = ""
    due_date: date | None = None


@dataclass
class Outcome:
    kind: str
    committed: bool = False
    rows: int = 0
    problems: list[Problem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unknown_accounts: list[UnknownAccount] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)  # codes created (or to be created)
    counterparties: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # already there, identical
    lines: list[PlannedLine] = field(default_factory=list)
    total_debit: Decimal = ZERO
    total_credit: Decimal = ZERO
    entry_id: UUID | None = None
    files: dict[str, str] = field(default_factory=dict)  # name -> SHA-256

    @property
    def difference(self) -> Decimal:
        return self.total_debit - self.total_credit


def _read(upload: Upload, kind: str, ready: Callable[[set[str]], bool], missing: str,
          out: Outcome) -> Table | None:  # fmt: skip
    out.files[upload.name] = upload.sha256
    try:
        table = tables.read(upload.data, upload.name, templates.fields(kind), ready, missing)
    except TableError as refused:
        out.problems.append(Problem(0, "", str(refused), upload.name))
        return None
    out.problems.extend(table.problems)
    out.rows += len(table.rows)
    return table


def _cell(table: Table, number: int, key: str, found: Any) -> Any:
    """``found`` as read, or None after recording its problem against the row and column."""
    if isinstance(found, Problem):
        table.problem(number, key, found.message)
        return None
    return found


def _run(ctx: WorkspaceContext, entity_id: UUID, out: Outcome, commit: bool,
         create: Callable[[], None]) -> Outcome:  # fmt: skip
    """Run ``create`` in a transaction: kept only when committing and nothing went wrong."""
    if out.problems:
        out.problems = tables.merged(out.problems)
        return out
    with transaction.atomic():
        try:
            create()
        except DomainError as refused:
            out.problems.append(Problem(0, "", refused.detail))
        if out.problems or not commit:
            transaction.set_rollback(True)
            return out
        audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id,
              action="onboarding.import.completed", subject_type="import",
              subject_id=out.entry_id or uuid4(), entity_id=entity_id,
              changes={"kind": out.kind, "files": out.files, "rows": out.rows,
                       "accounts_created": out.accounts,
                       "counterparties_created": len(out.counterparties),
                       "entry_id": out.entry_id})  # fmt: skip
        out.committed = True
    return out


# --- 1. the chart of accounts -------------------------------------------------------------------


@dataclass
class _AccountRow:
    row: int
    data: AccountInput


def _account_row(table: Table, number: int, cells: dict[str, object]) -> _AccountRow | None:
    code = _cell(table, number, "code", tables.text(cells.get("code"), 20))
    name = _cell(table, number, "name", tables.text(cells.get("name"), 200))
    raw_type = _cell(table, number, "type", tables.text(cells.get("type"), 30))
    parent = _cell(table, number, "parent_code", tables.text(cells.get("parent_code"), 20))
    postable = _cell(
        table,
        number,
        "postable",
        tables.flag(cells.get("postable"), True, templates.YES, templates.NO),
    )
    control = _cell(table, number, "control", tables.text(cells.get("control"), 20))
    vat_role = _cell(table, number, "vat_role", tables.text(cells.get("vat_role"), 20))
    name_el = _cell(table, number, "name_el", tables.text(cells.get("name_el"), 200))  # fmt: skip
    if code == "":
        table.problem(number, "code", "Enter the account code.")
    if name == "":
        table.problem(number, "name", "Enter the account name.")
    account_type = ACCOUNT_TYPES.get(tables.normalise(raw_type or ""))
    if raw_type is not None and account_type is None:
        table.problem(number, "type", "Enter Asset, Liability, Equity, Income or Expense.")
    control_type = CONTROLS.get(tables.normalise(control or ""))
    if control is not None and control_type is None:
        table.problem(number, "control", "Enter Receivable, Payable or leave it blank.")
    role = VAT_ROLES.get(tables.normalise(vat_role or ""))
    if vat_role is not None and role is None:
        table.problem(number, "vat_role", "Enter Input, Output or leave it blank.")
    if None in (code, name, account_type, postable, control_type, role, parent, name_el) or "" in (
        code, name,
    ):  # fmt: skip
        return None
    return _AccountRow(number, AccountInput(
        code=str(code).upper(), name=str(name), type=str(account_type), name_el=str(name_el),
        parent_code=str(parent).upper() or None, is_postable=bool(postable),
        control_type=str(control_type), vat_role=str(role),
    ))  # fmt: skip


def _check_parents(table: Table, todo: dict[str, _AccountRow], chart: dict[str, Account]) -> None:
    for code, r in todo.items():
        parent_code = r.data.parent_code
        if not parent_code:
            continue
        parent = todo.get(parent_code)
        heading, kind = ((not parent.data.is_postable, parent.data.type) if parent else
                         (not chart[parent_code].is_postable, chart[parent_code].type)
                         if parent_code in chart else (None, None))  # fmt: skip
        if heading is None:
            table.problem(r.row, "parent_code", f"{parent_code} is neither in this file nor in "
                                                "the chart.")  # fmt: skip
        elif not heading:
            table.problem(r.row, "parent_code", f"{parent_code} is postable; a parent must be a "
                                                "heading (Postable: No).")  # fmt: skip
        elif kind != r.data.type:
            table.problem(r.row, "type", f"{code} must have the same type as its heading "
                                         f"{parent_code}.")  # fmt: skip


def _check_chart(table: Table, rows: list[_AccountRow], chart: dict[str, Account],
                 out: Outcome) -> list[_AccountRow]:  # fmt: skip
    """The rows to create, parents first; the others are reported or skipped."""
    seen: dict[str, _AccountRow] = {}
    for r in rows:
        if r.data.code in seen:
            table.problem(r.row, "code", f"{r.data.code} is also on row {seen[r.data.code].row}.")
        else:
            seen[r.data.code] = r
    todo: dict[str, _AccountRow] = {}
    for code, r in seen.items():
        existing = chart.get(code)
        if existing is None:
            todo[code] = r
        elif existing.name == r.data.name and existing.type == r.data.type:
            out.skipped.append(code)
        else:
            table.problem(r.row, "code", f"{code} is already in the chart as {existing.name!r} "
                                         f"({existing.type.title()}).")  # fmt: skip
    _check_parents(table, todo, chart)
    ordered: list[_AccountRow] = []
    placed: set[str] = set()
    while len(ordered) < len(todo):
        ready = [r for c, r in todo.items() if c not in placed and (
            not r.data.parent_code or r.data.parent_code not in todo
            or r.data.parent_code in placed)]  # fmt: skip
        if not ready:  # a loop of parents
            for c, r in todo.items():
                if c not in placed:
                    table.problem(r.row, "parent_code", "The parents form a loop.")
            break
        for r in ready:
            ordered.append(r)
            placed.add(r.data.code)
    return ordered


def import_chart(ctx: WorkspaceContext, entity_id: UUID, upload: Upload, *,
                 commit: bool = False) -> Outcome:  # fmt: skip
    out = Outcome("chart")
    entity = get_entity(ctx, entity_id, "ledger.account.manage")
    table = _read(upload, "chart", lambda f: {"code", "name", "type"} <= f,
                  "No header row with Code, Name and Type columns was found in the first 10 "
                  "rows.", out)  # fmt: skip
    if table is None:
        return _run(ctx, entity.id, out, commit, lambda: None)
    rows = [r for n, cells in table.rows if (r := _account_row(table, n, cells))]
    chart = {a.code: a for a in account_list(ctx, entity.id)}
    ordered = _check_chart(table, rows, chart, out)
    out.problems.extend(table.problems)
    out.accounts = [r.data.code for r in ordered]

    def create() -> None:
        for r in ordered:
            try:
                with transaction.atomic():
                    add_account(ctx, entity.id, r.data)
            except DomainError as refused:
                out.problems.append(Problem(r.row, "", refused.detail, upload.name))

    return _run(ctx, entity.id, out, commit, create)


# --- 2. customers and suppliers -----------------------------------------------------------------


def _counterparty_row(
    table: Table, number: int, cells: dict[str, object]
) -> tuple[int, CounterpartyInput] | None:
    got = {k: _cell(table, number, k, tables.text(cells.get(k), n)) for k, n in
           (("code", 30), ("name", 200), ("kind", 30), ("vat_no", 30), ("email", 320),
            ("payment_terms_days", 3), ("country", 2))}  # fmt: skip
    for key, label in (("code", "code"), ("name", "name")):
        if got[key] == "":
            table.problem(number, key, f"Enter the {label}.")
    kind = KINDS.get(tables.normalise(got["kind"] or ""))
    if got["kind"] is not None and kind is None:
        table.problem(number, "kind", "Enter Customer, Supplier or Both.")
    terms = got["payment_terms_days"]
    days = 30 if terms == "" else int(terms) if terms and terms.isdigit() else None
    if terms is not None and (days is None or days > MAX_TERMS):
        table.problem(number, "payment_terms_days", "Enter whole days from 0 to 365.")
        days = None
    country = (got["country"] or "").upper()
    if got["country"] and not country.isalpha():
        table.problem(number, "country", "Enter two letters, such as CY.")
        days = None
    if None in got.values() or kind is None or days is None or "" in (got["code"], got["name"]):
        return None
    return number, CounterpartyInput(
        code=str(got["code"]).upper(), name=str(got["name"]), kind=kind,
        vat_no=str(got["vat_no"]), email=str(got["email"]), payment_terms_days=days,
        country=country,
    )  # fmt: skip


def import_counterparties(ctx: WorkspaceContext, entity_id: UUID, upload: Upload, *,
                          commit: bool = False) -> Outcome:  # fmt: skip
    out = Outcome("counterparties")
    entity = get_entity(ctx, entity_id, "registers.counterparty.manage")
    table = _read(upload, "counterparties", lambda f: {"code", "name", "kind"} <= f,
                  "No header row with Code, Name and Kind columns was found in the first 10 "
                  "rows.", out)  # fmt: skip
    if table is None:
        return _run(ctx, entity.id, out, commit, lambda: None)
    existing = {c.code: c for c in counterparty_list(ctx, entity.id)}
    seen: dict[str, int] = {}
    todo: list[tuple[int, CounterpartyInput]] = []
    for number, cells in table.rows:
        found = _counterparty_row(table, number, cells)
        if found is None:
            continue
        data = found[1]
        if data.code in seen:
            table.problem(number, "code", f"{data.code} is also on row {seen[data.code]}.")
            continue
        seen[data.code] = number
        there = existing.get(data.code)
        if there is None:
            todo.append(found)
        elif there.name == data.name:
            out.skipped.append(data.code)
        else:
            table.problem(number, "code", f"{data.code} is already used by another customer or "
                                          "supplier.")  # fmt: skip
    out.problems.extend(table.problems)
    out.counterparties = [d.code for _, d in todo]

    def create() -> None:
        for number, data in todo:
            try:
                with transaction.atomic():
                    add_counterparty(ctx, entity.id, data)
            except DomainError as refused:
                out.problems.append(Problem(number, "", refused.detail, upload.name))

    return _run(ctx, entity.id, out, commit, create)


# --- 3. opening balances and open invoices -------------------------------------------------------


@dataclass
class _Item:
    row: int
    account: Account
    counterparty: Any
    invoice: str
    invoice_date: date | None
    due_date: date | None
    amount: Decimal  # positive: what the customer owes, or what is owed to the supplier


def _resolve(code: str, account_map: dict[str, str], chart: dict[str, Account]) -> Account | None:
    return chart.get(account_map.get(code, code).strip().upper())


def _balances(table: Table, chart: dict[str, Account], account_map: dict[str, str],
              out: Outcome) -> dict[str, Decimal]:  # fmt: skip
    """Net debit balance per chart account (several file accounts may map to one)."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    unknown: dict[str, tuple[str, list[int]]] = {}
    for number, cells in table.rows:
        code = _cell(table, number, "account", tables.text(cells.get("account"), 40))
        name = _cell(table, number, "name", tables.text(cells.get("name"), 200)) or ""
        debit = _cell(table, number, "debit", tables.amount(cells.get("debit")))
        credit = _cell(table, number, "credit", tables.amount(cells.get("credit")))
        balance = _cell(table, number, "balance", tables.amount(cells.get("balance")))
        if None in (code, debit, credit, balance):
            continue
        net = debit - credit + balance
        if code == "":
            if net:
                table.problem(number, "account", "Enter the account code.")
            continue
        if (debit or credit) and balance:
            table.problem(number, "balance", "Use Debit and Credit, or Balance, not both.")
            continue
        account = _resolve(code, account_map, chart)
        if account is None:
            seen = unknown.setdefault(code, (name, []))
            seen[1].append(number)
            continue
        if not account.is_postable or account.status != Account.Status.ACTIVE:
            table.problem(number, "account", f"{account.code} is a heading or inactive; map this "
                                             "line to a postable account.")  # fmt: skip
            continue
        totals[account.code] += net
    for code, (name, rows) in unknown.items():
        out.unknown_accounts.append(UnknownAccount(code, name, tuple(rows)))
        table.problem(rows[0], "account", f"{code} is not in the chart: map it to an account, or "
                                          "import the chart first.")  # fmt: skip
    return totals


def _items(table: Table, chart: dict[str, Account], account_map: dict[str, str],
           parties: dict[str, Any]) -> list[_Item]:  # fmt: skip
    found: list[_Item] = []
    seen: dict[tuple[str, str, str], int] = {}
    for number, cells in table.rows:
        code = _cell(table, number, "account", tables.text(cells.get("account"), 40))
        party = _cell(table, number, "counterparty", tables.text(cells.get("counterparty"), 30))
        invoice = _cell(table, number, "invoice", tables.text(cells.get("invoice"), 60))
        issued = _cell(table, number, "invoice_date", tables.day(cells.get("invoice_date")))
        due = _cell(table, number, "due_date", tables.day(cells.get("due_date")))
        value = _cell(table, number, "amount", tables.amount(cells.get("amount")))
        if None in (code, party, invoice, value):
            continue
        account = _resolve(code, account_map, chart)
        counterparty = parties.get(party.upper())
        problems = (
            ("account", "Enter the account code." if not code else
             f"{code} is not a receivables or payables account of the chart."
             if account is None or not account.control_type else ""),
            ("counterparty", "Enter the customer or supplier code." if not party else
             f"{party} is not set up: import the customers and suppliers first."
             if counterparty is None else ""),
            ("invoice", "Enter the invoice number." if not invoice else ""),
            ("amount", "Enter the amount outstanding." if not value else ""),
        )  # fmt: skip
        if any(message for _, message in problems):
            for key, message in problems:
                if message:
                    table.problem(number, key, message)
            continue
        assert account is not None and counterparty is not None  # noqa: S101, PT018 - checked
        ident = (account.code, counterparty.code, invoice.upper())
        if ident in seen:
            table.problem(number, "invoice", f"Invoice {invoice} of {counterparty.code} is also "
                                             f"on row {seen[ident]}.")  # fmt: skip
            continue
        seen[ident] = number
        found.append(_Item(number, account, counterparty, invoice, issued, due, value))
    return found


def _already_booked(entity_id: UUID, items: list[_Item], table: Table) -> None:
    """An invoice already among the entity's entries (not void) would be counted twice."""
    if not items:
        return
    booked = set(
        JournalLine.objects.filter(
            entry__legal_entity_id=entity_id, account_id__in={i.account.id for i in items},
            counterparty_id__in={i.counterparty.id for i in items},
        )
        .exclude(entry__status=JournalEntry.Status.VOID)
        .exclude(reference="")
        .values_list("account_id", "counterparty_id", "reference")
    )  # fmt: skip
    booked_upper = {(a, c, r.upper()) for a, c, r in booked}
    for item in items:
        if (item.account.id, item.counterparty.id, item.invoice.upper()) in booked_upper:
            table.problem(
                item.row,
                "invoice",
                f"Invoice {item.invoice} of {item.counterparty.code} is already in the books.",
            )


def _plan_lines(totals: dict[str, Decimal], items: list[_Item], chart: dict[str, Account],
                tb: Table, open_table: Table | None) -> list[PlannedLine]:  # fmt: skip
    by_account: dict[str, list[_Item]] = defaultdict(list)
    for item in items:
        by_account[item.account.code].append(item)
    lines: list[PlannedLine] = []
    for code in sorted(set(totals) | set(by_account)):
        account, net = chart[code], totals.get(code, ZERO)
        if not account.control_type:
            if net:
                lines.append(PlannedLine(code, account.name, max(net, ZERO), max(-net, ZERO)))
            continue
        sign = 1 if account.control_type == "RECEIVABLE" else -1
        listed = sum((i.amount for i in by_account[code]), ZERO) * sign
        if listed != net:
            where = open_table.file if open_table else "the open invoices file"
            tb.problem(0, "account", f"{code} {account.name}: the trial balance shows "
                                     f"{net:.2f} (debit positive) but the open invoices in "
                                     f"{where} add up to {listed:.2f}. List the invoices behind "
                                     "this balance.")  # fmt: skip
            continue
        for item in by_account[code]:
            value = item.amount * sign
            due = item.due_date or (item.invoice_date and item.invoice_date + timedelta(
                days=item.counterparty.payment_terms_days))  # fmt: skip
            lines.append(PlannedLine(
                code, account.name, max(value, ZERO), max(-value, ZERO),
                item.counterparty.code, item.invoice, due or None,
            ))  # fmt: skip
    return lines


def import_opening_balances(  # noqa: PLR0913 - keyword-only options
    ctx: WorkspaceContext,
    entity_id: UUID,
    trial_balance: Upload,
    *,
    as_of: date,
    open_items: Upload | None = None,
    account_map: dict[str, str] | None = None,
    commit: bool = False,
) -> Outcome:
    """One draft entry dated ``as_of``: a line per account of the trial balance, and for each
    receivables or payables account a line per open invoice instead (they must add up to the
    account's balance). The entry must balance; it is then approved and posted as usual."""
    out = Outcome("opening-balances")
    entity = get_entity(ctx, entity_id, "ledger.entry.create")
    mapping = {k.strip(): v.strip() for k, v in (account_map or {}).items() if v.strip()}
    chart = {a.code: a for a in account_list(ctx, entity.id)}
    tb = _read(trial_balance, "opening-balances",
               lambda f: "account" in f and ("balance" in f or {"debit", "credit"} <= f),
               "No header row with an account column and Debit and Credit (or Balance) columns "
               "was found in the first 10 rows.", out)  # fmt: skip
    items_table = None
    if open_items is not None:
        items_table = _read(open_items, "open-items",
                            lambda f: {"account", "counterparty", "invoice", "amount"} <= f,
                            "No header row with Account code, Customer or supplier code, Invoice "
                            "number and Amount outstanding columns was found in the first 10 "
                            "rows.", out)  # fmt: skip
    if not any(fy.start_date <= as_of <= fy.end_date for fy in fiscal_year_list(ctx, entity.id)):
        out.problems.append(Problem(0, "", f"No fiscal year contains {as_of:%d/%m/%Y}: create it "
                                           "first (Settings, fiscal years)."))  # fmt: skip
    earlier = JournalEntry.objects.filter(
        legal_entity_id=entity.id, source=JournalEntry.Source.IMPORT,
        description__startswith=OPENING,
    ).exclude(status=JournalEntry.Status.VOID).first()  # fmt: skip
    if earlier is not None:
        out.problems.append(Problem(0, "", f"Opening balances were already imported "
                                           f"({earlier.description}); void that entry first to "
                                           "import them again."))  # fmt: skip
    if tb is None:
        return _run(ctx, entity.id, out, commit, lambda: None)
    totals = _balances(tb, chart, mapping, out)
    items: list[_Item] = []
    if items_table is not None:
        parties = {c.code: c for c in counterparty_list(ctx, entity.id)}
        items = _items(items_table, chart, mapping, parties)
        _already_booked(entity.id, items, items_table)
        out.problems.extend(items_table.problems)
    out.lines = _plan_lines(totals, items, chart, tb, items_table)
    out.problems.extend(tb.problems)
    out.total_debit = sum((ln.debit for ln in out.lines), ZERO)
    out.total_credit = sum((ln.credit for ln in out.lines), ZERO)
    if out.difference:
        out.problems.append(
            Problem(
                0,
                "",
                f"The trial balance does not balance: debits "
                f"{out.total_debit:.2f}, credits "
                f"{out.total_credit:.2f}, difference "
                f"{abs(out.difference):.2f}.",
                trial_balance.name,
            )
        )
    if not out.lines and not out.problems:
        out.problems.append(Problem(0, "", "There are no balances to import.", trial_balance.name))
    if any(chart[ln.account_code].type in ("INCOME", "EXPENSE") for ln in out.lines):
        out.warnings.append("Income and expense accounts have balances. At the start of a year "
                            "they are normally zero, with the result in retained earnings; keep "
                            "them only if you start part way through the year.")  # fmt: skip

    def create() -> None:
        parties = {c.code: c.id for c in counterparty_list(ctx, entity.id)}
        settle = f"{entity.jurisdiction}:SETTLE:open"
        lines = [LineInput(
            account_id=chart[ln.account_code].id, debit=str(ln.debit), credit=str(ln.credit),
            memo=(f"Invoice {ln.reference}" if ln.reference else "Opening balance"),
            counterparty_id=parties.get(ln.counterparty_code), reference=ln.reference,
            due_date=ln.due_date,
            # A VAT account's opening balance is not a transaction of any VAT return.
            vat_code_id=settle if chart[ln.account_code].vat_role else None,
        ) for ln in out.lines]  # fmt: skip
        entry = create_entry_draft(ctx, entity.id, EntryInput(
            accounting_date=as_of, description=f"{OPENING} {as_of:%d/%m/%Y} (imported)",
            lines=lines,
        ))  # fmt: skip
        out.entry_id = entry.id

    return _run(ctx, entity.id, out, commit, create)
