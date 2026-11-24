"""Draft → Reviewed → Finalised → Filed (V1-2d, #215): manual adjustments with approval, sending a
reviewed report back to draft, the inclusion of each line in one return, the differences that
later entries make, and amendments. On the golden quarter of ``test_vat_reports`` (Box 4 = 76,
Box 5 = 140 payable)."""

from collections.abc import Callable
from typing import Any
from uuid import UUID

import pytest
from django.db import DatabaseError, IntegrityError, transaction

from fcp.core.db.rls import set_context
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.tax.models import VatAdjustment, VatInclusion, VatReport

from ..ledger.conftest import join
from .test_vat_reports import Q1, S19, act, books, generate, post, scheme, v

pytestmark = pytest.mark.django_db
Make = Callable[..., Any]
__all__ = ["books", "v"]
PROOF = "Adviser's letter of 3 April 2026, in Documents"


def boxes(report: dict[str, Any], key: str = "amount") -> dict[str, str]:
    return {b["box"]: b[key] for b in report["final_return"]["boxes"]}


def adjust(v: dict[str, Any], report_id: str, client: Any = None, **body: Any) -> Any:
    payload = {"box": "4", "amount": "10.00", "reason": "Input VAT on a March invoice received "
               "late", "evidence": PROOF, **body}  # fmt: skip
    return act(v, report_id, "adjustments", client, **payload)


def decide(v: dict[str, Any], report_id: str, adjustment_id: str, what: str,
           client: Any = None) -> Any:  # fmt: skip
    return act(v, report_id, f"adjustments/{adjustment_id}/{what}", client)


@pytest.fixture
def boss(v: dict[str, Any], make_user: Make, api_client: Make) -> Any:
    return join(v["client"], v["ws"]["slug"], make_user("fm@example.test"), api_client,
                "finance_manager")  # fmt: skip


def test_adjustments_need_a_reason_evidence_and_approval(v: dict[str, Any], boss: Any) -> None:
    scheme(v, 3, Q1)
    report = generate(v).json()
    rid = report["id"]
    assert adjust(v, rid, box="3").status_code == 422  # follows from Boxes 1 and 2
    assert adjust(v, rid, amount="0").status_code == 422
    assert adjust(v, rid, amount="1.005").status_code == 422
    assert adjust(v, rid, evidence="").status_code == 422
    made = adjust(v, rid)
    assert made.status_code == 201, made.content
    adjustment = made.json()
    assert (adjustment["status"], adjustment["box"], adjustment["amount"]) == (
        "PROPOSED",
        "4",
        "10.00",
    )
    # A proposed adjustment does not count, and holds the review back.
    detail = v["client"].get(f"{v['base']}/vat-reports/{rid}").json()
    assert boxes(detail)["4"] == "76.00"
    assert "Approve or reject every proposed adjustment first." in detail["blockers"]
    assert act(v, rid, "review", boss).status_code == 409
    # Its author cannot approve it; someone else can.
    assert decide(v, rid, adjustment["id"], "approve").status_code == 403
    approved = decide(v, rid, adjustment["id"], "approve", boss)
    assert approved.status_code == 200, approved.content
    assert (approved.json()["status"], approved.json()["self_approved"]) == ("APPROVED", False)
    assert decide(v, rid, adjustment["id"], "reject", boss).status_code == 409  # decided once
    # A second one, withdrawn by its author.
    second = adjust(v, rid, box="6", amount="-25.00").json()
    assert decide(v, rid, second["id"], "reject").json()["status"] == "REJECTED"

    detail = v["client"].get(f"{v['base']}/vat-reports/{rid}").json()
    assert detail["final_return"]["adjusted"] is True
    assert (boxes(detail, "original")["4"], boxes(detail, "adjustment")["4"],
            boxes(detail)["4"]) == ("76.00", "10.00", "86.00")  # fmt: skip
    assert (boxes(detail)["5"], boxes(detail)["6"]) == ("130.00", "1700.00")
    assert detail["snapshot"]["return"]["boxes"][3]["amount"] == "76.00"  # the books unchanged
    assert [a["status"] for a in detail["adjustments"]] == ["APPROVED", "REJECTED"]

    # Once reviewed, adjustments are closed, also in the database.
    assert act(v, rid, "review", boss).status_code == 200
    assert adjust(v, rid).status_code == 409
    set_context(tenant_id=UUID(v["ws"]["id"]))
    with pytest.raises(DatabaseError, match="while the VAT report is a draft"), \
            transaction.atomic():  # fmt: skip
        VatAdjustment.objects.filter(id=adjustment["id"]).update(amount="11.00")
    with pytest.raises(DatabaseError, match="adjustments are kept"), transaction.atomic():
        VatAdjustment.objects.filter(id=second["id"]).delete()
    finalised = act(v, rid, "finalise", boss).json()
    assert boxes(finalised)["5"] == "130.00"
    set_context(tenant_id=UUID(v["ws"]["id"]))
    events = [e.action for e in AuditEvent.objects.filter(action__startswith="tax.vat.adj")]
    assert events == ["tax.vat.adjustment_proposed", "tax.vat.adjustment_approved",
                      "tax.vat.adjustment_proposed", "tax.vat.adjustment_rejected"]  # fmt: skip


