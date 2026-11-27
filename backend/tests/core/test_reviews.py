"""The owner's check of the rules and the engine, recorded as data (brief 27, #254)."""

from datetime import date
from typing import Any

import pytest

from fcp.core import reviews

from ..ledger.conftest import books

__all__ = ["books"]


def test_the_owners_check_is_recorded_and_never_called_a_professional_verification() -> None:
    for subject in (reviews.vat_codes("CY"), reviews.vat_box_rules("CY"),
                    reviews.corporate_tax("CY"), reviews.ENGINE):  # fmt: skip
        found = reviews.review(subject)
        assert (found.status, found.on, found.by) == ("OWNER_CHECKED", date(2026, 11, 27),
                                                      "The owner")  # fmt: skip
        assert "not a professional verification" in found.label()
    assert reviews.engine_status() == "OWNER_CHECKED"
    assert "not independently certified" in reviews.engine_note()
    # The record is append-only: the earlier, pending entries are kept as history.
    assert [r.status for r in reviews.history() if r.subject == reviews.ENGINE] == [
        "PENDING", "OWNER_CHECKED"]  # fmt: skip


def test_an_unknown_subject_is_pending() -> None:
    found = reviews.review("GR:VAT_CODES")
    assert found.pending
    assert found.label() == "Pending verification."


def test_a_check_needs_a_date_and_who_made_it() -> None:
    with pytest.raises(ValueError, match="needs a date"):
        reviews._parse({"subject": "X", "status": "OWNER_CHECKED", "on": None, "by": ""})
    with pytest.raises(ValueError, match="unknown review status"):
        reviews._parse({"subject": "X", "status": "DONE"})


@pytest.mark.django_db
def test_the_screens_read_the_status(books: dict[str, Any]) -> None:
    client, base = books["client"], books["base"]
    found = {r["subject"]: r for r in client.get(f"{base}/reviews").json()}
    assert found["PROJECTION_ENGINE"]["label"] == (
        "Checked by the owner on 27/11/2026 (not a professional verification).")  # fmt: skip
    codes = client.get(f"{base}/vat-codes").json()
    assert {c["review_status"] for c in codes} == {"OWNER_CHECKED"}
    assert not any(c["verified"] for c in codes)  # no professional has verified them
    rules = client.get(f"{base}/tax-rules").json()
    assert rules[0]["review_status"] == "OWNER_CHECKED"
    assert rules[0]["review_note"].startswith("Checked by the owner on 27/11/2026")
