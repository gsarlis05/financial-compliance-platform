"""Reading an import file (R-2, #245): a CSV or an .xlsx workbook, as data only.

Nothing in a file is evaluated:
- at most 5 MB; an .xlsx must be a zip archive of at most 200 parts and 50 MB unpacked, with no
  macros; XML is parsed through defusedxml (openpyxl uses it when installed);
- formulas are refused, and so is text starting with ``=``, ``+``, ``-``, ``@``, tab or CR;
- at most 5,000 data rows and 40 columns are read, from the first sheet only.

Columns are recognised by their header names (English or Greek; case, accents and punctuation
ignored), so the columns may be in any order and extra columns are ignored. Every problem is
reported with its row and column; the caller creates nothing while any remains.
"""

import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

MAX_BYTES = 5 * 1024 * 1024
MAX_PARTS = 200
MAX_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ROWS = 5000
MAX_COLUMNS = 40
HEADER_SEARCH_ROWS = 10
DANGEROUS = ("=", "+", "-", "@", "\t", "\r")
CENT = Decimal("0.01")
DELIMITERS = (",", ";", "\t")


class TableError(ValueError):
    """The file as a whole cannot be read; the message is shown to the user."""


class Formula:
    """A cell holding a formula: refused, never evaluated."""


FORMULA = Formula()


@dataclass(frozen=True)
class Problem:
    row: int  # as a spreadsheet shows it (1-based); 0: the file as a whole
    column: str
    message: str
    file: str = ""


@dataclass
class Table:
    """The data rows of a file, by field (the caller's names for the recognised columns)."""

    file: str
    header_row: int
    columns: dict[str, str]  # field -> the file's own header
    rows: list[tuple[int, dict[str, object]]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)

    def problem(self, row: int, key: str, message: str) -> None:
        self.problems.append(Problem(row, self.columns.get(key, key), message, self.file))


def normalise(text: str) -> str:
    """Lower case, no accents (Greek tonos too), punctuation as spaces, single spaces."""
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w]+", " ", plain).split())


# --- reading the file --------------------------------------------------------------------------


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    greek = data.decode("cp1253", errors="replace")
    if sum(1 for c in greek if "Ͱ" <= c <= "Ͽ") >= 3:  # Greek letters: Windows Greek
        return greek
    return data.decode("latin-1")


def _check_archive(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = archive.infolist()
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise TableError("This is not an .xlsx workbook or a CSV file.") from exc
    if len(parts) > MAX_PARTS or sum(p.file_size for p in parts) > MAX_UNCOMPRESSED:
        raise TableError("The workbook is too large once unpacked.")
    names = {p.filename.lower() for p in parts}
    if any(n.endswith("vbaproject.bin") for n in names):
        raise TableError("Workbooks with macros are not accepted.")
    if "xl/workbook.xml" not in names:
        raise TableError("This is not an .xlsx workbook.")


def _xlsx_rows(data: bytes) -> list[list[object]]:
    _check_archive(data)
    from openpyxl import load_workbook  # noqa: PLC0415 (only imports need openpyxl)

    try:
        book = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False)
    except Exception as exc:
        raise TableError("The workbook could not be read.") from exc
    try:
        rows: list[list[object]] = []
        for cells in book.worksheets[0].iter_rows(max_col=MAX_COLUMNS):
            rows.append([FORMULA if c.data_type == "f" else c.value for c in cells])
            if len(rows) > MAX_ROWS + HEADER_SEARCH_ROWS:
                break
        return rows
    finally:
        book.close()


def _csv_rows(text: str, delimiter: str) -> list[list[object]]:
    rows: list[list[object]] = []
    for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
        rows.append(list(row[:MAX_COLUMNS]))
        if len(rows) > MAX_ROWS + HEADER_SEARCH_ROWS:
            break
    return rows


Dynamic = Callable[[object], str | None]


