"""Helpers shared by report exports (CSV, XLSX, PDF)."""

from functools import cache
from importlib import resources

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_text(value: str) -> str:
    """Neutralise spreadsheet formula injection in text cells (threat T9)."""
    return "'" + value if value.startswith(_FORMULA_PREFIXES) else value


@cache
def pdf_fonts() -> tuple[str, str]:
    """Register the bundled Liberation Sans (Latin and Greek; SIL OFL 1.1, see fonts/OFL.txt)
    with ReportLab once, and return the regular and bold font names."""
    from reportlab.pdfbase import pdfmetrics  # noqa: PLC0415 (only exports need ReportLab)
    from reportlab.pdfbase.ttfonts import TTFont  # noqa: PLC0415

    fonts = resources.files(__package__).joinpath("fonts")
    for name, filename in (("FCPSans", "LiberationSans-Regular.ttf"),
                           ("FCPSans-Bold", "LiberationSans-Bold.ttf")):  # fmt: skip
        with resources.as_file(fonts.joinpath(filename)) as path:
            pdfmetrics.registerFont(TTFont(name, str(path)))
    return "FCPSans", "FCPSans-Bold"


__all__ = ["pdf_fonts", "safe_text"]
