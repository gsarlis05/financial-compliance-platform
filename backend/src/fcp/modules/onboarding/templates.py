"""The import templates (R-2, #245): an .xlsx workbook or a CSV file per kind of data.

The workbook's first sheet is the one read back: its header row and nothing else. A second sheet,
"How to fill in", explains each column and shows synthetic example rows; it is never imported.
"""

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from fcp.core.export import safe_text

from .tables import names

_DATA = json.loads((Path(__file__).parent / "templates.json").read_text("utf-8"))
KINDS = tuple(_DATA["templates"])
YES = frozenset(names(*_DATA["yes"]))
NO = frozenset(names(*_DATA["no"]))
# Account types as written in the chart (ours, accountants' and packages'), normalised; a type such
# as "Accounts Receivable" also makes the account a control account ("ASSET:RECEIVABLE").
ACCOUNT_TYPES = {names(k)[0]: v for k, v in _DATA["account_types"].items()}
TOTAL_WORDS = names(*_DATA["totals"])


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    day_first: bool
    note: str
    status: str = "TO_BE_CONFIRMED"


PRESETS = {p["key"]: Preset(p["key"], p["name"], p["day_first"], p["note"])
           for p in _DATA["presets"]}  # fmt: skip


def is_total(*cells: str) -> bool:
    """A subtotal or total row: its first text cell starts with a word such as Total."""
    first = next((c for c in cells if c.strip()), "")
    words = names(first)[0] if first else ""
    return any(words == w or words.startswith(f"{w} ") for w in TOTAL_WORDS)


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    also: tuple[str, ...]
    note: str


def title(kind: str) -> str:
    return str(_DATA["templates"][kind]["title"])


def columns(kind: str) -> list[Column]:
    return [Column(c["key"], c["header"], tuple(c["also"]), c["note"])
            for c in _DATA["templates"][kind]["columns"]]  # fmt: skip


def fields(kind: str) -> dict[str, tuple[str, ...]]:
    """Each field with the normalised header names that identify it."""
    return {c.key: names(c.header, *c.also) for c in columns(kind)}


def headers(kind: str, months: tuple[str, ...] = ()) -> list[str]:
    """The header row; the prior-year template adds one column per month (2025-01 …)."""
    return [c.header for c in columns(kind)] + list(months)


def as_csv(kind: str, months: tuple[str, ...] = ()) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerow(headers(kind, months))
    return out.getvalue().encode("utf-8-sig")


def as_workbook(kind: str, months: tuple[str, ...] = ()) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 (only templates need openpyxl)
    from openpyxl.styles import Font  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    cols = columns(kind)
    head = headers(kind, months)
    book = Workbook()
    sheet = book.active
    if sheet is None:  # pragma: no cover (a new workbook always has one sheet)
        raise ValueError("No sheet.")
    sheet.title = "Import"
    sheet.append(head)
    for i, cell in enumerate(sheet[1]):
        cell.font = Font(bold=True)
        letter = get_column_letter(i + 1)
        sheet.column_dimensions[letter].width = max(14, len(head[i]) + 4)
        # Codes typed in these columns stay text: leading zeros are kept.
        sheet.column_dimensions[letter].number_format = "@"
    sheet.freeze_panes = "A2"
    how = book.create_sheet("How to fill in")
    how.append([safe_text(f"{title(kind)}: fill in the first sheet, one row per line. "
                          "This sheet is not imported.")])  # fmt: skip
    how["A1"].font = Font(bold=True)
    how.append([])
    how.append(["Column", "What to enter"])
    for cell in how[3]:
        cell.font = Font(bold=True)
    for c in cols:
        how.append([safe_text(c.header), safe_text(c.note)])
    template = _DATA["templates"][kind]
    if "months_note" in template:
        how.append(["2025-01 …", safe_text(template["months_note"])])
    how.append([])
    how.append(["Example (synthetic)"])
    width = len(template["example"][0])
    how.append([*head, "2025-01", "2025-02"][:width] if months else head)
    for row in _DATA["templates"][kind]["example"]:
        how.append([safe_text(v) for v in row])
    how.column_dimensions["A"].width = 28
    how.column_dimensions["B"].width = 90
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
