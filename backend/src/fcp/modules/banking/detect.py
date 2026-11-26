"""Recognise a bank's CSV statement export (R-1, #244; brief 26).

Given the bytes of a CSV export, work out how to read it, from the file itself:

- the encoding (UTF-8, Windows Greek, Latin-1);
- the delimiter;
- the header row, after any lines of account details some banks put first;
- which column is which, from the header names in English and Greek (case, accents and
  punctuation ignored);
- the decimal separator and the date format, from the values.

What the values leave open (a date such as 03/04/2026 when every date fits both day-first and
month-first) is returned as a question, never guessed silently. A bank preset only breaks such a
tie; it never decides a column. The presets are marked "to be confirmed": the developer has not
seen these banks' real export files.
"""

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path

from .parsers import (
    DATE_FORMATS,
    MAX_SKIP_ROWS,
    CsvMapping,
    ParsedLine,
    StatementFormatError,
    _check_size,
    parse_csv,
)

SAMPLE_ROWS = 200
PREVIEW_LINES = 5
DELIMITERS = (",", ";", "\t", "|")

# Header names per field, normalised (lower case, no accents or punctuation), English and Greek.
SYNONYMS: dict[str, tuple[str, ...]] = {
    key: tuple(names)
    for key, names in json.loads((Path(__file__).parent / "headers.json").read_text("utf-8"))[
        "fields"
    ].items()
}
FIELDS = ("date", "amount", "debit", "credit", "description", "reference", "counterparty",
          "balance")  # fmt: skip


@dataclass(frozen=True)
class Preset:
    """Defaults for a bank, used only to break a tie the file leaves open."""

    key: str
    name: str
    day_first: bool = True
    decimal_comma: bool | None = None  # None: decided by the values
    status: str = "TO_BE_CONFIRMED"
    note: str = "Not yet checked against a real export from this bank."


PRESETS = {
    p.key: p
    for p in (
        Preset("BANK_OF_CYPRUS", "Bank of Cyprus"),
        Preset("HELLENIC_BANK", "Hellenic Bank"),
        Preset("EUROBANK_CYPRUS", "Eurobank Cyprus"),
        Preset("REVOLUT_BUSINESS", "Revolut Business"),
    )
}


@dataclass(frozen=True)
class Question:
    field: str
    message: str
    options: tuple[str, ...]
    chosen: str


@dataclass
class Detection:
    mapping: CsvMapping
    columns: dict[str, str]  # field -> the file's own header name
    questions: list[Question] = field(default_factory=list)
    preview: list[ParsedLine] = field(default_factory=list)
    preset: Preset | None = None
    error: str = ""


def normalise(text: str) -> str:
    """Lower case, no accents (Greek tonos too), punctuation as spaces, single spaces."""
    decomposed = unicodedata.normalize("NFD", text.strip().lower())
    plain = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w]+", " ", plain).split())


