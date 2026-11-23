"""Imports in the VAT return (V1-2f, #217): the customs declaration behind each import VAT claim,
with its reference, date, taxable value, import VAT and evidence document; checks against the
claim; no import VAT claimed twice; the imports schedule.

Uses the real document store and antivirus (``make services``), as the documents tests do.

Q1 2026: goods imported for 1,000, import VAT 190 at 19% (IMP19), paid to customs.
"""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.tax.models import VatImport

from ..ledger.conftest import books
from ..ledger.test_dimensions import commit_point

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books"]

IMP19 = "CY:IMP19:open"
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


@pytest.fixture(autouse=True)
def bucket(document_bucket: None) -> None:
    del document_bucket


def post(b: dict[str, Any], day: str, *lines: tuple[str, str, str, str | None]) -> str:
    acc = b["accounts"]
    body = {"accounting_date": day, "description": f"Import {day}", "lines": [
        {"account_id": acc[a]["id"], "debit": dr, "credit": cr,
         **({"vat_code_id": code} if code else {})} for a, dr, cr, code in lines]}  # fmt: skip
    made = b["client"].post_json(f"{b['base']}/journal-entries", body)
    assert made.status_code == 201, made.content
    posted = b["client"].post_json(f"{b['base']}/journal-entries/{made.json()['id']}/post", {})
    assert posted.status_code == 200, posted.content
    commit_point()
    return str(made.json()["id"])


def attach(b: dict[str, Any], entry_id: str, name: str = "customs-declaration.pdf",
           data: bytes = PDF) -> str:  # fmt: skip
    made = b["client"].post(f"{b['base']}/documents",
                            {"file": SimpleUploadedFile(name, data), "entry_id": entry_id},
                            headers=b["client"]._csrf())  # fmt: skip
    assert made.status_code == 201, made.content
    return str(made.json()["id"])


def record(b: dict[str, Any], **body: Any) -> Any:
    return b["client"].post_json(f"{b['base']}/vat-imports", body)


@pytest.fixture
def imp(books: dict[str, Any]) -> dict[str, Any]:
    c, base = books["client"], books["base"]
    assert c.put_json(f"{base}/ledger-settings", {"approval_policy": "NONE"}).status_code == 200
    books["entry"] = post(books, "2026-02-10", ("5000", "1000", "0", IMP19),
                          ("1220", "190", "0", IMP19), ("1300", "0", "1190", None))  # fmt: skip
    books["document"] = attach(books, books["entry"])
    made = c.post_json(f"{base}/vat-period-schemes", {"months": 3, "effective_from": "2026-01-01"})
    assert made.status_code == 201, made.content
    return books


def good(b: dict[str, Any], **change: Any) -> dict[str, Any]:
    return {"entry_id": b["entry"], "customs_reference": "26CY000000000012A1",
            "customs_date": "2026-02-09", "customs_value": "1000.00", "import_vat": "190.00",
            "document_id": b["document"], **change}  # fmt: skip


def generate(b: dict[str, Any]) -> dict[str, Any]:
    made = b["client"].post_json(f"{b['base']}/vat-reports", {"period_start": "2026-01-01"})
    assert made.status_code == 201, made.content
    return dict(made.json())


def test_a_claim_needs_its_customs_record(imp: dict[str, Any]) -> None:
    listed = imp["client"].get(f"{imp['base']}/vat-imports",
                               query_params={"date_from": "2026-01-01",
                                             "date_to": "2026-03-31"}).json()  # fmt: skip
    assert listed["records"] == []
    assert [(m["entry_id"], m["claimed_vat"]) for m in listed["missing"]] == [
        (imp["entry"], "190.00")]  # fmt: skip
    report = generate(imp)
    kinds = sorted(e["kind"] for e in report["snapshot"]["exceptions"])
    # The import VAT is in Box 4; the value of imports is not mapped by the rules (V1-2c).
    assert kinds == ["IMPORT_WITHOUT_RECORD", "UNSUPPORTED"]
    assert {b["box"]: b["amount"] for b in report["final_return"]["boxes"]}["4"] == "190.00"


