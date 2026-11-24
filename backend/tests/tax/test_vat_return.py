"""The 13-box return from line contributions (V1-2c, #214): the acceptance fixtures of the owner's
specification (brief 25 §5), rounding, the cross-field checks and the line checks, on hand-made
lines. Rates 19% and full recovery unless stated."""

from decimal import Decimal
from typing import Any

from fcp.modules.tax.report import Line, compute

CODES = {  # code: (treatment, rate, category)
    "S19": ("STANDARD", "0.19", "DOMESTIC"),
    "Z0": ("ZERO", "0", "ZERO_RATED"),
    "EX": ("EXEMPT", None, "EXEMPT"),
    "EUGS": ("ZERO", "0", "EU_GOODS_SUPPLY"),
    "EUSS": ("OUT_OF_SCOPE", None, "EU_SERVICES_SUPPLY"),
    "OSD": ("OUT_OF_SCOPE", None, "OUTSIDE_SCOPE_DEDUCTIBLE"),
    "EUGA19": ("REVERSE_CHARGE", "0.19", "EU_GOODS_ACQUISITION"),
    "RCEU19": ("REVERSE_CHARGE", "0.19", "RC_EU_SERVICES"),
    "RCNEU19": ("REVERSE_CHARGE", "0.19", "RC_NON_EU_SERVICES"),
    "RCDOM19": ("REVERSE_CHARGE", "0.19", "RC_DOMESTIC"),
    "IMP19": ("STANDARD", "0.19", "IMPORT"),
    "OUT": ("OUT_OF_SCOPE", None, "NON_SUPPLY"),
}
TYPES = {"4000": "INCOME", "5000": "EXPENSE", "6100": "EXPENSE", "2120": "LIABILITY",
         "1220": "ASSET"}  # fmt: skip
ROLES = {"2120": "OUTPUT", "1220": "INPUT"}
PARTY = {"DE": "DE123456789", "US": "", "CY": "CY10000000X", "FR": "FR12345678901"}


def ln(entry: str, account: str, code: str, net_debit: str, country: str = "",
       **extra: Any) -> Line:  # fmt: skip
    treatment, rate, category = CODES[code]
    return Line(f"{entry}-{account}", entry, f"GJ-{entry}", extra.pop("day", "2026-01-10"),
                "test", account, f"Account {account}", TYPES[account], ROLES.get(account, ""),
                code, treatment, Decimal(rate) if rate is not None else None, False,
                Decimal(net_debit), "Party (Demo)" if country else "", "", category=category,
                country=country, vat_no=extra.pop("vat_no", PARTY.get(country, "")),
                **extra)  # fmt: skip


def local_sale(e: str = "1", sign: int = 1) -> list[Line]:
    return [ln(e, "4000", "S19", str(-1000 * sign)), ln(e, "2120", "S19", str(-190 * sign))]


def local_purchase(e: str = "2") -> list[Line]:
    return [ln(e, "5000", "S19", "500"), ln(e, "1220", "S19", "95")]


def eu_goods(e: str = "3") -> list[Line]:
    return [ln(e, "5000", "EUGA19", "1000", "DE"), ln(e, "2120", "EUGA19", "-190", "DE"),
            ln(e, "1220", "EUGA19", "190", "DE")]  # fmt: skip


def eu_service(e: str = "4", recovered: str = "19", **detail: Any) -> list[Line]:
    return [ln(e, "6100", "RCEU19", "100", "FR"), ln(e, "2120", "RCEU19", "-19", "FR"),
            ln(e, "1220", "RCEU19", recovered, "FR", **detail)]  # fmt: skip


def non_eu_service(e: str = "5") -> list[Line]:
    return [ln(e, "6100", "RCNEU19", "100", "US"), ln(e, "2120", "RCNEU19", "-19", "US"),
            ln(e, "1220", "RCNEU19", "19", "US")]  # fmt: skip


def boxes(found: dict[str, Any]) -> dict[str, str]:
    return {b["box"]: b["amount"] for b in found["return"]["boxes"] if Decimal(b["amount"])}


