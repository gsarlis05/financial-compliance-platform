"""Hardened bank statement parsers (M2-5, AC-M2-5): CAMT.053 and CSV, attacks, limits, fuzzing."""

import contextlib
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.devtools.demo.camt import Txn, camt053
from fcp.modules.banking import parsers
from fcp.modules.banking.parsers import CsvMapping, StatementFormatError, parse_camt053, parse_csv

IBAN = "CY17002001280000001200527600"
TXNS = [
    Txn(
        date(2026, 3, 1), Decimal("1190.00"), "Invoice INV-1", "INV-1", "Customer One (Demo)", "B1"
    ),
    Txn(date(2026, 3, 2), Decimal("-250.50"), "Rent March", "", "Landlord (Demo)", "B2"),
    Txn(date(2026, 3, 3), Decimal("-10.00"), "Card hold", status="PDNG"),
]


def test_camt053_reads_balances_entries_and_parties() -> None:
    statement = parse_camt053(camt053(TXNS, iban=IBAN, opening=Decimal("1000.00")))
    assert statement.iban == IBAN
    assert statement.currency == "EUR"
    assert statement.opening_balance == Decimal("1000.00")
    assert statement.closing_balance == Decimal("1939.50")
    assert statement.closing_date == date(2026, 3, 3)
    assert [(ln.booking_date, ln.amount) for ln in statement.lines] == [
        (date(2026, 3, 1), Decimal("1190.00")), (date(2026, 3, 2), Decimal("-250.50"))]  # fmt: skip
    first = statement.lines[0]
    assert (first.reference, first.counterparty_name, first.bank_ref) == (
        "INV-1", "Customer One (Demo)", "B1")  # fmt: skip
    assert statement.lines[1].counterparty_name == "Landlord (Demo)"  # the creditor on a debit


XXE = b"""<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>
<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02">&x;</Document>"""
LAUGHS = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
          + b"".join(f'<!ENTITY {c} "{("&" + p + ";") * 10}">'.encode()
                     for p, c in zip("abcdefgh", "bcdefghi", strict=True))
          + b']><Document>&i;</Document>')  # fmt: skip


@pytest.mark.parametrize("payload", [XXE, LAUGHS], ids=["xxe", "billion-laughs"])
def test_xml_attacks_are_refused(payload: bytes) -> None:
    with pytest.raises(StatementFormatError, match="refused for safety"):
        parse_camt053(payload)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"", "empty"),
        (b"not xml", "not well-formed"),
        (b'<?xml version="1.0" encoding="U-TF-8"?><Document/>', "not well-formed"),  # fuzz find
        (b'<Document xmlns="urn:x">x</Document>', "not an ISO 20022 CAMT.053"),
        (camt053(TXNS, iban=IBAN, opening=Decimal(0)).replace(b"1190.00", b"1e3"),
         "not an amount"),
        (camt053(TXNS, iban=IBAN, opening=Decimal(0)).replace(b"1190.00", b"1190.001"),
         "not an amount"),
        (camt053(TXNS, iban=IBAN, opening=Decimal(0)).replace(b"<Dt>2026-03-01</Dt></BookgDt>",
                                                             b"<Dt>2026-13-01</Dt></BookgDt>"),
         "not a date"),
        (camt053(TXNS, iban=IBAN, opening=Decimal(0)).replace(
            b'Ccy="EUR">250.50', b'Ccy="USD">250.50'), "same currency"),
        (camt053(TXNS, iban=IBAN, opening=Decimal(0)).replace(b"<Stmt>", b"<Stmt></Stmt><Stmt>", 1),
         "2 statements"),
    ],
)  # fmt: skip
def test_camt053_rejects_bad_files_with_a_reason(payload: bytes, message: str) -> None:
    with pytest.raises(StatementFormatError, match=message):
        parse_camt053(payload)


def test_size_and_row_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(StatementFormatError, match="larger than 5 MB"):
        parse_camt053(b" " * (parsers.MAX_BYTES + 1))
    monkeypatch.setattr(parsers, "MAX_LINES", 1)
    with pytest.raises(StatementFormatError, match="more than 1 entries"):
        parse_camt053(camt053(TXNS, iban=IBAN, opening=Decimal(0)))
    with pytest.raises(StatementFormatError, match="more than 1 rows"):
        parse_csv(b"date,amount\n2026-01-01,1\n2026-01-02,2\n")