def _header(
    rows: list[list[object]], fields: dict[str, tuple[str, ...]],
    ready: Callable[[set[str]], bool], dynamic: Dynamic | None,
) -> tuple[int, dict[str, int]] | None:  # fmt: skip
    names = {name: key for key, synonyms in fields.items() for name in synonyms}
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        found: dict[str, int] = {}
        for i, cell in enumerate(row):
            key = names.get(normalise(str(cell))) if isinstance(cell, str) else None
            if key is None and dynamic is not None and cell is not None:
                key = dynamic(cell)
            if key and key not in found:
                found[key] = i
        if ready(set(found)):
            return index, found
    return None


def _label(cell: object) -> str:
    if isinstance(cell, datetime):
        return f"{cell:%Y-%m}"
    return str(cell).strip()


def read(
    data: bytes,
    file: str,
    fields: dict[str, tuple[str, ...]],
    ready: Callable[[set[str]], bool],
    missing: str,
    dynamic: Dynamic | None = None,
) -> Table:
    """The rows of ``data`` by field. ``fields`` maps each field to its normalised header names;
    ``dynamic`` names other header cells (such as months); the header is the first row (of the
    first 10) for which ``ready`` holds."""
    if not data:
        raise TableError(f"{file}: the file is empty.")
    if len(data) > MAX_BYTES:
        raise TableError(f"{file}: the file is larger than 5 MB.")
    if data.startswith(b"PK\x03\x04"):
        candidates = [_xlsx_rows(data)]
    else:
        text = _decode(data)
        candidates = [_csv_rows(text, d) for d in DELIMITERS]
    for rows in candidates:
        header = _header(rows, fields, ready, dynamic)
        if header is None:
            continue
        index, found = header
        head = rows[index]
        table = Table(file, index + 1, {k: _label(head[i]) for k, i in found.items()})
        for number, row in enumerate(rows[index + 1 :], start=index + 2):
            if all(c is None or (isinstance(c, str) and not c.strip()) for c in row):
                continue
            if len(table.rows) >= MAX_ROWS:
                table.problems.append(Problem(number, "", f"At most {MAX_ROWS} rows are read.",
                                              file))  # fmt: skip
                break
            table.rows.append(
                (number, {k: row[i] if i < len(row) else None for k, i in found.items()})
            )
        return table
    raise TableError(f"{file}: {missing}")


# --- reading one cell ----------------------------------------------------------------------------


def text(value: object, max_length: int) -> str | Problem:
    """The cell as text (blank: ""), or the problem with it."""
    if value is FORMULA:
        return Problem(0, "", "Formulas are not accepted; enter the value.")
    if value is None:
        return ""
    if isinstance(value, float):  # fcp-lint: allow-float (a code typed as a number in Excel)
        value = format(Decimal(repr(value)).normalize(), "f")
    found = str(value).strip()
    if found.startswith(DANGEROUS):
        return Problem(0, "", "Text cannot start with =, +, -, @, a tab or a line break.")
    if len(found) > max_length:
        return Problem(0, "", f"At most {max_length} characters.")
    return found


_PLAIN = re.compile(r"^\d+(\.\d+)?$")


def _number_text(raw: str) -> str | None:
    """A typed amount as plain digits with a decimal point, or None if its separators are
    ambiguous (1.250 or 1,250: thousands or decimals?)."""
    cleaned = raw.replace("\u00a0", "").replace(" ", "").replace("'", "")
    last_dot, last_comma = cleaned.rfind("."), cleaned.rfind(",")
    if last_dot >= 0 and last_comma >= 0:
        decimal_sep = "." if last_dot > last_comma else ","
        thousands = "," if decimal_sep == "." else "."
        cleaned = cleaned.replace(thousands, "").replace(decimal_sep, ".")
    elif last_comma >= 0 or last_dot >= 0:
        sep = "," if last_comma >= 0 else "."
        parts = cleaned.split(sep)
        if len(parts) > 2:  # 1,250,000 or 1.250.000: thousands only
            cleaned = "".join(parts)
        elif len(parts[1]) == 3:  # 1,250 or 1.250: thousands or decimals?
            return None
        else:
            cleaned = f"{parts[0]}.{parts[1]}"
    return cleaned if _PLAIN.match(cleaned) else None


_DR_CR = re.compile(r"^(dr|cr)\.?\s*|\s*(dr|cr)\.?$", re.IGNORECASE)


