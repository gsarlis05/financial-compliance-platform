"""The example files, end to end (R-5, #248; AC-R1, AC-R2): a full set imported through the API
gives a trial balance equal to the source to the cent, with nothing posted until approved; the
accountant's and the package versions give the same opening; each bank preset's example statement
is recognised and imported without setting columns by hand. Every file is synthetic."""

import csv
import io
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from fcp.modules.ledger.models import JournalEntry
from fcp.modules.reporting.models import FactComparative

from ..banking.test_banking import bank, upload
from ..ledger.conftest import books
from ..ledger.test_entries import act
from .test_imports import send

__all__ = ["bank", "books"]
pytestmark = pytest.mark.django_db
EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "books"


def example(name: str) -> tuple[str, bytes]:
    return name, (EXAMPLES / name).read_bytes()


def source_balances() -> dict[str, Decimal]:
    rows = csv.DictReader(io.StringIO((EXAMPLES / "opening-balances.csv").read_text("utf-8")))
    return {r["Account code"]: Decimal(r["Debit"] or "0") - Decimal(r["Credit"] or "0")
            for r in rows}  # fmt: skip


def setup(b: dict[str, Any]) -> None:
    for kind, name in (("chart", "chart.csv"), ("counterparties", "counterparties.csv")):
        done = send(b, kind, {"file": example(name)}, commit=True)
        assert (done["committed"], done["problems"]) == (True, []), (kind, done["problems"])


def nets(entry_id: str) -> dict[str, Decimal]:
    found: dict[str, Decimal] = defaultdict(Decimal)
    for ln in JournalEntry.objects.get(id=entry_id).lines.select_related("account"):
        found[ln.account.code] += ln.debit - ln.credit
    return dict(found)


def test_a_full_set_from_the_templates(books: dict[str, Any]) -> None:
    setup(books)
    opening = send(books, "opening-balances", {"file": example("opening-balances.csv"),
                                               "open_items": example("open-items.csv")},
                   commit=True, as_of="2026-01-01", account_map="{}")  # fmt: skip
    assert (opening["committed"], opening["problems"], opening["warnings"]) == (True, [], [])
    assert JournalEntry.objects.get(id=opening["entry_id"]).status == "DRAFT"
    prior = send(books, "prior-year", {"file": example("prior-year.csv")}, commit=True,
                 account_map="{}")  # fmt: skip
    assert (prior["committed"], prior["problems"], prior["warnings"]) == (True, [], [])
    assert len(prior["months"]) == 12
    assert FactComparative.objects.filter(month="2025-06-01").exists()
    # Nothing is in the books until the draft is approved and posted.
    tb_url = f"{books['base']}/reports/trial-balance"
    assert books["client"].get(tb_url, {"as_of": "2026-01-01"}).json()["rows"] == []
    books["client"].put_json(f"{books['base']}/ledger-settings", {"approval_policy": "NONE"})
    assert act(books, opening["entry_id"], "post").status_code == 200
    rows = books["client"].get(tb_url, {"as_of": "2026-01-01"}).json()["rows"]
    posted = {r["code"]: Decimal(r["debit"]) - Decimal(r["credit"]) for r in rows}
    assert posted == source_balances()  # to the cent (AC-R2)


def test_the_accountant_and_package_versions_give_the_same_opening(books: dict[str, Any]) -> None:
    setup(books)
    templates = send(books, "opening-balances", {"file": example("opening-balances.csv"),
                                                 "open_items": example("open-items.csv")},
                     as_of="2026-01-01", account_map="{}")  # fmt: skip
    assert templates["problems"] == []
    delivered = send(books, "opening-balances",
                     {"file": example("accountant-trial-balance.csv"),
                      "aged_receivables": example("aged-receivables.csv"),
                      "aged_payables": example("aged-payables.csv")},
                     commit=True, as_of="2026-01-01", account_map="{}", results_account="3200",
                     date_order="month")  # fmt: skip
    # The aged payables report is month first; the receivables report names its months in words.
    assert (delivered["committed"], delivered["problems"]) == (True, [])
    assert nets(delivered["entry_id"]) == source_balances()
    key = lambda ln: (ln["account_code"], ln["counterparty_code"], ln["reference"],  # noqa: E731
                      ln["debit"], ln["credit"], ln["due_date"])  # fmt: skip
    assert sorted(map(key, delivered["lines"])) == sorted(map(key, templates["lines"]))


PRESETS = {
    "BANK_OF_CYPRUS": "bank-statement-bank-of-cyprus-preset.csv",
    "HELLENIC_BANK": "bank-statement-hellenic-bank-preset.csv",
    "EUROBANK_CYPRUS": "bank-statement-eurobank-cyprus-preset.csv",
    "REVOLUT_BUSINESS": "bank-statement-revolut-business-preset.csv",
}


@pytest.mark.parametrize("preset", list(PRESETS))
def test_each_bank_presets_example_imports_without_setting_columns(
    bank: dict[str, Any], preset: str
) -> None:
    client, url = bank["client"], bank["bank_url"]
    name, data = example(PRESETS[preset])
    found = client.post(f"{url}/csv-detect", {"file": SimpleUploadedFile(name, data),
                                              "preset": preset},
                        headers=client._csrf()).json()  # fmt: skip
    assert found["error"] == ""
    assert found["questions"] == []  # AC-R1: nothing to ask for these files
    assert [ln["amount"] for ln in found["preview"]] == ["3400.00", "-2500.00", "-4.50"]
    assert found["preset"]["status"] == "TO_BE_CONFIRMED"
    assert client.put_json(f"{url}/csv-mapping", found["mapping"]).status_code == 200
    result = upload(bank, data, "CSV", name).json()
    assert (result["status"], result["lines_created"]) == ("DONE", 3)
    assert result["closing_balance"] == "19136.00"
