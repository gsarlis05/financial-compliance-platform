"""The validation package (M6F-8, #153): the engine agrees with the independent model on every
scenario, every line, every month, and the committed results are up to date."""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from fcp.devtools.validation import harness
from fcp.modules.projections.engine import VALIDATION_STATUS, EngineInput


def test_the_engine_agrees_with_the_independent_model() -> None:
    results = harness.run_all()
    assert [r.slug for r in results] == [
        "s1-base",
        "s2-losses",
        "s3-negative-cash",
        "s4-loans",
        "s5-changing-revenue",
        "s6-unexpected-expenses",
    ]
    for r in results:
        assert not r.discrepancies, (r.slug, r.discrepancies[:5])
        assert not r.loan_discrepancies, (r.slug, r.loan_discrepancies[:5])
        assert all(ok for *_, ok in r.reconciliation), r.slug
        assert all(r.invariants.values()), (r.slug, r.invariants)
        assert r.payments_engine == r.payments_model, r.slug
        assert r.compared == 24 * 62
    files = harness.outputs(results)
    stale = [name for name, text in files.items()
             if (harness.ROOT / "results" / name).read_text() != text]  # fmt: skip
    assert not stale, f"Run python -m fcp.devtools.validation and commit: {stale}"


def test_the_engine_is_not_marked_as_validated() -> None:
    # Owner decision D9: only a signed professional review may change this.
    assert VALIDATION_STATUS == "PENDING_PROFESSIONAL_REVIEW"
    sign_off = (harness.ROOT / "05-reviewer-sign-off.md").read_text()
    assert "Not yet completed" in sign_off


def test_a_two_cent_difference_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    # A negative control: the engine is given rent of 2 cents more in one month; the comparison
    # must report it (and nothing passes by tolerance alone).
    real = harness.engine_input

    def nudged(raw: dict[str, Any]) -> EngineInput:
        inp = real(raw)
        rent = inp.drivers[("opex", "OPEX.RENT")]
        rent[date(2027, 5, 1)] += Decimal("0.02")
        return inp

    monkeypatch.setattr(harness, "engine_input", nudged)
    found = harness.run_scenario(harness.ROOT / "scenarios" / "s1-base.json", harness.independent())
    assert not found.passed
    assert ("PL.OPEX.RENT", "2027-05") in {(d.key, d.month) for d in found.discrepancies}
