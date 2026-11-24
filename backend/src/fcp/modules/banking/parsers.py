"""Bank statement parsers: ISO 20022 CAMT.053 (XML) and CSV with a per-bank column mapping (M2-5).

Bank files come from outside, so they are treated as hostile input (threat model: file parsing):
- XML is parsed with ``defusedxml``: DTDs, entity declarations and external references are
  refused, which stops XXE and "billion laughs" expansion before any expansion happens;
- size and row limits are enforced before and during parsing;
- amounts must be plain decimals with at most two places (no floats, no exponents);
- text is stripped of control characters and truncated.

Every problem raises ``StatementFormatError`` with an actionable message; nothing else escapes
(fuzz-tested). Parsers have no side effects and no database access.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring

from fcp.core.errors import ValidationFailedError

MAX_BYTES = 5 * 1024 * 1024
MAX_LINES = 20_000
MAX_TEXT = 500
_AMOUNT = re.compile(r"^\d{1,15}(\.\d{1,2})?$")
_SIGNED_AMOUNT = re.compile(r"^[+-]?\d{1,15}(\.\d{1,2})?$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_CAMT053 = "urn:iso:std:iso:20022:tech:xsd:camt.053."


class StatementFormatError(ValidationFailedError):
    code = "banking.statement.invalid"
    title = "The bank statement could not be read"


@dataclass(frozen=True)
class ParsedLine:
    booking_date: date
    amount: Decimal  # positive: money in; negative: money out
    description: str = ""
    counterparty_name: str = ""
    reference: str = ""
    bank_ref: str = ""
    value_date: date | None = None


@dataclass(frozen=True)
class ParsedStatement:
    statement_id: str
    currency: str
    lines: list[ParsedLine]
    iban: str = ""
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    closing_date: date | None = None


def _text(value: str | None) -> str:
    return _CONTROL.sub(" ", value or "").strip()[:MAX_TEXT]


def _check_size(data: bytes) -> None:
    if not data:
        raise StatementFormatError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise StatementFormatError(f"The file is larger than {MAX_BYTES // (1024 * 1024)} MB.")


# --- CAMT.053 -------------------------------------------------------------------------------------


class _Xml:
    def __init__(self, namespace: str) -> None:
        self.ns = namespace

    def path(self, path: str) -> str:
        return "/".join(f"{{{self.ns}}}{part}" for part in path.split("/"))

    def find(self, element: Element, path: str) -> Element | None:
        return element.find(self.path(path))

    def all(self, element: Element, path: str) -> list[Element]:
        return element.findall(self.path(path))

    def text(self, element: Element, *paths: str) -> str:
        for path in paths:
            found = self.find(element, path)
            if found is not None and found.text:
                return _text(found.text)
        return ""


def _amount(text: str, where: str) -> Decimal:
    if not _AMOUNT.match(text.strip()):
        raise StatementFormatError(
            f"{where}: '{text[:20]}' is not an amount with up to 2 decimals."
        )
    return Decimal(text.strip())


def _date(text: str, where: str) -> date:
    try:
        return date.fromisoformat(text.strip()[:10])
    except ValueError:
        raise StatementFormatError(f"{where}: '{text[:20]}' is not a date (YYYY-MM-DD).") from None


def _signed(xml: _Xml, element: Element, where: str) -> tuple[Decimal, str]:
    amount_el = xml.find(element, "Amt")
    indicator = xml.text(element, "CdtDbtInd")
    if amount_el is None or amount_el.text is None or indicator not in ("CRDT", "DBIT"):
        raise StatementFormatError(f"{where}: amount or credit/debit indicator missing.")
    amount = _amount(amount_el.text, where)
    return (amount if indicator == "CRDT" else -amount), _text(amount_el.get("Ccy"))


def _balances(xml: _Xml, statement: Element) -> tuple[Decimal | None, Decimal | None, date | None]:
    opening = closing = None
    closing_date = None
    for balance in xml.all(statement, "Bal"):
        code = xml.text(balance, "Tp/CdOrPrtry/Cd")
        amount, _ = _signed(xml, balance, f"Balance {code or '?'}")
        if code in ("OPBD", "PRCD") and opening is None:
            opening = amount
        elif code == "CLBD":
            closing = amount
            day = xml.text(balance, "Dt/Dt", "Dt/DtTm")
            closing_date = _date(day, "Closing balance date") if day else None
    return opening, closing, closing_date


def _entry(xml: _Xml, entry: Element, number: int) -> ParsedLine | None:
    where = f"Entry {number}"
    status = xml.text(entry, "Sts", "Sts/Cd")
    if status and status != "BOOK":
        return None  # pending or information-only entries are not booked yet
    amount, _ = _signed(xml, entry, where)
    booked = xml.text(entry, "BookgDt/Dt", "BookgDt/DtTm")
    if not booked:
        raise StatementFormatError(f"{where}: booking date missing.")
    valued = xml.text(entry, "ValDt/Dt", "ValDt/DtTm")
    details = xml.find(entry, "NtryDtls/TxDtls")
    description = reference = party = ""
    if details is not None:
        description = " ".join(
            _text(u.text) for u in xml.all(details, "RmtInf/Ustrd") if u.text
        ).strip()[:MAX_TEXT]
        reference = xml.text(details, "RmtInf/Strd/CdtrRefInf/Ref", "Refs/EndToEndId")
        if reference == "NOTPROVIDED":
            reference = ""
        role = "Dbtr" if amount > 0 else "Cdtr"
        party = xml.text(details, f"RltdPties/{role}/Nm", f"RltdPties/{role}/Pty/Nm")
    return ParsedLine(
        booking_date=_date(booked, where),
        value_date=_date(valued, where) if valued else None,
        amount=amount,
        description=description or xml.text(entry, "AddtlNtryInf"),
        counterparty_name=party,
        reference=reference,
        bank_ref=xml.text(entry, "AcctSvcrRef"),
    )


def parse_camt053(data: bytes) -> ParsedStatement:
    """One CAMT.053 statement (versions .001.02 to .001.08 share the fields used here)."""
    _check_size(data)
    try:
        root = fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise StatementFormatError(
            "The file declares a DTD, entities or external references, which bank statements "
            "never need. It was refused for safety."
        ) from None
    except (ParseError, ValueError, LookupError):  # LookupError: unknown declared encoding
        raise StatementFormatError("The file is not well-formed XML.") from None
    namespace = root.tag[1:].split("}", 1)[0] if root.tag.startswith("{") else ""
    if not namespace.startswith(_CAMT053) or not root.tag.endswith("}Document"):
        raise StatementFormatError("The file is XML but not an ISO 20022 CAMT.053 statement.")
    xml = _Xml(namespace)
    statements = xml.all(root, "BkToCstmrStmt/Stmt")
    if len(statements) != 1:
        raise StatementFormatError(
            f"The file contains {len(statements)} statements; import one statement per file."
        )
    statement = statements[0]
    entries = xml.all(statement, "Ntry")
    if len(entries) > MAX_LINES:
        raise StatementFormatError(f"The statement has more than {MAX_LINES} entries.")
    opening, closing, closing_date = _balances(xml, statement)
    lines = [line for n, e in enumerate(entries, start=1) if (line := _entry(xml, e, n))]
    currencies = {_text(a.get("Ccy")) for a in statement.iter(xml.path("Amt"))}
    if len(currencies) != 1:
        raise StatementFormatError("Every amount in the statement must have the same currency.")
    return ParsedStatement(
        statement_id=xml.text(statement, "Id") or "?",
        iban=xml.text(statement, "Acct/Id/IBAN").replace(" ", "").upper(),
        currency=currencies.pop(),
        opening_balance=opening,
        closing_balance=closing,
        closing_date=closing_date,
        lines=lines,
    )


# --- CSV ------------------------------------------------------------------------------------------

DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%m/%d/%Y")
ENCODINGS = ("utf-8-sig", "utf-8", "cp1253", "latin-1")


@dataclass(frozen=True)
class CsvMapping:
    """How a bank's CSV export is laid out. Columns are header names (or 1-based numbers when the
    file has no header). Either ``amount`` (signed) or ``debit`` and ``credit`` columns.

    With ``strict`` (saved bank mappings), every mapped column must exist, so a typo cannot silently
    drop data; the default mapping skips optional columns a file does not have."""

    date: str = "date"
    amount: str = "amount"
    debit: str = ""
    credit: str = ""
    description: str = "description"
    reference: str = "reference"
    counterparty: str = ""
    balance: str = ""
    date_format: str = "%Y-%m-%d"
    delimiter: Literal[",", ";", "\t", "|"] = ","
    decimal_comma: bool = False
    has_header: bool = True
    encoding: str = "utf-8-sig"
    strict: bool = True

    def validate(self) -> None:
        if self.date_format not in DATE_FORMATS:
            raise StatementFormatError(f"Date format must be one of {', '.join(DATE_FORMATS)}.")
        if self.encoding not in ENCODINGS:
            raise StatementFormatError(f"Encoding must be one of {', '.join(ENCODINGS)}.")
        if not self.date or not (self.amount or (self.debit and self.credit)):
            raise StatementFormatError(
                "Map the date column and either an amount column or debit and credit columns."
            )
        if self.amount and (self.debit or self.credit):
            raise StatementFormatError("Map either an amount column or debit and credit, not both.")


# Matches the synthetic bank export (date, description, amount, balance, ..., reference).
DEFAULT_CSV_MAPPING = CsvMapping(balance="balance", strict=False)
OPTIONAL_COLUMNS = ("description", "reference", "counterparty", "balance")


def _csv_amount(raw: str, mapping: CsvMapping, where: str) -> Decimal:
    text = raw.strip().replace(" ", "").replace("\u00a0", "")
    if mapping.decimal_comma:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", "")
    if not _SIGNED_AMOUNT.match(text):
        raise StatementFormatError(f"{where}: '{raw[:20]}' is not an amount with up to 2 decimals.")
    return Decimal(text)


def _rows(data: bytes, mapping: CsvMapping) -> list[list[str]]:
    _check_size(data)
    mapping.validate()
    try:
        text = data.decode(mapping.encoding)
    except UnicodeDecodeError:
        raise StatementFormatError(f"The file is not encoded as {mapping.encoding}.") from None
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=mapping.delimiter))
    except csv.Error as exc:
        raise StatementFormatError(f"The CSV could not be read: {str(exc)[:100]}.") from None
    rows = [r for r in rows if any(cell.strip() for cell in r)]
    if not rows:
        raise StatementFormatError("The file has no rows.")
    if len(rows) > MAX_LINES + 1:
        raise StatementFormatError(f"The file has more than {MAX_LINES} rows.")
    return rows


_COLUMNS = ("date", "amount", "debit", "credit", "description", "reference", "counterparty",
            "balance")  # fmt: skip


def _columns(mapping: CsvMapping, header: list[str] | None) -> dict[str, int | None]:
    """Column positions by field, from header names or 1-based numbers."""
    result: dict[str, int | None] = {}
    for name in _COLUMNS:
        column = getattr(mapping, name).strip()
        if not column:
            result[name] = None
        elif header is not None:
            if column.lower() in header:
                result[name] = header.index(column.lower())
            elif not mapping.strict and name in OPTIONAL_COLUMNS:
                result[name] = None
            else:
                raise StatementFormatError(f"Column '{column}' is not in the file's header.")
        elif column.isdigit() and int(column) >= 1:
            result[name] = int(column) - 1
        else:
            raise StatementFormatError("Without a header, columns are numbers from 1.")
    return result


def _csv_line(
    row: list[str], cols: dict[str, int | None], mapping: CsvMapping, where: str
) -> tuple[ParsedLine, Decimal | None]:
    def cell(name: str) -> str:
        i = cols[name]
        if i is None:
            return ""
        if i >= len(row):
            raise StatementFormatError(f"{where}: missing column '{getattr(mapping, name)}'.")
        return row[i]

    try:
        # A calendar date without a time of day, so no time zone applies.
        booked = datetime.strptime(cell("date").strip(), mapping.date_format).date()  # noqa: DTZ007
    except ValueError:
        raise StatementFormatError(
            f"{where}: '{cell('date')[:20]}' does not match the date format {mapping.date_format}."
        ) from None
    if cols["amount"] is not None:
        amount = _csv_amount(cell("amount"), mapping, where)
    else:
        debit, credit = cell("debit").strip(), cell("credit").strip()
        amount = (_csv_amount(credit, mapping, where) if credit else Decimal(0)) - (
            _csv_amount(debit, mapping, where) if debit else Decimal(0)
        )
    balance = _csv_amount(cell("balance"), mapping, where) if cols["balance"] is not None else None
    line = ParsedLine(
        booking_date=booked,
        amount=amount,
        description=_text(cell("description")),
        reference=_text(cell("reference")),
        counterparty_name=_text(cell("counterparty")),
    )
    return line, balance


def parse_csv(data: bytes, mapping: CsvMapping = DEFAULT_CSV_MAPPING) -> ParsedStatement:
    """A CSV export. With a balance column, the opening balance is the first row's balance before
    its amount and the closing balance is the last row's (rows in date order)."""
    rows = _rows(data, mapping)
    header = None
    if mapping.has_header:
        header, rows = [h.strip().lower() for h in rows[0]], rows[1:]
    cols = _columns(mapping, header)
    first = 2 if mapping.has_header else 1
    parsed = [_csv_line(row, cols, mapping, f"Row {n}") for n, row in enumerate(rows, start=first)]
    lines = [line for line, _ in parsed]
    balances = [b for _, b in parsed if b is not None]
    opening = closing = None
    closing_date = None
    if balances and lines:
        opening, closing = balances[0] - lines[0].amount, balances[-1]
        closing_date = max(ln.booking_date for ln in lines)
    return ParsedStatement(
        statement_id="CSV",
        currency="",  # CSV exports carry no currency: the bank account's applies
        opening_balance=opening,
        closing_balance=closing,
        closing_date=closing_date,
        lines=lines,
    )
