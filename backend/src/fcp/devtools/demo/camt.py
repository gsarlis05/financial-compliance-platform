"""Write synthetic ISO 20022 CAMT.053 statements (tests and the demo; never real bank data)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from xml.sax.saxutils import escape

NS = "urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"


@dataclass(frozen=True)
class Txn:
    booking_date: date
    amount: Decimal  # positive in, negative out
    description: str = ""
    reference: str = ""
    party: str = ""
    bank_ref: str = ""
    status: str = "BOOK"


def _amount(value: Decimal, currency: str) -> str:
    indicator = "CRDT" if value >= 0 else "DBIT"
    return f'<Amt Ccy="{currency}">{abs(value):.2f}</Amt><CdtDbtInd>{indicator}</CdtDbtInd>'


def _balance(code: str, value: Decimal, day: date, currency: str) -> str:
    return (f"<Bal><Tp><CdOrPrtry><Cd>{code}</Cd></CdOrPrtry></Tp>{_amount(value, currency)}"
            f"<Dt><Dt>{day.isoformat()}</Dt></Dt></Bal>")  # fmt: skip


def _entry(t: Txn, currency: str) -> str:
    role = "Dbtr" if t.amount >= 0 else "Cdtr"
    party = f"<RltdPties><{role}><Nm>{escape(t.party)}</Nm></{role}></RltdPties>" if t.party else ""
    reference = (f"<Strd><CdtrRefInf><Ref>{escape(t.reference)}</Ref></CdtrRefInf></Strd>"
                 if t.reference else "")  # fmt: skip
    return (
        f"<Ntry>{_amount(t.amount, currency)}<Sts>{t.status}</Sts>"
        f"<BookgDt><Dt>{t.booking_date.isoformat()}</Dt></BookgDt>"
        f"<ValDt><Dt>{t.booking_date.isoformat()}</Dt></ValDt>"
        f"<AcctSvcrRef>{escape(t.bank_ref)}</AcctSvcrRef>"
        f"<NtryDtls><TxDtls>{party}<RmtInf><Ustrd>{escape(t.description)}</Ustrd>{reference}"
        f"</RmtInf></TxDtls></NtryDtls></Ntry>"
    )


def camt053(
    txns: Sequence[Txn], *, iban: str, opening: Decimal, statement_id: str = "STMT-1",
    currency: str = "EUR", period: tuple[date, date] | None = None,
) -> bytes:  # fmt: skip
    """``period`` defaults to the first and last booking dates (one of them must be given)."""
    booked = [t for t in txns if t.status == "BOOK"]
    first, last = period or (min(t.booking_date for t in txns), max(t.booking_date for t in txns))
    closing = opening + sum((t.amount for t in booked), Decimal(0))
    body = "".join(_entry(t, currency) for t in txns)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><Document xmlns="{NS}"><BkToCstmrStmt>'
        f"<GrpHdr><MsgId>{escape(statement_id)}</MsgId><CreDtTm>{last.isoformat()}T23:59:59"
        f"</CreDtTm></GrpHdr><Stmt><Id>{escape(statement_id)}</Id>"
        f"<Acct><Id><IBAN>{escape(iban)}</IBAN></Id><Ccy>{currency}</Ccy></Acct>"
        f"{_balance('OPBD', opening, first, currency)}{_balance('CLBD', closing, last, currency)}"
        f"{body}</Stmt></BkToCstmrStmt></Document>"
    ).encode()
