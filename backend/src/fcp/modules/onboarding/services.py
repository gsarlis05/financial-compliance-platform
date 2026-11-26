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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from django.db import transaction

from fcp.core.errors import DomainError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.ledger.api import (
    Account,
    AccountInput,
    account_list,
    add_account,
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


@dataclass(frozen=True)
class UnknownCounterparty:
    name: str
    side: str  # RECEIVABLE or PAYABLE
    rows: tuple[int, ...]


@dataclass
class Outcome:
    kind: str
    committed: bool = False
    rows: int = 0
    problems: list[Problem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unknown_accounts: list[UnknownAccount] = field(default_factory=list)
    unknown_counterparties: list[UnknownCounterparty] = field(default_factory=list)
    accounts: list[str] = field(default_factory=list)  # codes created (or to be created)
    counterparties: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # already there, identical
    lines: list[PlannedLine] = field(default_factory=list)
    total_debit: Decimal = ZERO
    total_credit: Decimal = ZERO
    entry_id: UUID | None = None
    files: dict[str, str] = field(default_factory=dict)  # name -> SHA-256
    months: list[str] = field(default_factory=list)  # prior year (R-4): the months imported

    @property
    def difference(self) -> Decimal:
        return self.total_debit - self.total_credit


def read_upload(upload: Upload, kind: str, ready: Callable[[set[str]], bool], missing: str,
                out: Outcome, dynamic: tables.Dynamic | None = None) -> Table | None:  # fmt: skip
    out.files[upload.name] = upload.sha256
    try:
        table = tables.read(upload.data, upload.name, templates.fields(kind), ready, missing,
                            dynamic)  # fmt: skip
    except TableError as refused:
        out.problems.append(Problem(0, "", str(refused), upload.name))
        return None
    out.problems.extend(table.problems)
    out.rows += len(table.rows)
    return table


def cell(table: Table, number: int, key: str, found: Any) -> Any:
    """``found`` as read, or None after recording its problem against the row and column."""
    if isinstance(found, Problem):
        table.problem(number, key, found.message)
        return None
    return found


def run(ctx: WorkspaceContext, entity_id: UUID, out: Outcome, commit: bool,
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
    code = cell(table, number, "code", tables.text(cells.get("code"), 20))
    name = cell(table, number, "name", tables.text(cells.get("name"), 200))
    raw_type = cell(table, number, "type", tables.text(cells.get("type"), 30))
    parent = cell(table, number, "parent_code", tables.text(cells.get("parent_code"), 20))
    postable = cell(
        table,
        number,
        "postable",
        tables.flag(cells.get("postable"), True, templates.YES, templates.NO),
    )
    control = cell(table, number, "control", tables.text(cells.get("control"), 20))
    vat_role = cell(table, number, "vat_role", tables.text(cells.get("vat_role"), 20))
    name_el = cell(table, number, "name_el", tables.text(cells.get("name_el"), 200))  # fmt: skip
    if code == "":
        table.problem(number, "code", "Enter the account code.")
    if name == "":
        table.problem(number, "name", "Enter the account name.")
    account_type, _, implied = (templates.ACCOUNT_TYPES.get(tables.normalise(raw_type or ""))
                                or "").partition(":")  # fmt: skip
    if raw_type is not None and not account_type:
        table.problem(number, "type", "Enter Asset, Liability, Equity, Income or Expense.")
        account_type = None
    control_type = implied if control == "" else CONTROLS.get(tables.normalise(control or ""))
    if control and control_type is None:
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
    table = read_upload(upload, "chart", lambda f: {"code", "name", "type"} <= f,
                  "No header row with Code, Name and Type columns was found in the first 10 "
                  "rows.", out)  # fmt: skip
    if table is None:
        return run(ctx, entity.id, out, commit, lambda: None)
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

    return run(ctx, entity.id, out, commit, create)


# --- 2. customers and suppliers -----------------------------------------------------------------


def _counterparty_row(
    table: Table, number: int, cells: dict[str, object]
) -> tuple[int, CounterpartyInput] | None:
    got = {k: cell(table, number, k, tables.text(cells.get(k), n)) for k, n in
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
    table = read_upload(upload, "counterparties", lambda f: {"code", "name", "kind"} <= f,
                  "No header row with Code, Name and Kind columns was found in the first 10 "
                  "rows.", out)  # fmt: skip
    if table is None:
        return run(ctx, entity.id, out, commit, lambda: None)
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

    return run(ctx, entity.id, out, commit, create)
