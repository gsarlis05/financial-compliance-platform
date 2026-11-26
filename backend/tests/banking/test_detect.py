"""Recognising a bank's CSV export (R-1, #244). Synthetic files only: the shapes are typical of
bank exports (Greek or English headers, account details before the header, decimal commas,
separate debit and credit columns, timestamps); none is a real bank's file."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from fcp.modules.banking.detect import PRESETS, detect, normalise
from fcp.modules.banking.parsers import StatementFormatError, parse_csv

from ..ledger.conftest import books
from .test_banking import bank, upload

__all__ = ["bank", "books"]

GREEK = (
    "Λογαριασμός;CY00 0000 0000 0000 (Demo)\n"
    "Περίοδος;01/03/2026 - 31/03/2026\n"
    "\n"
    "Ημερομηνία;Ημερομηνία Αξίας;Περιγραφή;Χρέωση;Πίστωση;Υπόλοιπο\n"
    "02/03/2026;02/03/2026;Ενοίκιο Μαρτίου (Demo);1.250,00;;8.750,00\n"
    "15/03/2026;15/03/2026;Είσπραξη τιμολογίου 17 (Demo);;3.400,50;12.150,50\n"
    "28/03/2026;28/03/2026;Προμήθεια τράπεζας (Demo);4,20;;12.146,30\n"
)

ENGLISH = (
    "Type,Started Date,Completed Date,Description,Amount,Fee,Currency,State,Balance\n"
    "CARD_PAYMENT,2026-03-03 09:12:44,2026-03-04 10:01:02,Office supplies (Demo),-45.90,0.00,"
    "EUR,COMPLETED,1954.10\n"
    "TRANSFER,2026-03-10 14:00:00,2026-03-10 14:00:05,Client payment (Demo),1200.00,0.00,EUR,"
    "COMPLETED,3154.10\n"
)


def test_greek_headers_windows_greek_preamble_and_decimal_comma() -> None:
    found = detect(GREEK.encode("cp1253"))
    m = found.mapping
    assert (m.encoding, m.delimiter, m.skip_rows, m.decimal_comma) == ("cp1253", ";", 2, True)
    assert (m.date, m.debit, m.credit, m.balance, m.amount) == (
        "Ημερομηνία", "Χρέωση", "Πίστωση", "Υπόλοιπο", "")  # fmt: skip
    assert m.description == "Περιγραφή"
    # 02/03, 15/03, 28/03: only day-first fits 15 and 28.
    assert (m.date_format, found.questions) == ("%d/%m/%Y", [])
    assert [(ln.booking_date, ln.amount) for ln in found.preview] == [
        (date(2026, 3, 2), Decimal("-1250.00")),
        (date(2026, 3, 15), Decimal("3400.50")),
        (date(2026, 3, 28), Decimal("-4.20")),
    ]
    assert found.error == ""
    # The mapping found reads the whole file with the normal parser.
    assert parse_csv(GREEK.encode("cp1253"), m).closing_balance == Decimal("12146.30")


def test_english_export_with_timestamps_and_a_signed_amount() -> None:
    found = detect(ENGLISH.encode("utf-8"), "REVOLUT_BUSINESS")
    m = found.mapping
    assert (m.date, m.amount, m.balance, m.decimal_comma) == (
        "Completed Date", "Amount", "Balance", False)  # fmt: skip
    assert m.date_format == "%Y-%m-%d %H:%M:%S"
    assert [ln.amount for ln in found.preview] == [Decimal("-45.90"), Decimal("1200.00")]
    assert found.preset is PRESETS["REVOLUT_BUSINESS"]
    assert found.preset.status == "TO_BE_CONFIRMED"


def test_dates_that_fit_both_orders_are_a_question() -> None:
    text = "Date,Description,Amount\n03/04/2026,Rent (Demo),-100.00\n05/04/2026,Fee (Demo),-2.00\n"
    found = detect(text.encode())
    [question] = found.questions
    assert question.field == "date_format"
    assert question.options == ("%d/%m/%Y", "%m/%d/%Y")
    assert question.chosen == "%d/%m/%Y"  # Cyprus default: day first
    assert "03/04/2026" in question.message


def test_amounts_without_decimals_leave_the_separator_open() -> None:
    text = "Date;Description;Amount\n2026-03-01;Deposit (Demo);1000\n"
    found = detect(text.encode())
    assert [q.field for q in found.questions] == ["decimal_comma"]


def test_a_file_without_a_recognisable_header_is_refused_clearly() -> None:
    with pytest.raises(StatementFormatError, match="No header with a date and an amount"):
        detect(b"a,b,c\n1,2,3\n")


def test_headers_compare_without_case_accents_or_punctuation() -> None:
    assert normalise("  ΗΜΕΡΟΜΗΝΊΑ Αξίας: ") == "ημερομηνια αξιας"
    assert normalise("Ref. No.") == "ref no"


# --- through the API ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_detect_save_and_import_through_the_api(bank: dict[str, Any]) -> None:
    """Recognise the file, save the layout as the account's mapping, then import as usual."""
    client, url = bank["client"], bank["bank_url"]
    data = GREEK.encode("cp1253")
    got = client.post(f"{url}/csv-detect", {"file": SimpleUploadedFile("s.csv", data),
                                            "preset": "BANK_OF_CYPRUS"},
                      headers=client._csrf())  # fmt: skip
    assert got.status_code == 200, got.content
    found = got.json()
    assert found["columns"]["debit"] == "Χρέωση"
    assert [ln["amount"] for ln in found["preview"]] == ["-1250.00", "3400.50", "-4.20"]
    assert (found["preset"]["key"], found["preset"]["status"]) == (
        "BANK_OF_CYPRUS", "TO_BE_CONFIRMED")  # fmt: skip
    saved = client.put_json(f"{url}/csv-mapping", found["mapping"])
    assert saved.status_code == 200, saved.content
    result = upload(bank, data, "CSV", "s.csv").json()
    assert (result["status"], result["lines_created"]) == ("DONE", 3)
    assert result["closing_balance"] == "12146.30"
    presets = client.get(f"{bank['base']}/bank-presets").json()
    assert [p["key"] for p in presets] == ["BANK_OF_CYPRUS", "HELLENIC_BANK", "EUROBANK_CYPRUS",
                                           "REVOLUT_BUSINESS"]  # fmt: skip
    # Nothing recognisable: a clear refusal, nothing saved.
    bad = client.post(f"{url}/csv-detect", {"file": SimpleUploadedFile("x.csv", b"a,b\n1,2\n")},
                      headers=client._csrf())  # fmt: skip
    assert bad.status_code == 422
