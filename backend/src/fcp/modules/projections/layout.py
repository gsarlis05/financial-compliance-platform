"""How the projected statements are laid out (M6-6): rows, their kind and their names.

Totals of the balance sheet (``BS.TOTAL_*``) are not stored values: they are sums of the stored,
rounded lines, worked out where they are shown, so they tie to the cent (doc 10 §2.4).
"""

from decimal import Decimal
from typing import Literal

from .drivers import OPEX_LINES, REVENUE_LINES
from .engine import ASSETS, EQUITY, LIABILITIES

Kind = Literal["line", "subtotal", "total"]
Layout = tuple[tuple[str, Kind], ...]

INCOME: Layout = (
    *((f"PL.{c}", "line") for c in REVENUE_LINES), ("PL.REVENUE", "subtotal"),
    ("PL.COGS", "line"), ("PL.GROSS_PROFIT", "subtotal"),
    *((f"PL.{c}", "line") for c in OPEX_LINES), ("PL.OPEX", "subtotal"),
    ("PL.EBITDA", "subtotal"), ("PL.DA", "line"), ("PL.EBIT", "subtotal"),
    ("PL.INTEREST", "line"), ("PL.PBT", "subtotal"), ("PL.TAX", "line"),
    ("PL.NET_INCOME", "total"),
)  # fmt: skip
BALANCE: Layout = (
    *((x, "line") for x in ASSETS), ("BS.TOTAL_ASSETS", "total"),
    *((x, "line") for x in LIABILITIES), ("BS.TOTAL_LIABILITIES", "subtotal"),
    *((x, "line") for x in EQUITY), ("BS.TOTAL_EQUITY", "subtotal"),
    ("BS.TOTAL_LIABILITIES_EQUITY", "total"),
)  # fmt: skip
CASH_FLOW: Layout = (
    ("CF.NET_INCOME", "line"), ("CF.DA", "line"), ("CF.WC.AR", "line"),
    ("CF.WC.INVENTORY", "line"), ("CF.WC.AP", "line"), ("CF.WC.TAX", "line"),
    ("CF.OPERATING", "subtotal"), ("CF.CAPEX", "line"), ("CF.INVESTING", "subtotal"),
    ("CF.BORROWING", "line"), ("CF.REPAYMENT", "line"), ("CF.SHARE_CAPITAL", "line"),
    ("CF.DIVIDENDS", "line"), ("CF.REVOLVER", "line"), ("CF.FINANCING", "subtotal"),
    ("CF.NET_CHANGE", "subtotal"), ("CF.OPENING_CASH", "line"), ("CF.CLOSING_CASH", "total"),
)  # fmt: skip
STATEMENTS: tuple[tuple[str, Layout], ...] = (
    ("IS", INCOME), ("BS", BALANCE), ("CF", CASH_FLOW),
)  # fmt: skip
TOTALS = {
    "BS.TOTAL_ASSETS": ASSETS,
    "BS.TOTAL_LIABILITIES": LIABILITIES,
    "BS.TOTAL_EQUITY": EQUITY,
    "BS.TOTAL_LIABILITIES_EQUITY": LIABILITIES + EQUITY,
}


def with_totals(rows: dict[str, list[Decimal | None]]) -> dict[str, list[Decimal | None]]:
    """The rows plus the balance-sheet totals, per column (None where a line is missing)."""
    out = dict(rows)
    width = max((len(v) for v in rows.values()), default=0)
    for total, lines in TOTALS.items():
        column: list[Decimal | None] = []
        for i in range(width):
            parts = [rows.get(x, [None] * width)[i] for x in lines]
            known = [p for p in parts if p is not None]
            column.append(sum(known, Decimal(0)) if len(known) == len(parts) else None)
        out[total] = column
    return out