def test_csv_with_the_default_mapping_and_balances() -> None:
    data = (b"date,description,amount,balance,counterparty_id,reference\n"
            b"2026-01-05,Receipt,1190.00,2190.00,C001,INV-1\n"
            b"2026-01-06,=cmd|' /C calc'!A0,-90.50,2099.50,S001,\n")  # fmt: skip
    statement = parse_csv(data)
    assert [ln.amount for ln in statement.lines] == [Decimal("1190.00"), Decimal("-90.50")]
    assert (statement.opening_balance, statement.closing_balance) == (
        Decimal("1000.00"), Decimal("2099.50"))  # fmt: skip
    assert statement.lines[0].reference == "INV-1"
    assert statement.lines[1].description.startswith("=cmd")  # stored as text, never evaluated


def test_csv_with_a_bank_specific_mapping() -> None:
    mapping = CsvMapping(date="1", amount="", debit="3", credit="4", description="2", reference="",
                         date_format="%d/%m/%Y", delimiter=";", decimal_comma=True,
                         has_header=False, encoding="cp1253")  # fmt: skip
    data = "05/01/2026;Πληρωμή ενοικίου;1.250,50;\n06/01/2026;Είσπραξη;;99,00\n".encode("cp1253")
    statement = parse_csv(data, mapping)
    assert [ln.amount for ln in statement.lines] == [Decimal("-1250.50"), Decimal("99.00")]
    assert statement.lines[0].description == "Πληρωμή ενοικίου"


@pytest.mark.parametrize(
    ("data", "mapping", "message"),
    [
        (b"date,amount\nxx,1\n", parsers.DEFAULT_CSV_MAPPING, "does not match the date format"),
        (b"date,amount\n2026-01-01,1.234\n", parsers.DEFAULT_CSV_MAPPING, "not an amount"),
        (b"date,total\n2026-01-01,1\n", CsvMapping(), "Column 'amount' is not in"),
        (b"2026-01-01\n", CsvMapping(date="1", amount="2", description="", reference="",
                                     has_header=False), "missing column"),
        (b"date,amount\n", CsvMapping(date_format="%s"), "Date format must be one of"),
        (b"\xff\xfe", CsvMapping(encoding="utf-8"), "not encoded as utf-8"),
        (b"\n\n", CsvMapping(), "no rows"),
        (b"a,b\n", CsvMapping(date="x", has_header=False), "columns are numbers from 1"),
        (b"a,b\n", CsvMapping(amount=""), "either an amount column"),
        (b"a,b\n", CsvMapping(debit="d", credit="c"), "not both"),
        (b"date,amount\n2026-01-01,1\n", CsvMapping(), "Column 'description' is not in"),
    ],
)  # fmt: skip
def test_csv_errors_are_actionable(data: bytes, mapping: CsvMapping, message: str) -> None:
    with pytest.raises(StatementFormatError, match=message):
        parse_csv(data, mapping)


# --- fuzzing: whatever the input, only StatementFormatError (or a valid result) comes out --------

VALID = camt053(TXNS, iban=IBAN, opening=Decimal("1000.00"))


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=2000))
def test_fuzz_random_bytes(data: bytes) -> None:
    for parse in (parse_camt053, parse_csv):
        with contextlib.suppress(StatementFormatError):
            parse(data)


@settings(max_examples=300, deadline=None)
@given(
    position=st.integers(min_value=0, max_value=len(VALID) - 1),
    replacement=st.binary(min_size=0, max_size=8),
    cut=st.integers(min_value=0, max_value=8),
)
def test_fuzz_mutated_statements(position: int, replacement: bytes, cut: int) -> None:
    mutated = VALID[:position] + replacement + VALID[position + cut :]
    try:
        statement = parse_camt053(mutated)
    except StatementFormatError:
        return
    assert all(abs(ln.amount) < Decimal("1e15") for ln in statement.lines)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=500))
def test_fuzz_csv_text(text: str) -> None:
    with contextlib.suppress(StatementFormatError):
        parse_csv(text.encode("utf-8"))