def _decode(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    greek = data.decode("cp1253", errors="replace")
    if sum(1 for c in greek if "Ͱ" <= c <= "Ͽ") >= 3:  # Greek letters: Windows Greek
        return greek, "cp1253"
    return data.decode("latin-1"), "latin-1"


def _rows(text: str, delimiter: str) -> list[list[str]]:
    rows = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    found: list[list[str]] = []
    for row in rows:
        if any(cell.strip() for cell in row):
            found.append(row)
        if len(found) > SAMPLE_ROWS:
            break
    return found


def _field_of(header: str) -> str | None:
    name = normalise(header)
    for key, names in SYNONYMS.items():
        if name in names:
            return key
    return None


def _header(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """The first row (within the first lines) naming a date column and an amount, or debit and
    credit columns: its position among the non-empty rows and the field of each column."""
    for index, row in enumerate(rows[: MAX_SKIP_ROWS + 1]):
        found: dict[str, int] = {}
        for i, cell in enumerate(row):
            key = _field_of(cell)
            if key and key not in found:
                found[key] = i
        dated = "date" in found or "value_date" in found
        if dated and ("amount" in found or ("debit" in found and "credit" in found)):
            return index, found
    return None


def _delimiter(text: str) -> tuple[str, list[list[str]], tuple[int, dict[str, int]]]:
    for delimiter in DELIMITERS:
        rows = _rows(text, delimiter)
        header = _header(rows)
        if header is not None:
            return delimiter, rows, header
    raise StatementFormatError(
        "No header with a date and an amount (or debit and credit) column was found. Choose the "
        "columns yourself."
    )


_COMMA_DECIMAL = re.compile(r"^-?[\d.\s]*\d,\d{1,2}$")
_DOT_DECIMAL = re.compile(r"^-?[\d,\s]*\d\.\d{1,2}$")


def _decimal_comma(values: list[str], preset: Preset | None) -> tuple[bool, bool]:
    """(decimal comma, decided by the values)."""
    comma = dot = 0
    for raw in values:
        text = raw.strip().replace("\u00a0", "").replace("€", "").replace("EUR", "").strip()
        if _COMMA_DECIMAL.match(text):
            comma += 1
        elif _DOT_DECIMAL.match(text):
            dot += 1
    if comma and not dot:
        return True, True
    if dot and not comma:
        return False, True
    if preset is not None and preset.decimal_comma is not None:
        return preset.decimal_comma, False
    return comma > dot, False


def _date_formats(values: list[str]) -> list[str]:
    fitting = []
    for fmt in DATE_FORMATS:
        try:
            for raw in values:
                datetime.strptime(raw.strip(), fmt)  # noqa: DTZ007 - a calendar date
        except ValueError:
            continue
        fitting.append(fmt)
    return fitting


def _column(rows: list[list[str]], index: int) -> list[str]:
    return [r[index] for r in rows if index < len(r) and r[index].strip()]


def detect(data: bytes, preset_key: str = "") -> Detection:
    """How to read this CSV export, with a preview of its first lines."""
    _check_size(data)
    preset = PRESETS.get(preset_key)
    text, encoding = _decode(data)
    delimiter, rows, (skip, found) = _delimiter(text)
    header, body = rows[skip], rows[skip + 1 :]
    date_key = "date" if "date" in found else "value_date"
    columns = {name: header[found[key]].strip() for name, key in
               [(f, "date" if f == "date" else f) for f in FIELDS] if key in found}  # fmt: skip
    if date_key == "value_date":
        columns["date"] = header[found["value_date"]].strip()
    if "amount" in columns:
        columns.pop("debit", None)
        columns.pop("credit", None)
    questions: list[Question] = []

    money = [v for name in ("amount", "debit", "credit", "balance") if name in columns
             for v in _column(body, found[name])]  # fmt: skip
    comma, decided = _decimal_comma(money, preset)
    if not decided and money:
        questions.append(Question(
            "decimal_comma", "The amounts read the same with a decimal point or a decimal comma.",
            ("point", "comma"), "comma" if comma else "point"))  # fmt: skip

    dates = _column(body, found[date_key])
    fitting = _date_formats(dates)
    if not fitting:
        raise StatementFormatError(
            f"The dates in column '{columns['date']}' (for example "
            f"'{dates[0][:20] if dates else ''}') are in a format the import does not read yet."
        )
    day_first = [f for f in fitting if f.startswith("%d")]
    month_first = [f for f in fitting if f.startswith("%m")]
    if day_first and month_first:
        prefer_day = preset.day_first if preset else True
        chosen = day_first[0] if prefer_day else month_first[0]
        example = dates[0].strip()
        questions.append(Question(
            "date_format", f"Every date fits both day-month and month-day order (for example "
            f"{example}). Which is it?", (day_first[0], month_first[0]), chosen))  # fmt: skip
    else:
        chosen = fitting[0]

    mapping = CsvMapping(
        date=columns["date"], amount=columns.get("amount", ""),
        debit=columns.get("debit", ""), credit=columns.get("credit", ""),
        description=columns.get("description", ""), reference=columns.get("reference", ""),
        counterparty=columns.get("counterparty", ""), balance=columns.get("balance", ""),
        date_format=chosen, delimiter=delimiter, decimal_comma=comma,  # type: ignore[arg-type]
        has_header=True, encoding=encoding, skip_rows=skip,
    )  # fmt: skip
    found_detection = Detection(mapping=mapping, columns=columns, questions=questions,
                                preset=preset)  # fmt: skip
    try:
        parsed = parse_csv(data, replace(mapping, strict=True))
        found_detection.preview = parsed.lines[:PREVIEW_LINES]
    except StatementFormatError as refused:
        found_detection.error = str(refused)
    return found_detection
