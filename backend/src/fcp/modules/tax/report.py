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

from fcp.core import reviews

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
    # V1-2h: the line's foreign amount (signed like net_debit), its rate, the rate's time, source.
    txn_currency: str = ""
    txn_net_debit: Decimal | None = None
    exchange_rate: Decimal | None = None
    rate_at: str | None = None
    rate_source: str = ""


CURRENCY_POLICY = (
    "Amounts in a foreign currency are converted into euros at the exchange rate of the "
    "transaction's date and time, recorded on each line with its source (owner's decision, "
    "2026-11-23; to be confirmed by a tax professional, #93)."
)


def money(value: Decimal) -> str:
    return str((value + 0).quantize(CENT, rounding=ROUND_HALF_UP))  # + 0: never "-0.00"


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
    foreign = any(ln.txn_currency for ln in lines)
    return {
        **({"currency_policy": CURRENCY_POLICY} if foreign else {}),
        "return": vat_return,
        "codes": rows,
        "totals": {**{k: money(v) for k, v in totals.items()}, "net": money(net),
                   "direction": "PAYABLE" if net > 0 else "REFUNDABLE" if net < 0 else "NIL"},
        "accounts": [{**a, "vat": money(a["vat"]), "settled": money(a["settled"])}
                     for a in sorted(accounts.values(), key=lambda a: a["code"])],
        "settlements": money(settlements),
        **_reviews(boxes.rules["jurisdiction"], rows),
        "exceptions": exceptions,
        "lines": shown,
    }  # fmt: skip


Row = dict[str, Any]