NAMES: dict[str, tuple[str, str]] = {  # key: (English, Greek)
    "IS": ("Projected income statement", "Προβλεπόμενη κατάσταση αποτελεσμάτων"),
    "BS": ("Projected balance sheet", "Προβλεπόμενη κατάσταση οικονομικής θέσης"),
    "CF": ("Projected cash flow statement", "Προβλεπόμενη κατάσταση ταμειακών ροών"),
    "PL.REV.SALES": ("Sales of goods", "Πωλήσεις αγαθών"),
    "PL.REV.SERVICES": ("Services", "Παροχή υπηρεσιών"),
    "PL.REV.OTHER": ("Other income", "Λοιπά έσοδα"),
    "PL.REVENUE": ("Revenue", "Έσοδα"),
    "PL.COGS": ("Cost of sales", "Κόστος πωλήσεων"),
    "PL.GROSS_PROFIT": ("Gross profit", "Μικτό κέρδος"),
    "PL.OPEX.PAYROLL": ("Payroll", "Μισθοδοσία"),
    "PL.OPEX.RENT": ("Rent", "Ενοίκια"),
    "PL.OPEX.UTILITIES": ("Utilities", "Κοινόχρηστα και ενέργεια"),
    "PL.OPEX.PROFESSIONAL": ("Professional fees", "Αμοιβές τρίτων"),
    "PL.OPEX.MARKETING": ("Marketing", "Διαφήμιση"),
    "PL.OPEX.TRAVEL": ("Travel", "Ταξίδια"),
    "PL.OPEX.INSURANCE": ("Insurance", "Ασφάλιστρα"),
    "PL.OPEX.OTHER": ("Other operating costs", "Λοιπά λειτουργικά έξοδα"),
    "PL.OPEX": ("Operating costs", "Λειτουργικά έξοδα"),
    "PL.EBITDA": ("EBITDA", "EBITDA"),
    "PL.DA": ("Depreciation and amortisation", "Αποσβέσεις"),
    "PL.EBIT": ("Operating profit (EBIT)", "Λειτουργικό αποτέλεσμα (EBIT)"),
    "PL.INTEREST": ("Net finance costs", "Καθαρό χρηματοοικονομικό κόστος"),
    "PL.PBT": ("Profit before tax", "Κέρδος προ φόρων"),
    "PL.TAX": ("Income tax", "Φόρος εισοδήματος"),
    "PL.NET_INCOME": ("Net income", "Καθαρό αποτέλεσμα"),
    "BS.PPE.GROSS": ("Property, plant and equipment at cost", "Ενσώματα πάγια (κόστος)"),
    "BS.PPE.ACCDEP": ("Accumulated depreciation", "Συσσωρευμένες αποσβέσεις"),
    "BS.INTANGIBLES": ("Intangible assets", "Άυλα στοιχεία"),
    "BS.INVESTMENTS": ("Investments", "Επενδύσεις"),
    "BS.INVENTORY": ("Inventory", "Αποθέματα"),
    "BS.AR": ("Trade receivables", "Εμπορικές απαιτήσεις"),
    "BS.OTHER_REC": ("Other receivables", "Λοιπές απαιτήσεις"),
    "BS.TAX_REC": ("Tax receivable", "Απαιτήσεις φόρων"),
    "BS.CASH": ("Cash", "Ταμειακά διαθέσιμα"),
    "BS.TOTAL_ASSETS": ("Total assets", "Σύνολο ενεργητικού"),
    "BS.DEBT.NONCURRENT": ("Long-term debt", "Μακροπρόθεσμος δανεισμός"),
    "BS.DEBT.CURRENT": ("Short-term debt and credit facility",
                        "Βραχυπρόθεσμος δανεισμός και πιστωτικό όριο"),
    "BS.AP": ("Trade payables", "Εμπορικές υποχρεώσεις"),
    "BS.OTHER_PAY": ("Other payables", "Λοιπές υποχρεώσεις"),
    "BS.TAX_PAY": ("Tax payable", "Υποχρεώσεις φόρων"),
    "BS.TOTAL_LIABILITIES": ("Total liabilities", "Σύνολο υποχρεώσεων"),
    "BS.EQUITY.SHARE_CAPITAL": ("Share capital", "Μετοχικό κεφάλαιο"),
    "BS.EQUITY.SHARE_PREMIUM": ("Share premium", "Υπέρ το άρτιο"),
    "BS.EQUITY.RETAINED": ("Retained earnings", "Αποτελέσματα εις νέον"),
    "BS.TOTAL_EQUITY": ("Total equity", "Σύνολο ιδίων κεφαλαίων"),
    "BS.TOTAL_LIABILITIES_EQUITY": ("Total liabilities and equity",
                                    "Σύνολο υποχρεώσεων και ιδίων κεφαλαίων"),
    "CF.NET_INCOME": ("Net income", "Καθαρό αποτέλεσμα"),
    "CF.DA": ("Depreciation and amortisation", "Αποσβέσεις"),
    "CF.WC.AR": ("Change in trade receivables", "Μεταβολή εμπορικών απαιτήσεων"),
    "CF.WC.INVENTORY": ("Change in inventory", "Μεταβολή αποθεμάτων"),
    "CF.WC.AP": ("Change in trade payables", "Μεταβολή εμπορικών υποχρεώσεων"),
    "CF.WC.TAX": ("Change in tax payable", "Μεταβολή υποχρεώσεων φόρων"),
    "CF.OPERATING": ("Cash from operations", "Ταμειακές ροές λειτουργικών δραστηριοτήτων"),
    "CF.CAPEX": ("Capital expenditure", "Επενδύσεις σε πάγια"),
    "CF.INVESTING": ("Cash from investing", "Ταμειακές ροές επενδυτικών δραστηριοτήτων"),
    "CF.BORROWING": ("New borrowing", "Νέος δανεισμός"),
    "CF.REPAYMENT": ("Repayments", "Αποπληρωμές δανείων"),
    "CF.SHARE_CAPITAL": ("New share capital", "Αύξηση μετοχικού κεφαλαίου"),
    "CF.DIVIDENDS": ("Dividends", "Μερίσματα"),
    "CF.REVOLVER": ("Credit facility drawn or repaid", "Χρήση ή αποπληρωμή πιστωτικού ορίου"),
    "CF.FINANCING": ("Cash from financing", "Ταμειακές ροές χρηματοδοτικών δραστηριοτήτων"),
    "CF.NET_CHANGE": ("Net change in cash", "Καθαρή μεταβολή ταμειακών διαθεσίμων"),
    "CF.OPENING_CASH": ("Opening cash", "Ταμειακά διαθέσιμα έναρξης"),
    "CF.CLOSING_CASH": ("Closing cash", "Ταμειακά διαθέσιμα λήξης"),
}  # fmt: skip


def name(key: str, lang: str) -> str:
    english, greek = NAMES.get(key, (key, key))
    return greek if lang == "el" else english
