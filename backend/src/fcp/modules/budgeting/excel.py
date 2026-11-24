"""Budget Excel export and hardened import (M4-2, AC-BU3, threat T9).

The workbook is our own template: one sheet, a header row ``Line | Account | Dimension | Note |
2026-01 … | Total``, one row per budget line. The export doubles as the import template.

Import never evaluates anything:
- the upload is at most 5 MB, must be an .xlsx (zip) archive with at most 200 parts and 50 MB
  uncompressed, and may not contain macros;
- XML is parsed through defusedxml (openpyxl uses it when installed);
- formulas are rejected, and so is text starting with ``=``, ``+``, ``-``, ``@``, tab or CR;
- at most 5,000 data rows and 40 columns are read;
- every problem is reported with its row and column, and nothing is saved while any remains.
"""

import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fcp.core.export import safe_text

MAX_BYTES = 5 * 1024 * 1024
MAX_PARTS = 200
MAX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 40
HEADER_SEARCH_ROWS = 10
TEXT_COLUMNS = ("Line", "Account", "Dimension", "Note")
DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
AMOUNT = re.compile(r"^\d{1,15}(\.\d{1,2})?$")
MONTH = re.compile(r"^(\d{4})-(\d{2})$")
CENT = Decimal("0.01")


class WorkbookError(ValueError):
    """The file as a whole cannot be read; the message is shown to the user."""


@dataclass(frozen=True)
class Problem:
    row: int  # 1-based, as Excel shows it (0: the file or header)
    column: str
    message: str


@dataclass
class Row:
    row: int
    line: str = ""
    account: str = ""
    dimension: str = ""
    note: str = ""
    amounts: dict[date, Decimal] = field(default_factory=dict)


@dataclass(frozen=True)
class ExportLine:
    line: str
    account: str
    dimension: str
    note: str
    amounts: list[Decimal]


def month_key(month: date) -> str:
    return f"{month.year:04d}-{month.month:02d}"