def test_back_to_draft_inclusions_and_the_database(v: dict[str, Any], boss: Any) -> None:
    scheme(v, 3, Q1)
    rid = generate(v).json()["id"]
    assert act(v, rid, "review", boss).status_code == 200
    assert act(v, rid, "reopen", boss, note=" ").status_code == 422
    back = act(v, rid, "reopen", boss, note="Box 7 looks low: check the March purchases")
    assert back.status_code == 200, back.content
    body = back.json()
    assert (body["status"], body["reviewed_by_id"], body["review_note"]) == (
        "DRAFT",
        None,
        "Box 7 looks low: check the March purchases",
    )
    assert act(v, rid, "regenerate").status_code == 200  # a draft again
    assert act(v, rid, "review", boss).status_code == 200
    final = act(v, rid, "finalise", boss).json()
    assert final["status"] == "FINALISED"

    set_context(tenant_id=UUID(v["ws"]["id"]))
    included = VatInclusion.objects.filter(report_id=rid, active=True)
    lines = {ln["line_id"] for ln in final["snapshot"]["lines"]}
    assert {str(i.line_id) for i in included} == lines
    assert len(lines) == 10
    # A line is in one return only; inclusions are kept.
    one = included.first()
    assert one is not None
    other = VatReport.objects.get(id=rid)
    with pytest.raises(IntegrityError), transaction.atomic():
        VatInclusion.objects.create(tenant_id=one.tenant_id, report=other, line_id=one.line_id,
                                    entry_id=one.entry_id)  # fmt: skip
    with pytest.raises(DatabaseError, match="is kept"), transaction.atomic():
        included.delete()
    with pytest.raises(DatabaseError, match="only ends when its return is superseded"), \
            transaction.atomic():  # fmt: skip
        included.update(active=False)
    with pytest.raises(DatabaseError, match="never change"), transaction.atomic():
        VatReport.objects.filter(id=rid).update(snapshot={"forged": True})


def test_later_entries_and_an_amendment(v: dict[str, Any], boss: Any) -> None:
    scheme(v, 3, Q1)
    rid = generate(v).json()["id"]
    adjustment = adjust(v, rid).json()
    decide(v, rid, adjustment["id"], "approve", boss)
    act(v, rid, "review", boss)
    act(v, rid, "finalise", boss)
    filed = act(v, rid, "filed", boss, filed_on="2026-05-05", reference="TAXIS-9",
                evidence="Portal acknowledgement in Documents")  # fmt: skip
    assert filed.status_code == 200, filed.content
    assert filed.json()["differences"]["changed"] is False

    # A sale posted into the quarter afterwards: shown as a difference, never moved anywhere.
    post(v, "2026-03-25", ("1300", "119", "0", None), ("4000", "0", "100", S19),
         ("2120", "0", "19", S19))  # fmt: skip
    after = v["client"].get(f"{v['base']}/vat-reports/{rid}").json()
    assert after["status"] == "FILED"
    diff = after["differences"]
    assert (diff["changed"], len(diff["added"]), diff["removed"]) == (True, 2, [])
    assert diff["boxes"] == {"1": "19.00", "3": "19.00", "5": "19.00", "6": "100.00"}
    assert boxes(after)["5"] == "130.00"  # the filed return as it was

    # The correction is a new version: an amendment of the filed return.
    v2 = act(v, rid, "new-version").json()
    assert (v2["version"], v2["previous"]["status"], v2["previous"]["filing_reference"]) == (
        2,
        "FILED",
        "TAXIS-9",
    )
    # The approved adjustment is carried over as a proposal, to be decided again.
    assert [(a["box"], a["amount"], a["status"]) for a in v2["adjustments"]] == [
        ("4", "10.00", "PROPOSED")]  # fmt: skip
    assert v2["previous"]["boxes"] == {"1": "19.00", "3": "19.00", "4": "-10.00", "5": "29.00",
                                       "6": "100.00"}  # fmt: skip
    decide(v, v2["id"], v2["adjustments"][0]["id"], "approve", boss)
    act(v, v2["id"], "review", boss)
    done = act(v, v2["id"], "finalise", boss).json()
    assert done["previous"]["boxes"] == {"1": "19.00", "3": "19.00", "5": "19.00", "6": "100.00"}
    assert boxes(done)["5"] == "149.00"
    first = v["client"].get(f"{v['base']}/vat-reports/{rid}").json()
    assert first["status"] == "SUPERSEDED"
    set_context(tenant_id=UUID(v["ws"]["id"]))
    assert not VatInclusion.objects.filter(report_id=rid, active=True).exists()
    assert VatInclusion.objects.filter(report_id=v2["id"], active=True).count() == 12


def test_one_person_approves_their_own(v: dict[str, Any]) -> None:
    scheme(v, 3, Q1)
    rid = generate(v).json()["id"]
    slug = v["ws"]["slug"]
    assert v["client"].put_json(f"/api/w/{slug}/one-person", {"enabled": True}).status_code == 200
    made = adjust(v, rid).json()
    approved = decide(v, rid, made["id"], "approve").json()
    assert (approved["status"], approved["self_approved"]) == ("APPROVED", True)
    assert act(v, rid, "review").json()["self_approved"] is True
    assert act(v, rid, "finalise").json()["status"] == "FINALISED"
