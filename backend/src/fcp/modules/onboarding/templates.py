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


def as_csv(kind: str) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerow([c.header for c in columns(kind)])
    return out.getvalue().encode("utf-8-sig")


def as_workbook(kind: str) -> bytes:
    from openpyxl import Workbook  # noqa: PLC0415 (only templates need openpyxl)
    from openpyxl.styles import Font  # noqa: PLC0415
    from openpyxl.utils import get_column_letter  # noqa: PLC0415

    cols = columns(kind)
    book = Workbook()
    sheet = book.active
    if sheet is None:  # pragma: no cover (a new workbook always has one sheet)
        raise ValueError("No sheet.")
    sheet.title = "Import"
    sheet.append([c.header for c in cols])
    for i, cell in enumerate(sheet[1]):
        cell.font = Font(bold=True)
        letter = get_column_letter(i + 1)
        sheet.column_dimensions[letter].width = max(14, len(cols[i].header) + 4)
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
    how.append([])
    how.append(["Example (synthetic)"])
    how.append([c.header for c in cols])
    for row in _DATA["templates"][kind]["example"]:
        how.append([safe_text(v) for v in row])
    how.column_dimensions["A"].width = 28
    how.column_dimensions["B"].width = 90
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
