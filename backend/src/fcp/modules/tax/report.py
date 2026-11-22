"""The figures of a VAT period, computed from posted ledger lines (V1-2, pure).

Only what the books record is used; nothing is estimated and no rule is invented.

- **VAT** comes from lines on VAT accounts: output VAT (credit positive) on OUTPUT accounts, input
  VAT (debit positive) on INPUT accounts, by VAT code. Lines with the settlement code (payments to
  or refunds from the Tax Department, and the settlement entry) are shown apart and are not part
  of the period's VAT.
- **Taxable amounts** come from lines on other accounts that carry a VAT code. A line counts as a
  sale when its entry has output VAT on that code and no input VAT, as a purchase when it has input
  VAT only; otherwise (no VAT, as for zero-rated or exempt supplies, or both, as for a reverse
  charge) an income account means a sale and any other account a purchase. Sales are credit
  positive, purchases debit positive, so credit notes reduce them.
- **Checks**: the VAT each code's rate gives on its taxable amounts against the VAT recorded
  (at most one cent per entry apart), VAT on a code that carries none, VAT without a taxable
  amount and taxable amounts without VAT.

The law's own presentation of these figures (the return's items) is added from the official
sources as versioned data (``data/``); until then the report says so.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
SETTLEMENT = "SETTLEMENT"
NO_VAT = ("ZERO", "EXEMPT", "OUT_OF_SCOPE")
SIDES = {"sales": "sales", "purchase": "purchases"}


@dataclass(frozen=True)
class Line:
    line_id: str
    entry_id: str
    entry_ref: str
    accounting_date: str
    description: str
    account_code: str
    account_name: str
    account_type: str
    vat_role: str
    code: str
    treatment: str
    rate: Decimal | None
    verified: bool
    net_debit: Decimal
    counterparty: str
    reference: str


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _kind(line: Line, roles: set[str]) -> str:
    """SALE or PURCHASE for a taxable-amount line, from its entry's VAT on the same code."""
    if roles == {"OUTPUT"}:
        return "SALE"
    if roles == {"INPUT"}:
        return "PURCHASE"
    return "SALE" if line.account_type == "INCOME" else "PURCHASE"


def compute(lines: list[Line]) -> dict[str, Any]:
    roles: dict[tuple[str, str], set[str]] = defaultdict(set)
    for ln in lines:
        if ln.vat_role and ln.code and ln.treatment != SETTLEMENT:
            roles[(ln.entry_id, ln.code)].add(ln.vat_role)

    zero = Decimal(0)
    codes: dict[str, dict[str, Any]] = {}
    entries: dict[str, set[str]] = defaultdict(set)
    accounts: dict[str, dict[str, Any]] = {}
    settlements = zero
    shown: list[dict[str, Any]] = []
    exceptions: list[dict[str, str]] = []
    for ln in lines:
        acc: dict[str, Any] = {"vat": zero, "settled": zero}  # a throwaway for other lines
        if ln.vat_role:
            acc = accounts.setdefault(ln.account_code, {"code": ln.account_code,
                                      "name": ln.account_name, "role": ln.vat_role,
                                      "vat": zero, "settled": zero})  # fmt: skip
        if ln.treatment == SETTLEMENT:
            if ln.vat_role:  # the VAT side of a payment, refund or settlement entry
                settlements += ln.net_debit
                acc["settled"] += ln.net_debit
                shown.append(_shown(ln, "SETTLEMENT", ln.net_debit))
            continue
        if not ln.code:  # a VAT account line always has a code; kept for safety
            exceptions.append({"kind": "NO_CODE", "entry": ln.entry_ref,
                               "detail": f"{ln.account_code} has no VAT code."})  # fmt: skip
            continue
        row = codes.setdefault(ln.code, {"code": ln.code, "treatment": ln.treatment,
                               "rate": None if ln.rate is None else str(ln.rate),
                               "verified": ln.verified, "sales_base": zero, "sales_vat": zero,
                               "purchase_base": zero, "purchase_vat": zero})  # fmt: skip
        entries[ln.code].add(ln.entry_id)
        if ln.vat_role == "OUTPUT":
            amount = -ln.net_debit
            row["sales_vat"] += amount
            acc["vat"] += amount
            shown.append(_shown(ln, "SALE_VAT", amount))
        elif ln.vat_role == "INPUT":
            amount = ln.net_debit
            row["purchase_vat"] += amount
            acc["vat"] += amount
            shown.append(_shown(ln, "PURCHASE_VAT", amount))
        elif _kind(ln, roles.get((ln.entry_id, ln.code), set())) == "SALE":
            row["sales_base"] += -ln.net_debit
            shown.append(_shown(ln, "SALE", -ln.net_debit))
        else:
            row["purchase_base"] += ln.net_debit
            shown.append(_shown(ln, "PURCHASE", ln.net_debit))
    exceptions += _entry_checks(lines, roles)

    totals, rows = _summarise(codes, entries, exceptions)
    net = totals["sales_vat"] - totals["purchase_vat"]
    return {
        "codes": rows,
        "totals": {**{k: money(v) for k, v in totals.items()}, "net": money(net),
                   "direction": "PAYABLE" if net > 0 else "REFUNDABLE" if net < 0 else "NIL"},
        "accounts": [{**a, "vat": money(a["vat"]), "settled": money(a["settled"])}
                     for a in sorted(accounts.values(), key=lambda a: a["code"])],
        "settlements": money(settlements),
        "unverified_codes": sorted(r["code"] for r in rows if not r["verified"]),
        "exceptions": exceptions,
        "lines": shown,
    }  # fmt: skip