def test_each_acceptance_fixture() -> None:
    assert boxes(compute(local_sale())) == {"1": "190.00", "3": "190.00", "5": "190.00",
                                            "6": "1000.00"}  # fmt: skip
    assert boxes(compute(local_purchase())) == {"4": "95.00", "5": "-95.00", "7": "500.00"}
    assert boxes(compute(eu_goods())) == {"2": "190.00", "3": "190.00", "4": "190.00",
                                          "7": "1000.00", "11A": "1000.00"}  # fmt: skip
    assert boxes(compute(eu_service())) == {
        "1": "19.00", "3": "19.00", "4": "19.00", "6": "100.00", "7": "100.00", "11B": "100.00",
    }  # fmt: skip
    assert boxes(compute(non_eu_service())) == {"1": "19.00", "3": "19.00", "4": "19.00",
                                                "6": "100.00", "7": "100.00"}  # fmt: skip
    # Half of the EU service's VAT is recoverable: Box 4 takes only that half, and the rate
    # check counts the other half as non-recoverable, not as an error.
    half = compute(eu_service(recovered="9.50", recovery_percent=Decimal(50),
                              blocked=Decimal("9.50")))  # fmt: skip
    assert boxes(half) == {"1": "19.00", "3": "19.00", "4": "9.50", "5": "9.50", "6": "100.00",
                           "7": "100.00", "11B": "100.00"}  # fmt: skip
    assert half["exceptions"] == []
    # A credit note on the local sale takes it back out.
    credit = compute(local_sale("9", sign=-1))
    assert boxes(credit) == {"1": "-190.00", "3": "-190.00", "5": "-190.00", "6": "-1000.00"}


def test_the_five_together() -> None:
    found = compute(local_sale() + local_purchase() + eu_goods() + eu_service()
                    + non_eu_service())  # fmt: skip
    assert boxes(found) == {"1": "228.00", "2": "190.00", "3": "418.00", "4": "323.00",
                            "5": "95.00", "6": "1200.00", "7": "1700.00", "11A": "1000.00",
                            "11B": "100.00"}  # fmt: skip
    assert {b["box"] for b in found["return"]["boxes"]} == {
        "1", "2", "3", "4", "5", "6", "7", "8A", "8B", "9", "10", "11A", "11B"}  # fmt: skip
    assert found["return"]["direction"] == "PAYABLE"
    assert found["exceptions"] == []
    assert all(c["ok"] for c in found["return"]["checks"])
    # Every line says which boxes it feeds and why; the boxes add up from the lines.
    for box in ("1", "4", "6", "7"):
        total = sum((Decimal(x["boxes"].get(box, "0")) for x in found["lines"]), Decimal(0))
        assert money(total) == boxes(found)[box]
    acquisition = next(
        x for x in found["lines"] if x["code"] == "EUGA19" and x["kind"] == "PURCHASE"
    )
    assert acquisition["boxes"] == {"7": "1000.00", "11A": "1000.00"}
    assert acquisition["rule"] == "spec §2: qualifying EU goods acquisition"
    assert (acquisition["mapping"], acquisition["country"]) == ("MAPPED", "DE")
    # The same lines give the same return.
    assert compute(local_sale() + local_purchase() + eu_goods() + eu_service()
                   + non_eu_service())["return"] == found["return"]  # fmt: skip


def money(value: Decimal) -> str:
    return f"{value:.2f}"


