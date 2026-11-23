"""The VAT computation on its own (V1-2): classification of taxable amounts, settlements and every
kind of exception, on hand-made lines."""

from decimal import Decimal

from fcp.modules.tax.report import Line, compute, digest, figures

CATEGORY = {"S19": "DOMESTIC", "Z0": "ZERO_RATED", "RC": "LEGACY_REVERSE_CHARGE",
            "SETTLE": "SETTLEMENT"}  # fmt: skip


def line(*fields: str | None) -> Line:
    """(entry, account, account type, VAT role, code, treatment, rate, net debit)."""
    entry, account, kind, role, code, treatment, rate, net_debit = fields
    assert entry
    assert account
    assert kind is not None
    assert code
    assert treatment
    assert net_debit
    return Line(f"{entry}-{account}", entry, f"GJ-{entry}", "2026-01-10", "test", account,
                f"Account {account}", kind, role or "", code, treatment,
                Decimal(rate) if rate is not None else None, False, Decimal(net_debit),
                "", "", category=CATEGORY[code])  # fmt: skip


def test_reverse_charge_settlements_and_exceptions() -> None:
    lines = [
        # Reverse charge: output and input VAT on the same purchase; the base is a purchase.
        line("1", "5000", "EXPENSE", "", "RC", "REVERSE_CHARGE", "0.19", "1000"),
        line("1", "2120", "LIABILITY", "OUTPUT", "RC", "REVERSE_CHARGE", "0.19", "-190"),
        line("1", "1220", "ASSET", "INPUT", "RC", "REVERSE_CHARGE", "0.19", "190"),
        # VAT on a zero-rated code.
        line("2", "4000", "INCOME", "", "Z0", "ZERO", "0", "-500"),
        line("2", "2120", "LIABILITY", "OUTPUT", "Z0", "ZERO", "0", "-5"),
        # VAT without a taxable amount, and a taxable amount without VAT.
        line("3", "2120", "LIABILITY", "OUTPUT", "S19", "STANDARD", "0.19", "-19"),
        line("4", "4000", "INCOME", "", "S19", "STANDARD", "0.19", "-200"),
        # A VAT payment: shown apart, never part of the period's VAT; its bank side is ignored.
        line("5", "2120", "LIABILITY", "OUTPUT", "SETTLE", "SETTLEMENT", None, "100"),
        line("5", "1300", "ASSET", "", "SETTLE", "SETTLEMENT", None, "-100"),
    ]
    found = compute(lines)
    codes = {c["code"]: c for c in found["codes"]}
    assert (codes["RC"]["purchase_base"], codes["RC"]["purchase_vat"]) == ("1000.00", "190.00")
    assert (codes["RC"]["sales_base"], codes["RC"]["sales_vat"]) == ("0.00", "190.00")
    assert found["settlements"] == "100.00"
    assert [a["settled"] for a in found["accounts"] if a["code"] == "2120"] == ["100.00"]
    kinds = sorted(e["kind"] for e in found["exceptions"])
    assert [k for k in kinds if k != "UNSUPPORTED"] == [
        "BASE_WITHOUT_VAT", "RATE_MISMATCH", "VAT_ON_NO_VAT_CODE", "VAT_WITHOUT_BASE"]  # fmt: skip
    # The old RC code does not say which reverse charge applies: each kind of its lines is
    # unsupported, once per entry, and feeds no box; output VAT on a zero-rated code has no box.
    unsupported = [e["detail"] for e in found["exceptions"] if e["kind"] == "UNSUPPORTED"]
    assert [d[:9] for d in unsupported] == ["GJ-1 (RC)"] * 3 + ["GJ-2 (Z0)"]
    assert all("The old code RC" in d for d in unsupported[:3])
    assert all(not ln["boxes"] for ln in found["lines"] if ln["code"] == "RC")
    # Totals: output 190 + 5 + 19 = 214; input 190; net 24 payable.
    assert (found["totals"]["sales_vat"], found["totals"]["purchase_vat"],
            found["totals"]["net"], found["totals"]["direction"]) == (
        "214.00", "190.00", "24.00", "PAYABLE")  # fmt: skip
    # Exceptions do not change the figures' fingerprint; figures do.
    again = compute(lines)
    assert digest(figures(again)) == digest(figures(found))
    assert digest(figures(compute(lines[:-2]))) != digest(figures(found))


def test_refund_and_nil() -> None:
    refund = compute([
        line("1", "5000", "EXPENSE", "", "S19", "STANDARD", "0.19", "100"),
        line("1", "1220", "ASSET", "INPUT", "S19", "STANDARD", "0.19", "19"),
    ])  # fmt: skip
    assert (refund["totals"]["net"], refund["totals"]["direction"]) == ("-19.00", "REFUNDABLE")
    assert refund["exceptions"] == []
    assert compute([])["totals"]["direction"] == "NIL"