def export(title: str, subtitle: str, months: list[date], lines: list[ExportLine]) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 (only budget files need openpyxl)
    from openpyxl.styles import Font  # noqa: PLC0415

    book = Workbook()
    sheet = book.active
    if sheet is None:  # pragma: no cover (a new workbook always has one sheet)
        raise WorkbookError("No sheet.")
    sheet.title = "Budget"
    sheet.append([safe_text(title)])
    sheet.append([safe_text(subtitle)])
    sheet.append([])
    sheet.append([*TEXT_COLUMNS, *(month_key(m) for m in months), "Total"])
    sheet["A1"].font = Font(bold=True, size=13)
    for cell in sheet[4]:
        cell.font = Font(bold=True)
    for ln in lines:
        sheet.append(
            [
                safe_text(ln.line),
                safe_text(ln.account),
                safe_text(ln.dimension),
                safe_text(ln.note),
                *ln.amounts,
                sum(ln.amounts, Decimal(0)),
            ]
        )
    for row in sheet.iter_rows(min_row=5, min_col=5):
        for cell in row:
            cell.number_format = "#,##0.00"
    sheet.freeze_panes = "E5"
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _check_archive(data: bytes) -> None:
    if not data:
        raise WorkbookError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise WorkbookError("The file is larger than 5 MB.")
    if not data.startswith(b"PK\x03\x04"):
        raise WorkbookError("This is not an .xlsx workbook.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise WorkbookError("This is not an .xlsx workbook.") from exc
    if len(parts) > MAX_PARTS or sum(p.file_size for p in parts) > MAX_UNCOMPRESSED:
        raise WorkbookError("The workbook is too large once unpacked.")
    names = {p.filename.lower() for p in parts}
    if any(n.endswith("vbaproject.bin") for n in names):
        raise WorkbookError("Workbooks with macros are not accepted.")
    if "xl/workbook.xml" not in names:
        raise WorkbookError("This is not an .xlsx workbook.")


def _header_month(value: object) -> date | None:
    if isinstance(value, datetime):
        return date(value.year, value.month, 1)
    if isinstance(value, str) and (m := MONTH.match(value.strip())):
        year, month = int(m.group(1)), int(m.group(2))
        if 1 <= month <= 12:
            return date(year, month, 1)
    return None


def _amount(value: object) -> Decimal | str:  # noqa: PLR0911 (one return per kind of cell)
    """The cell as a Decimal amount, or the problem with it."""
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        return "Enter a number, not TRUE or FALSE."
    if isinstance(value, (int, Decimal)):
        number = Decimal(value)
    elif isinstance(value, float):  # fcp-lint: allow-float (Excel stores numbers as floats)
        number = Decimal(repr(value))
    elif isinstance(value, str):
        text = value.strip()
        if text.startswith(DANGEROUS):
            return "Text cannot start with =, +, - or @. Enter negative amounts as numbers."
        if not AMOUNT.match(text):
            return "Enter a number with at most 2 decimals."
        number = Decimal(text)
    else:
        return "Enter a number."
    try:
        if not number.is_finite() or number != number.quantize(CENT) or abs(number) >= 10**15:
            return "Enter a number with at most 2 decimals and fewer than 16 digits."
    except InvalidOperation:
        return "Enter a number with at most 2 decimals and fewer than 16 digits."
    return number.quantize(CENT)


def _text(value: object) -> str | None:
    """The cell as text, or None if it is dangerous."""
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith(DANGEROUS):
        return None
    return text


def _header(rows: Iterator[tuple[Any, ...]]) -> tuple[int, list[str | date | None]]:
    for number, cells in enumerate(rows, start=1):
        first = cells[0].value if cells else None
        if isinstance(first, str) and first.strip() == "Line":
            header: list[str | date | None] = []
            for c in cells:
                month = _header_month(c.value)
                header.append(
                    month if month else (None if c.value is None else str(c.value).strip())
                )
            return number, header
        if number >= HEADER_SEARCH_ROWS:
            break
    raise WorkbookError("No header row starting with 'Line' in the first 10 rows.")


def _header_problems(
    number: int, header: list[str | date | None], allowed: set[date]
) -> list[Problem]:
    problems = []
    for i, h in enumerate(header):
        if isinstance(h, date) and h not in allowed:
            problems.append(
                Problem(number, _column(i), f"{month_key(h)} is not a month of this fiscal year.")
            )
        elif isinstance(h, str) and h not in (*TEXT_COLUMNS, "Total"):
            problems.append(Problem(number, _column(i), f"Unknown column {h[:30]!r}."))
    problems += [
        Problem(number, "", f"The column {name!r} is missing.")
        for name in ("Line", "Account")
        if name not in header
    ]
    return problems


def _cell(row: Row, kind: str | date, cell: Any, column: str, allowed: set[date]) -> str | None:
    """Store one cell in ``row``; return the problem with it, if any."""
    if cell.data_type == "f":
        return "Formulas are not accepted; enter the value."
    if isinstance(kind, date):
        value = _amount(cell.value)
        if isinstance(value, str):
            return value
        if kind in allowed:
            row.amounts[kind] = value
        return None
    text = _text(cell.value)
    if text is None:
        return "Text cannot start with =, +, - or @."
    if len(text) > (300 if kind == "Note" else 60):
        return "This text is too long."
    setattr(row, kind.lower(), text)
    return None


def parse(data: bytes, months: list[date]) -> tuple[list[Row], list[Problem]]:
    """Read the template. Raises ``WorkbookError`` if the file cannot be read at all."""
    _check_archive(data)
    from openpyxl import load_workbook  # noqa: PLC0415

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise WorkbookError("The workbook could not be read.") from exc
    try:
        rows = book.worksheets[0].iter_rows(max_col=MAX_COLUMNS)
        header_row, header = _header(rows)
        allowed = set(months)
        problems = _header_problems(header_row, header, allowed)
        out: list[Row] = []
        for number, cells in enumerate(rows, start=header_row + 1):
            if all(c.value in (None, "") for c in cells):
                continue
            if len(out) >= MAX_ROWS:
                problems.append(Problem(number, "", f"At most {MAX_ROWS} rows are read."))
                break
            row = Row(number)
            for i, cell in enumerate(cells):
                kind = header[i] if i < len(header) else None
                if kind is None or kind == "Total":
                    continue
                problem = _cell(row, kind, cell, _column(i), allowed)
                if problem:
                    problems.append(Problem(number, _column(i), problem))
            out.append(row)
        return out, problems
    finally:
        book.close()


def _column(index: int) -> str:
    name, index = "", index + 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name