def _reviews(jurisdiction: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Who checked the codes and the box rules, pinned with the report as it stood when prepared
    (brief 27); codes are listed as unverified only while nobody has checked them."""
    codes = reviews.review(reviews.vat_codes(jurisdiction))
    rules = reviews.review(reviews.vat_box_rules(jurisdiction))
    pending = sorted(r["code"] for r in rows if not r["verified"]) if codes.pending else []
    return {"unverified_codes": pending,
            "reviews": {"vat_codes": codes.as_dict(), "box_rules": rules.as_dict()}}  # fmt: skip


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
            "country": ln.country, "vat_no": ln.vat_no, **_foreign(ln, amount)}  # fmt: skip


def _foreign(ln: Line, amount: Decimal) -> dict[str, Any]:
    """The line's foreign amount, signed as the amount shown (V1-2h)."""
    if not ln.txn_currency or ln.txn_net_debit is None:
        return {}
    same = (amount >= 0) == (ln.net_debit >= 0)
    txn = ln.txn_net_debit if same else -ln.txn_net_debit
    return {"txn_currency": ln.txn_currency, "txn_amount": money(txn),
            "exchange_rate": f"{ln.exchange_rate:f}" if ln.exchange_rate is not None else "",
            "rate_at": ln.rate_at, "rate_source": ln.rate_source}  # fmt: skip


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
    keys = ("return", "codes", "totals", "accounts", "settlements", "lines", "imports")
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


# --- schedules and reconciliation (V1-2e, #216) -------------------------------------------------

REVERSE_CHARGE = frozenset(("EU_GOODS_ACQUISITION", "RC_EU_SERVICES", "RC_NON_EU_SERVICES",
                            "RC_DOMESTIC", "LEGACY_REVERSE_CHARGE"))  # fmt: skip
EU_KIND = {
    "EU_GOODS_SUPPLY": "GOODS_SUPPLIED", "EU_SERVICES_SUPPLY": "SERVICES_SUPPLIED",
    "EU_GOODS_ACQUISITION": "GOODS_ACQUIRED", "RC_EU_SERVICES": "SERVICES_RECEIVED",
}  # fmt: skip
SHOWN = ("entry_id", "entry_ref", "date", "description", "code", "category", "counterparty",
         "country", "vat_no", "reference")  # fmt: skip
SCHEDULES = ("sales", "purchases", "eu_trade", "reverse_charge", "imports")


def _groups(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The report's lines (settlements left out) as one row per entry and VAT code."""
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    zero = Decimal(0)
    for ln in lines:
        if ln["kind"] == "SETTLEMENT":
            continue
        row = rows.setdefault((ln["entry_id"], ln["code"]), {
            "entry_id": ln["entry_id"], "entry_ref": ln["entry_ref"], "date": ln["date"],
            "description": ln["description"], "code": ln["code"],
            "category": ln.get("category", ""), "counterparty": "", "country": "", "vat_no": "",
            "reference": "", "net_sale": zero, "output_vat": zero, "net_purchase": zero,
            "input_vat": zero, "blocked": zero, "boxes": {}, "lines": [],
        })  # fmt: skip
        for key in ("counterparty", "country", "vat_no", "reference"):
            row[key] = row[key] or ln.get(key) or ""
        amount = Decimal(ln["amount"])
        field = {"SALE": "net_sale", "SALE_VAT": "output_vat", "PURCHASE": "net_purchase",
                 "PURCHASE_VAT": "input_vat"}[ln["kind"]]  # fmt: skip
        row[field] += amount
        if ln["kind"] == "PURCHASE_VAT" and ln.get("blocked"):
            row["blocked"] += Decimal(ln["blocked"]) if amount >= 0 else -Decimal(ln["blocked"])
        for box, value in ln.get("boxes", {}).items():
            row["boxes"][box] = row["boxes"].get(box, zero) + Decimal(value)
        row["lines"].append(ln["line_id"])
    return list(rows.values())


def _out(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    shown = {k: row[k] for k in SHOWN}
    shown.update({k: money(row[k]) for k in keys})
    shown["boxes"] = {b: money(v) for b, v in row["boxes"].items()}
    shown["lines"] = row["lines"]
    return shown


def schedules(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Sales, purchases, EU trade, reverse charge and imports, each with its rows (one per entry
    and VAT code) and totals, from the report's frozen lines."""
    found: dict[str, list[dict[str, Any]]] = {k: [] for k in SCHEDULES}
    records = {r["entry_id"]: r for r in snapshot.get("imports", [])}
    for row in _groups(snapshot["lines"]):
        category = row["category"]
        if category == "IMPORT":
            record = records.get(row["entry_id"], {})
            found["imports"].append({
                **_out(row, "net_purchase", "input_vat", "blocked"),
                "customs_reference": record.get("customs_reference", ""),
                "customs_date": record.get("customs_date", ""),
                "customs_value": record.get("customs_value", "0.00"),
                "document_name": record.get("document_name", ""),
            })  # fmt: skip
        elif category in REVERSE_CHARGE:
            found["reverse_charge"].append({**_out(row, "net_purchase", "output_vat", "input_vat",
                                                   "blocked"), "type": category})  # fmt: skip
        else:
            if row["net_sale"] or row["output_vat"]:
                found["sales"].append(_out(row, "net_sale", "output_vat"))
            if row["net_purchase"] or row["input_vat"]:
                found["purchases"].append(_out(row, "net_purchase", "input_vat", "blocked"))
        if category in EU_KIND:
            net = row["net_sale"] if category.endswith("SUPPLY") else row["net_purchase"]
            found["eu_trade"].append({**_out(row), "type": EU_KIND[category], "net": money(net)})
    result: dict[str, Any] = {}
    for name, rows in found.items():
        keys = [k for k in ("net_sale", "output_vat", "net_purchase", "input_vat", "blocked", "net",
                            "customs_value") if rows and k in rows[0]]  # fmt: skip
        totals = {k: money(sum((Decimal(r[k]) for r in rows), Decimal(0))) for k in keys}
        result[name] = {"rows": rows, "totals": totals}
    return result


def reconcile(snapshot: dict[str, Any], final: dict[str, Any] | None,
              adjustments: list[tuple[str, Decimal]]) -> dict[str, Any] | None:  # fmt: skip
    """The VAT control accounts from their opening to their closing balance, and the return
    bridged to the ledger with every reconciling item. Balances are shown as the role reads
    them: output VAT credit positive, input VAT debit positive. Payments, refunds and the
    settlement entry stay apart from Box 5."""
    balances = snapshot.get("balances")
    if balances is None or final is None:
        return None
    period = {a["code"]: a for a in snapshot["accounts"]}
    rows, ledger = [], {"OUTPUT": Decimal(0), "INPUT": Decimal(0)}
    for code in sorted(balances):
        b = balances[code]
        sign = Decimal(-1) if b["role"] == "OUTPUT" else Decimal(1)
        opening, closing = sign * Decimal(b["opening"]), sign * Decimal(b["closing"])
        vat = Decimal(period.get(code, {}).get("vat", "0"))
        settled = sign * Decimal(period.get(code, {}).get("settled", "0"))
        ledger[b["role"]] += vat
        rows.append({"code": code, "name": b["name"], "role": b["role"],
                     "opening": money(opening), "vat": money(vat), "settled": money(settled),
                     "closing": money(closing),
                     "unexplained": money(closing - opening - vat - settled)})  # fmt: skip
    exact = {x["box"]: Decimal(x["exact"]) for x in final["boxes"]}
    adjusted: dict[str, Decimal] = {}
    for box, amount in adjustments:
        adjusted[box] = adjusted.get(box, Decimal(0)) + amount
    unmapped = {"SALE_VAT": Decimal(0), "PURCHASE_VAT": Decimal(0)}
    for ln in snapshot["lines"]:
        if ln["kind"] in unmapped and not ln.get("boxes"):
            unmapped[ln["kind"]] += Decimal(ln["amount"])

    def bridge(side: str, role: str, boxes: tuple[str, ...], kind: str) -> dict[str, Any]:
        returned = sum((exact[b] for b in boxes), Decimal(0))
        adjust = sum((adjusted.get(b, Decimal(0)) for b in boxes), Decimal(0))
        items = [
            {"item": "NOT_IN_A_BOX", "amount": money(-unmapped[kind])},
            {"item": "ADJUSTMENTS", "amount": money(adjust)},
        ]
        explained = ledger[role] - unmapped[kind] + adjust
        return {"side": side, "boxes": "+".join(boxes), "ledger": money(ledger[role]),
                "items": [i for i in items if Decimal(i["amount"])],
                "return": money(returned), "unexplained": money(returned - explained)}  # fmt: skip

    bridges = [bridge("OUTPUT", "OUTPUT", ("1", "2"), "SALE_VAT"),
               bridge("INPUT", "INPUT", ("4",), "PURCHASE_VAT")]  # fmt: skip
    return {"accounts": rows, "bridges": bridges, "settlements": snapshot["settlements"],
            "box_5": money(exact["5"]),
            "balanced": all(Decimal(r["unexplained"]) == 0 for r in rows + bridges)}  # fmt: skip


# --- imports (V1-2f, #217) ----------------------------------------------------------------------


def import_checks(lines: list[dict[str, Any]], records: list[dict[str, Any]],
                  codes: list[dict[str, Any]]) -> list[dict[str, str]]:  # fmt: skip
    """Each import VAT claim has its customs record; the record's import VAT is the VAT claimed
    (recoverable and not); and its taxable value at the code's rate gives that VAT."""
    claims: dict[str, dict[str, Any]] = {}
    for ln in lines:
        if ln.get("category") == "IMPORT" and ln["kind"] == "PURCHASE_VAT":
            row = claims.setdefault(ln["entry_id"], {"ref": ln["entry_ref"], "vat": Decimal(0),
                                                     "code": ln["code"]})  # fmt: skip
            amount = Decimal(ln["amount"])
            blocked = Decimal(ln.get("blocked") or 0)
            row["vat"] += amount + (blocked if amount >= 0 else -blocked)
    by_entry = {r["entry_id"]: r for r in records}
    rates = {c["code"]: Decimal(c["rate"]) for c in codes if c["rate"] is not None}
    found = []
    for entry_id, claim in claims.items():
        record = by_entry.get(entry_id)
        if record is None:
            found.append({"kind": "IMPORT_WITHOUT_RECORD", "entry": claim["ref"],
                          "detail": f"{claim['ref']}: import VAT of {money(claim['vat'])} is "
                                    "claimed without its customs record (reference, value and "
                                    "evidence)."})  # fmt: skip
            continue
        recorded = Decimal(record["import_vat"])
        if abs(recorded - claim["vat"]) > CENT:
            detail = (f"{claim['ref']}: the entry claims import VAT of {money(claim['vat'])}, the "
                      f"customs declaration {record['customs_reference']} shows "
                      f"{money(recorded)}.")  # fmt: skip
            found.append({"kind": "IMPORT_VAT_MISMATCH", "entry": claim["ref"], "detail": detail})
        rate = rates.get(claim["code"])
        if rate is not None:
            expected = (Decimal(record["customs_value"]) * rate).quantize(CENT, ROUND_HALF_UP)
            if abs(expected - recorded) > CENT:
                found.append({"kind": "IMPORT_VALUE_MISMATCH", "entry": claim["ref"],
                              "detail": f"{claim['ref']}: the taxable value "
                                        f"{money(Decimal(record['customs_value']))} at the code's "
                                        f"rate gives {money(expected)}, not the "
                                        f"{money(recorded)} declared."})  # fmt: skip
    return found


# --- VIES (V1-2g, #218) -------------------------------------------------------------------------

VIES_KINDS = {"EU_GOODS_SUPPLY": "goods", "EU_SERVICES_SUPPLY": "services"}


def vat_key(country: str, vat_no: str) -> tuple[str, str]:
    """A partner as VIES lists it: its country and its VAT number without spaces, punctuation or
    the country prefix (Greece's prefix is EL)."""
    number = "".join(ch for ch in vat_no.upper() if ch.isalnum())
    for prefix in {country, "EL" if country == "GR" else country}:
        if prefix and number.startswith(prefix):
            number = number[len(prefix) :]
            break
    return country, number


def _months(start: str, end: str) -> list[str]:
    year, month = int(start[:4]), int(start[5:7])
    found = []
    while f"{year:04d}-{month:02d}-01" <= end:
        found.append(f"{year:04d}-{month:02d}-01")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return found


def _vies_status(in_books: bool, in_vies: bool, filed: dict[str, Decimal],
                 diff: dict[str, Decimal]) -> str:  # fmt: skip
    if not in_vies:
        return "NOT_FILED"
    if not in_books:
        # Only triangular amounts: shown apart and compared with no box.
        return "NOT_IN_BOOKS" if filed["goods"] or filed["services"] else "TRIANGULAR"
    if not any(diff.values()):
        return "MATCH"
    return "ROUNDING" if all(abs(v) < 1 for v in diff.values()) else "DIFFERENCE"


def vies_reconcile(
    snapshot: dict[str, Any], final: dict[str, Any] | None, statements: list[dict[str, Any]],
    start: str, end: str,
) -> dict[str, Any]:  # fmt: skip
    """The EU supplies in the books, per partner, against the VIES statements recorded for the
    period's months, and their totals against Boxes 8A (goods) and 8B (services).

    For a month, the latest correction recorded replaces the original statement: a correction
    carries the month's full figures (owner's decision, 2026-11-23). Triangular amounts are
    shown apart and compared with no box. Differences are classed: a month with no statement, a
    partner only on one side, rounding (under one euro), or another difference to explain."""
    zero = Decimal(0)
    months = _months(start, end)
    used: dict[str, dict[str, Any]] = {}
    for st in sorted(statements, key=lambda s: (s["filed_on"], s["kind"] == "CORRECTION")):
        if st["month"] in months:
            used[st["month"]] = st  # the latest filed wins; a correction after its original
    books: dict[tuple[str, str], dict[str, Any]] = {}
    supplied: set[str] = set()
    for ln in snapshot["lines"]:
        kind = VIES_KINDS.get(ln.get("category", ""))
        if kind and ln["kind"] == "SALE":
            key = vat_key(ln.get("country", ""), ln.get("vat_no", ""))
            row = books.setdefault(key, {"goods": zero, "services": zero})
            row[kind] += Decimal(ln["amount"])
            supplied.add(ln["date"][:8] + "01")
    filed: dict[tuple[str, str], dict[str, Decimal]] = {}
    for st in used.values():
        for vl in st["lines"]:
            key = vat_key(vl["country"], vl["vat_no"])
            row = filed.setdefault(key, {"goods": zero, "services": zero, "triangular": zero})
            for k in ("goods", "services", "triangular"):
                row[k] += Decimal(vl[k])
    partners = []
    for key in sorted(set(books) | set(filed)):
        b = books.get(key, {"goods": zero, "services": zero})
        f = filed.get(key, {"goods": zero, "services": zero, "triangular": zero})
        diff = {k: f[k] - b[k] for k in ("goods", "services")}
        status = _vies_status(key in books, key in filed, f, diff)
        partners.append({"country": key[0], "vat_no": key[1], "status": status,
                         **{f"books_{k}": money(b[k]) for k in ("goods", "services")},
                         **{f"vies_{k}": money(f[k]) for k in ("goods", "services",
                                                                "triangular")},
                         **{f"difference_{k}": money(v) for k, v in diff.items()}})  # fmt: skip
    boxes = {b["box"]: b for b in (final or {}).get("boxes", [])}
    totals = []
    for kind, box in (("goods", "8A"), ("services", "8B")):
        reported = sum((f[kind] for f in filed.values()), zero)
        exact = Decimal(boxes[box]["exact"]) if box in boxes else zero
        totals.append({"kind": kind, "box": box, "vies": money(reported),
                       "box_exact": money(exact),
                       "box_amount": boxes[box]["amount"] if box in boxes else "0.00",
                       "difference": money(reported - exact)})  # fmt: skip
    return {
        "months": [{"month": m, "statement": used[m]["reference"] if m in used else "",
                    "kind": used[m]["kind"] if m in used else "",
                    "supplies": m in supplied} for m in months],
        "missing_months": [m for m in months if m in supplied and m not in used],
        "partners": partners,
        "totals": totals,
        "triangular": money(sum((f["triangular"] for f in filed.values()), zero)),
        "agrees": all(p["status"] in ("MATCH", "TRIANGULAR") for p in partners)
                  and not any(m in supplied and m not in used for m in months),
    }  # fmt: skip