def test_outputs_rounding_and_the_value_checks() -> None:
    found = compute([
        ln("1", "4000", "EUGS", "-2000.50", "DE"),      # goods to an EU business: 6, 8A
        ln("2", "4000", "EUSS", "-300.49", "FR"),       # services to an EU business: 6, 8B
        ln("3", "4000", "Z0", "-400"),                  # zero-rated: 6, 9
        ln("4", "4000", "OSD", "-50"),                  # outside scope, deductible: 6, 10
        ln("5", "6100", "OUT", "70"),                   # not a supply: excluded, no exception
    ])  # fmt: skip
    rows = {b["box"]: b for b in found["return"]["boxes"]}
    # Value boxes to the nearest euro (half up), with the rounding shown; VAT boxes to the cent.
    assert (rows["6"]["amount"], rows["6"]["exact"], rows["6"]["rounding"]) == (
        "2751.00",
        "2750.99",
        "0.01",
    )
    assert (rows["8A"]["amount"], rows["8A"]["rounding"]) == ("2001.00", "0.50")
    assert (rows["8B"]["amount"], rows["8B"]["rounding"]) == ("300.00", "-0.49")
    assert (rows["9"]["amount"], rows["10"]["amount"]) == ("400.00", "50.00")
    assert rows["5"]["amount"] == "0.00"
    assert found["return"]["direction"] == "NIL"
    excluded = next(x for x in found["lines"] if x["code"] == "OUT")
    assert (excluded["mapping"], excluded["boxes"]) == ("EXCLUDED", {})
    assert found["exceptions"] == []
    # A credit note can leave Box 6 below the boxes it contains: the check says so.
    credit = compute([ln("1", "4000", "S19", "500"), ln("1", "2120", "S19", "95"),
                      ln("2", "4000", "Z0", "-100")])  # fmt: skip
    failed = [c for c in credit["return"]["checks"] if not c["ok"]]
    assert [c["check"] for c in failed] == ["BOX_6"]
    assert [e["kind"] for e in credit["exceptions"]] == ["BOX_CHECK"]
    assert "A credit note or correction can explain" in credit["exceptions"][0]["detail"]


def test_party_data_tax_points_and_unsupported_lines() -> None:
    found = compute([
        ln("1", "4000", "EUGS", "-100", "DE", vat_no=""),   # no VAT number
        ln("2", "4000", "EUSS", "-100", "CY"),              # not another member state
        ln("3", "4000", "EUSS", "-100"),                    # no country
        ln("4", "6100", "RCNEU19", "100", "DE"), ln("4", "2120", "RCNEU19", "-19", "DE"),
        ln("4", "1220", "RCNEU19", "19", "DE"),             # non-EU code, EU supplier
        ln("5", "5000", "RCDOM19", "100", "FR"), ln("5", "2120", "RCDOM19", "-19", "FR"),
        ln("5", "1220", "RCDOM19", "19", "FR"),             # domestic code, foreign party
        ln("6", "4000", "S19", "-100", tax_point="2026-04-02"),
        ln("6", "2120", "S19", "-19", tax_point="2026-04-02"),
        ln("7", "6100", "EX", "60"),                        # exempt: not mapped
        ln("8", "5000", "IMP19", "1000"), ln("8", "1220", "IMP19", "190"),  # import VAT only
    ], "2026-01-01", "2026-03-31")  # fmt: skip
    by_kind: dict[str, list[str]] = {}
    for e in found["exceptions"]:
        by_kind.setdefault(e["kind"], []).append(e["entry"])
    assert by_kind == {
        "PARTY_DATA": ["GJ-1", "GJ-2", "GJ-3", "GJ-4", "GJ-5"],
        "TAX_POINT_OUTSIDE_PERIOD": ["GJ-6", "GJ-6"],
        "UNSUPPORTED": ["GJ-7", "GJ-8"],
    }
    details = " ".join(e["detail"] for e in found["exceptions"])
    assert "needs a country and a VAT number" in details
    assert "a party in CY, which is not another EU member state" in details
    assert "a non-EU reverse charge with a supplier in DE" in details
    assert "The value of imports is not mapped" in details
    # Import VAT is still deductible: Box 4 takes it; its value feeds no box.
    assert boxes(found)["4"] == "228.00"  # 19 + 19 + 190
    imported = [x for x in found["lines"] if x["code"] == "IMP19"]
    assert [(x["kind"], x["mapping"]) for x in imported] == [
        ("PURCHASE", "UNSUPPORTED"), ("PURCHASE_VAT", "MAPPED")]  # fmt: skip