def test_recording_checking_and_no_double_claim(imp: dict[str, Any]) -> None:
    # Validation: a real import entry, a reference, positive amounts, evidence on the entry.
    other = post(imp, "2026-02-11", ("6100", "50", "0", None), ("1300", "0", "50", None))
    assert record(imp, **good(imp, entry_id=other)).status_code == 422
    assert record(imp, **good(imp, customs_reference="")).status_code == 422
    assert record(imp, **good(imp, customs_value="0")).status_code == 422
    loose = attach(imp, other, name="other.pdf", data=PDF + b"%other\n")
    refused = record(imp, **good(imp, document_id=loose))
    assert refused.status_code == 422
    assert "Attach the document to the entry first" in refused.json()["detail"]

    made = record(imp, **good(imp, import_vat="185.00"))
    assert made.status_code == 201, made.content
    body = made.json()
    assert (body["document_name"], body["voided_at"]) == ("customs-declaration.pdf", None)
    # The same declaration or the same entry cannot be recorded twice.
    assert record(imp, **good(imp)).status_code == 409
    assert record(imp, **good(imp, customs_reference="OTHER-1")).status_code == 409

    # The record disagrees with the claim (185 declared, 190 claimed): flagged.
    report = generate(imp)
    found = {e["kind"]: e["detail"] for e in report["snapshot"]["exceptions"]}
    assert "IMPORT_WITHOUT_RECORD" not in found
    assert "claims import VAT of 190.00, the customs declaration 26CY000000000012A1 shows " \
           "185.00" in found["IMPORT_VAT_MISMATCH"]  # fmt: skip
    assert "gives 190.00, not the 185.00 declared" in found["IMPORT_VALUE_MISMATCH"]
    row = report["schedules"]["imports"]["rows"][0]
    assert (row["customs_reference"], row["customs_value"], row["input_vat"],
            row["document_name"]) == ("26CY000000000012A1", "1000.00", "190.00",
                                      "customs-declaration.pdf")  # fmt: skip

    # Voided and recorded again, correctly; the report must be regenerated to see it.
    url = f"{imp['base']}/vat-imports/{body['id']}/void"
    assert imp["client"].post_json(url, {"reason": " "}).status_code == 422
    assert imp["client"].post_json(url, {"reason": "Wrong VAT typed"}).status_code == 200
    assert imp["client"].post_json(url, {"reason": "Again"}).status_code == 409
    assert record(imp, **good(imp)).status_code == 201
    stale = imp["client"].get(f"{imp['base']}/vat-reports/{report['id']}").json()
    assert any("Regenerate" in b for b in stale["blockers"])
    again = imp["client"].post_json(f"{imp['base']}/vat-reports/{report['id']}/regenerate",
                                    {}).json()  # fmt: skip
    assert [e["kind"] for e in again["snapshot"]["exceptions"]] == ["UNSUPPORTED"]

    set_context(tenant_id=UUID(imp["ws"]["id"]))
    actions = [e.action for e in AuditEvent.objects.filter(action__startswith="tax.vat.import")]
    assert actions == ["tax.vat.import_recorded", "tax.vat.import_voided",
                       "tax.vat.import_recorded"]  # fmt: skip


def test_the_database_keeps_records(imp: dict[str, Any]) -> None:
    made = record(imp, **good(imp)).json()
    slug = imp["ws"]["slug"]
    assert imp["client"].put_json(f"/api/w/{slug}/one-person", {"enabled": True}).status_code == 200
    report = generate(imp)
    for step in ("review", "finalise"):
        done = imp["client"].post_json(f"{imp['base']}/vat-reports/{report['id']}/{step}", {})
        assert done.status_code == 200, done.content
    # In a finalised return now: no voiding, in the service or the database.
    url = f"{imp['base']}/vat-imports/{made['id']}/void"
    assert imp["client"].post_json(url, {"reason": "Late change"}).status_code == 409
    set_context(tenant_id=UUID(imp["ws"]["id"]))
    rows = VatImport.objects.filter(id=made["id"])
    with pytest.raises(DatabaseError, match="in a finalised return"), transaction.atomic():
        rows.update(voided_at="2026-04-02T00:00Z", voided_by=imp["owner"], void_reason="x")
    with pytest.raises(DatabaseError, match="never changed"), transaction.atomic():
        rows.update(import_vat="1.00")
    with pytest.raises(DatabaseError, match="are kept"), transaction.atomic():
        rows.delete()