def amount(value: object) -> Decimal | Problem:  # noqa: PLR0911 (one return per kind of cell)
    """The cell as an amount (blank: zero), or the problem with it. Negative amounts are written
    with a leading minus or in brackets; an accountant's "1,250.00 Cr" (or "Cr 1,250.00") is a
    credit, so negative, and "Dr" a debit."""
    if value is FORMULA:
        return Problem(0, "", "Formulas are not accepted; enter the value.")
    if value is None or (isinstance(value, str) and not value.strip()):
        return Decimal(0)
    if isinstance(value, bool):
        return Problem(0, "", "Enter an amount, not TRUE or FALSE.")
    if isinstance(value, (int, Decimal)):
        number = Decimal(value)
    elif isinstance(value, float):  # fcp-lint: allow-float (Excel stores numbers as floats)
        number = Decimal(repr(value))
    elif isinstance(value, str):
        raw = value.strip().replace("€", "").replace("EUR", "").strip()
        side = _DR_CR.search(raw)
        credit = bool(side and (side.group(1) or side.group(2)).lower() == "cr")
        if side:
            raw = _DR_CR.sub("", raw).strip()
        negative = credit != (raw.startswith("-") or (raw.startswith("(") and raw.endswith(")")))
        digits = _number_text(raw.strip("-()").strip())
        if digits is None:
            return Problem(0, "", f"{value.strip()[:20]!r} is not an amount this import can read "
                                  "unambiguously; write it as 1250.00 or 1.250,00.")  # fmt: skip
        number = -Decimal(digits) if negative else Decimal(digits)
    else:
        return Problem(0, "", "Enter an amount.")
    try:
        if not number.is_finite() or number != number.quantize(CENT) or abs(number) >= 10**15:
            return Problem(0, "", "Enter an amount with at most 2 decimals and fewer than 16 "
                                  "digits.")  # fmt: skip
    except InvalidOperation:
        return Problem(0, "", "Enter an amount with at most 2 decimals and fewer than 16 digits.")
    return number.quantize(CENT)


# Year first, or with the month in words: the same whatever the order of day and month.
FIXED_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y",
                 "%d-%b-%Y", "%d-%b-%y")  # fmt: skip
DAY_FIRST = ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%d/%m/%y")
MONTH_FIRST = ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y")


def _parsed(text: str, formats: tuple[str, ...]) -> date | None:
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()  # noqa: DTZ007 - a calendar date
        except ValueError:
            continue
    return None


def day(value: object, *, day_first: bool = True) -> date | Problem | None:  # noqa: PLR0911
    """The cell as a date (blank: None). Typed dates are read day first (Cyprus) unless
    ``day_first`` is false: 03/04/2026 is then 4 March 2026. Year first (2026-04-03) and dates
    with the month in words (15 Dec 2025) read the same either way. A time after the date is
    ignored."""
    if value is FORMULA:
        return Problem(0, "", "Formulas are not accepted; enter the value.")
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = " ".join(value.split())
        text = re.sub(r"[ T]\d{1,2}:\d{2}(:\d{2})?$", "", text)
        found = _parsed(text, FIXED_FORMATS + (DAY_FIRST if day_first else MONTH_FIRST))
        if found is not None:
            return found
        if _parsed(text, MONTH_FIRST if day_first else DAY_FIRST) is not None:
            order = "month first (12/31/2026)" if day_first else "day first (31/12/2026)"
            return Problem(0, "", f"{text[:20]!r} reads only {order}: choose that date order for "
                                  "this file.")  # fmt: skip
    return Problem(0, "", "Enter a date as 31/12/2026 or 2026-12-31.")


def flag(value: object, default: bool, yes: frozenset[str], no: frozenset[str]) -> bool | Problem:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, bool):
        return value
    word = normalise(str(value))
    if word in yes:
        return True
    if word in no:
        return False
    return Problem(0, "", "Enter Yes or No.")


def names(*headers: str) -> tuple[str, ...]:
    return tuple(normalise(h) for h in headers)


def merged(problems: Iterable[Problem]) -> list[Problem]:
    """Problems in file and row order."""
    return sorted(problems, key=lambda p: (p.file, p.row, p.column))
