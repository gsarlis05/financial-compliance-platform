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

- **The return** (V1-2c, #214): each line adds its amount to the boxes its VAT code's category
  and its kind (output VAT, input VAT, net sale, net purchase) map to in the box rules
  (``boxes``, versioned data marked unverified). Box 3 = 1 + 2 and Box 5 = 3 - 4; Boxes 1-5 are
  shown to the cent, Boxes 6-11B to the nearest euro with the rounding shown. A line whose
  category the rules do not support is an exception, never guessed into a box.
"""

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .boxes import ALL_BOXES, VAT_BOXES, LineKind, mapping, ruleset

CENT = Decimal("0.01")
EURO = Decimal(1)
RULES = "CY-VAT-BOXES@1"
# The 27 member states (ISO 3166-1 alpha-2; Greece is GR here, EL in VAT numbers).
EU = frozenset((
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE",
    "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE",
))  # fmt: skip
EU_TRADE = frozenset(("EU_GOODS_SUPPLY", "EU_SERVICES_SUPPLY", "EU_GOODS_ACQUISITION",
                      "RC_EU_SERVICES"))  # fmt: skip
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
    # V1-2c: the code's category, the line's VAT details and the party's EU data.
    category: str = ""
    tax_point: str | None = None
    recovery_percent: Decimal | None = None
    blocked: Decimal | None = None
    country: str = ""
    vat_no: str = ""


def money(value: Decimal) -> str:
    return str(value.quantize(CENT, rounding=ROUND_HALF_UP))


def _kind(line: Line, roles: set[str]) -> str:
    """SALE or PURCHASE for a taxable-amount line, from its entry's VAT on the same code."""
    if roles == {"OUTPUT"}:
        return "SALE"
    if roles == {"INPUT"}:
        return "PURCHASE"
    return "SALE" if line.account_type == "INCOME" else "PURCHASE"


def compute(
    lines: list[Line], start: str | None = None, end: str | None = None, rules: str = RULES
) -> dict[str, Any]:
    roles: dict[tuple[str, str], set[str]] = defaultdict(set)
    for ln in lines:
        if ln.vat_role and ln.code and ln.treatment != SETTLEMENT:
            roles[(ln.entry_id, ln.code)].add(ln.vat_role)

    zero = Decimal(0)
    boxes = _Boxes(rules)
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
                shown.append(boxes.excluded(ln, _shown(ln, "SETTLEMENT", ln.net_debit)))
            continue
        if not ln.code:  # a VAT account line always has a code; kept for safety
            exceptions.append({"kind": "NO_CODE", "entry": ln.entry_ref,
                               "detail": f"{ln.account_code} has no VAT code."})  # fmt: skip
            continue
        row = codes.setdefault(ln.code, {"code": ln.code, "treatment": ln.treatment,
                               "rate": None if ln.rate is None else str(ln.rate),
                               "verified": ln.verified, "sales_base": zero, "sales_vat": zero,
                               "purchase_base": zero, "purchase_vat": zero,
                               "purchase_blocked": zero})  # fmt: skip
        entries[ln.code].add(ln.entry_id)
        kind: LineKind
        if ln.vat_role == "OUTPUT":
            kind, amount, shown_kind = "OUTPUT_VAT", -ln.net_debit, "SALE_VAT"
            row["sales_vat"] += amount
            acc["vat"] += amount
        elif ln.vat_role == "INPUT":
            kind, amount, shown_kind = "INPUT_VAT", ln.net_debit, "PURCHASE_VAT"
            row["purchase_vat"] += amount
            # Non-recoverable VAT, signed like the line (a credit note reverses it too).
            if ln.blocked:
                row["purchase_blocked"] += ln.blocked if amount >= 0 else -ln.blocked
            acc["vat"] += amount
        elif _kind(ln, roles.get((ln.entry_id, ln.code), set())) == "SALE":
            kind, amount, shown_kind = "NET_SALE", -ln.net_debit, "SALE"
            row["sales_base"] += amount
        else:
            kind, amount, shown_kind = "NET_PURCHASE", ln.net_debit, "PURCHASE"
            row["purchase_base"] += amount
        shown.append(boxes.add(ln, kind, amount, _shown(ln, shown_kind, amount)))
    exceptions += _entry_checks(lines, roles)
    exceptions += boxes.exceptions + _line_checks(lines, start, end)

    totals, rows = _summarise(codes, entries, exceptions)
    net = totals["sales_vat"] - totals["purchase_vat"]
    vat_return = boxes.result()
    exceptions += [{"kind": "BOX_CHECK", "entry": "", "detail": c["detail"]}
                   for c in vat_return["checks"] if not c["ok"]]  # fmt: skip
    return {
        "return": vat_return,
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
            # The rate gives the whole VAT; on purchases, only part of it may be recoverable.
            recorded = row[f"{side}_vat"] + (row["purchase_blocked"] if side == "purchase" else 0)
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
            "reference": ln.reference, "category": ln.category, "tax_point": ln.tax_point,
            "recovery_percent": None if ln.recovery_percent is None else str(ln.recovery_percent),
            "blocked": None if ln.blocked is None else money(ln.blocked),
            "country": ln.country, "vat_no": ln.vat_no}  # fmt: skip


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
    keys = ("return", "codes", "totals", "accounts", "settlements", "lines")
    return {k: report[k] for k in keys if k in report}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


class _Boxes:
    """The return's boxes, built from each line's contribution under one version of the rules."""

    def __init__(self, rules: str) -> None:
        self.rules = ruleset(rules)
        self.version = rules
        self.exact: dict[str, Decimal] = {b: Decimal(0) for b in ALL_BOXES}
        self.exceptions: list[dict[str, str]] = []
        self._unsupported: set[tuple[str, str, str]] = set()

    def add(self, ln: Line, kind: LineKind, amount: Decimal, row: dict[str, Any]) -> dict[str, Any]:
        found = mapping(ln.category, kind, self.version)
        for box in found.boxes:
            self.exact[box] += amount
        if found.status == "UNSUPPORTED" and (ln.entry_ref, ln.code, kind) not in self._unsupported:
            self._unsupported.add((ln.entry_ref, ln.code, kind))
            detail = f"{ln.entry_ref} ({ln.code}): {found.reason}"
            self.exceptions.append({"kind": "UNSUPPORTED", "entry": ln.entry_ref,
                                    "detail": detail})  # fmt: skip
        return {**row, "line_kind": kind, "mapping": found.status, "rule": found.reason,
                "boxes": {b: money(amount) for b in found.boxes}}  # fmt: skip

    def excluded(self, ln: Line, row: dict[str, Any]) -> dict[str, Any]:
        found = mapping(ln.category or "SETTLEMENT", "INPUT_VAT", self.version)
        return {**row, "line_kind": "", "mapping": found.status, "rule": found.reason,
                "boxes": {}}  # fmt: skip

    def result(self) -> dict[str, Any]:
        return {"rules": self.version, "status": self.rules["status"],
                "sources": self.rules["sources"],
                **present(dict(self.exact), self.rules)}  # fmt: skip


def present(value: dict[str, Decimal], rules: dict[str, Any]) -> dict[str, Any]:
    """The boxes as shown, from their exact amounts: Box 3 and Box 5 computed, the value boxes
    rounded to the euro with the rounding kept, the cross-field checks and the direction."""
    value["3"] = value["1"] + value["2"]
    value["5"] = value["3"] - value["4"]
    rows = []
    for spec in rules["boxes"]:
        box = spec["box"]
        exact = value[box]
        shown = exact.quantize(CENT if box in VAT_BOXES else EURO, ROUND_HALF_UP)
        rows.append({"box": box, "label": spec["label"], "kind": spec["kind"],
                     "amount": money(shown), "exact": money(exact),
                     "rounding": money(shown - exact)})  # fmt: skip
    outputs = sum((value[b] for b in ("8A", "8B", "9", "10", "11B")), Decimal(0))
    inputs = value["11A"] + value["11B"]
    checks = [
        {"check": "BOX_3", "ok": value["3"] == value["1"] + value["2"],
         "detail": "Box 3 is Box 1 plus Box 2."},
        {"check": "BOX_5", "ok": value["5"] == value["3"] - value["4"],
         "detail": "Box 5 is Box 3 minus Box 4."},
        {"check": "BOX_6", "ok": value["6"] >= outputs,
         "detail": f"Box 6 ({money(value['6'])}) is at least Boxes 8A + 8B + 9 + 10 + 11B "
                   f"({money(outputs)}). A credit note or correction can explain a shortfall."},
        {"check": "BOX_7", "ok": value["7"] >= inputs,
         "detail": f"Box 7 ({money(value['7'])}) is at least Boxes 11A + 11B "
                   f"({money(inputs)}). A credit note or correction can explain a shortfall."},
    ]  # fmt: skip
    net = value["5"]
    direction = "PAYABLE" if net > 0 else "REFUNDABLE" if net < 0 else "NIL"
    return {"boxes": rows, "checks": checks, "direction": direction}


def adjusted(vat_return: dict[str, Any], adjustments: list[tuple[str, Decimal]]) -> dict[str, Any]:
    """The return after approved manual adjustments (V1-2d): for each box, the amount from the
    ledger, the adjustments and the final amount; Boxes 3 and 5, the rounding and the checks
    follow the final amounts. The ledger's figures are never changed."""
    value = {b["box"]: Decimal(b["exact"]) for b in vat_return["boxes"]}
    added = {b: Decimal(0) for b in value}
    for box, amount in adjustments:
        added[box] += amount
        value[box] += amount
    final = present(value, ruleset(vat_return["rules"]))
    original = {b["box"]: b["amount"] for b in vat_return["boxes"]}
    for row in final["boxes"]:
        row["original"] = original[row["box"]]
        row["adjustment"] = money(added[row["box"]])
    return {**vat_return, **final, "adjusted": any(added.values())}


def _line_checks(lines: list[Line], start: str | None, end: str | None) -> list[dict[str, str]]:
    """Tax points outside the period, and missing or inconsistent EU party data (V1-2c)."""
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for ln in lines:
        if ln.tax_point and start and end and not start <= ln.tax_point <= end:
            found.append({"kind": "TAX_POINT_OUTSIDE_PERIOD", "entry": ln.entry_ref,
                          "detail": f"{ln.entry_ref}: tax point {ln.tax_point} is outside the "
                                    f"period ({start} to {end}). Check which return it belongs "
                                    "to."})  # fmt: skip
        if ln.vat_role or not ln.category or (ln.entry_ref, ln.code) in seen:
            continue
        seen.add((ln.entry_ref, ln.code))
        problem = _party_problem(ln)
        if problem:
            found.append({"kind": "PARTY_DATA", "entry": ln.entry_ref,
                          "detail": f"{ln.entry_ref} ({ln.code}): {problem}"})  # fmt: skip
    return found


def _party_problem(ln: Line) -> str:
    if ln.category in EU_TRADE:
        if not ln.country or not ln.vat_no:
            return "the customer or supplier needs a country and a VAT number for EU trade."
        if ln.country == "CY" or ln.country not in EU:
            return f"EU trade with a party in {ln.country}, which is not another EU member state."
    if ln.category == "RC_NON_EU_SERVICES" and ln.country in EU:
        return f"a non-EU reverse charge with a supplier in {ln.country}, an EU member state."
    if ln.category == "RC_DOMESTIC" and ln.country not in ("", "CY"):
        return f"a domestic reverse charge with a party in {ln.country}."
    return ""