Row = dict[str, Any]


def _summarise(
    codes: dict[str, Row], entries: dict[str, set[str]], exceptions: list[dict[str, str]]
) -> tuple[dict[str, Decimal], list[Row]]:
    """Totals and one row per code, with the VAT each code's rate gives and its checks."""
    zero = Decimal(0)
    totals = {"sales_base": zero, "sales_vat": zero, "purchase_base": zero, "purchase_vat": zero}
    rows = []
    for code in sorted(codes):
        row = codes[code]
        for key in totals:
            totals[key] += row[key]
        rate = Decimal(row["rate"]) if row["rate"] is not None else None
        for side in ("sales", "purchase"):
            recorded = row[f"{side}_vat"]
            # A reverse charge: the buyer accounts for the output VAT on its own purchase.
            base = (
                row["purchase_base"]
                if row["treatment"] == "REVERSE_CHARGE"
                else row[f"{side}_base"]
            )
            expected = (base * rate).quantize(CENT, ROUND_HALF_UP) if rate else zero
            row[f"{side}_expected_vat"] = expected
            if row["treatment"] in NO_VAT and recorded:
                exceptions.append(
                    {
                        "kind": "VAT_ON_NO_VAT_CODE",
                        "entry": "",
                        "detail": f"{code}: VAT recorded on a code that carries none.",
                    }
                )
            elif abs(recorded - expected) > CENT * len(entries[code]):
                exceptions.append({"kind": "RATE_MISMATCH", "entry": "", "detail":
                                   f"{code} ({SIDES[side]}): VAT recorded {money(recorded)}, "
                                   f"{money(expected)} at the code's rate."})  # fmt: skip
        rows.append({k: money(v) if isinstance(v, Decimal) else v for k, v in row.items()})
    return totals, rows


def _shown(ln: Line, kind: str, amount: Decimal) -> dict[str, Any]:
    return {"line_id": ln.line_id, "entry_id": ln.entry_id, "entry_ref": ln.entry_ref,
            "date": ln.accounting_date, "description": ln.description,
            "account": f"{ln.account_code} {ln.account_name}", "code": ln.code, "kind": kind,
            "amount": money(amount), "counterparty": ln.counterparty,
            "reference": ln.reference}  # fmt: skip


def _entry_checks(
    lines: list[Line], roles: dict[tuple[str, str], set[str]]
) -> list[dict[str, str]]:
    based: set[tuple[str, str]] = set()
    refs: dict[str, str] = {}
    rated: dict[str, Decimal | None] = {}
    for ln in lines:
        refs[ln.entry_id] = ln.entry_ref
        rated[ln.code] = ln.rate
        if ln.code and not ln.vat_role and ln.treatment != SETTLEMENT:
            based.add((ln.entry_id, ln.code))
    found = []
    for entry_id, code in sorted(set(roles) - based):
        found.append({"kind": "VAT_WITHOUT_BASE", "entry": refs[entry_id],
                      "detail": f"{refs[entry_id]}: VAT on {code} without a taxable amount on "
                                "the same code."})  # fmt: skip
    for entry_id, code in sorted(based - set(roles)):
        if rated.get(code):
            found.append({"kind": "BASE_WITHOUT_VAT", "entry": refs[entry_id],
                          "detail": f"{refs[entry_id]}: a taxable amount on {code} without "
                                    "its VAT."})  # fmt: skip
    return found


def figures(report: dict[str, Any]) -> dict[str, Any]:
    """The part of a report that must not change once it is signed off (lines and figures)."""
    return {k: report[k] for k in ("codes", "totals", "accounts", "settlements", "lines")}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
