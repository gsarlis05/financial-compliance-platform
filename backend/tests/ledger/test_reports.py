"""Trial balance, general ledger and exports (doc 09 AC-C8, AC-C11)."""

import csv
import io
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from hypothesis import given, settings
from hypothesis import strategies as st

from fcp.core.db.rls import set_context
from fcp.core.export import safe_text
from fcp.modules.audit_log.models import AuditEvent
from fcp.modules.ledger import accounts, entries, periods, reports
from fcp.modules.ledger.models import AccountBalance
from fcp.modules.tenancy import services as tenancy

from .conftest import join
from .test_entries import SALE, act, create, payload, post_through_workflow

Make = Callable[..., Any]


@pytest.fixture
def reviewer(books: dict[str, Any], make_user: Make, api_client: Make) -> Any:
    return join(
        books["client"], books["ws"]["slug"], make_user("r@example.test"), api_client, "reviewer"
    )


def tb(books: dict[str, Any], client: Any = None, **params: Any) -> Any:
    return (client or books["client"]).get(
        f"{books['base']}/reports/trial-balance", {"as_of": "2026-12-31", **params}
    )


# --- trial balance --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_trial_balance_balances_and_uses_normal_sides(books: dict[str, Any], reviewer: Any) -> None:
    post_through_workflow(books, reviewer, *SALE)
    post_through_workflow(books, reviewer, ("6100", "500.00", "0"), ("1300", "0", "500.00"))
    body = tb(books).json()
    rows = {r["code"]: r for r in body["rows"]}
    # Debit balances: bank 690 + groceries 500; credit balances: revenue 1000 + VAT 190.
    assert body["total_debit"] == body["total_credit"] == "1190.00"
    assert rows["1300"]["debit"] == "690.00"
    assert rows["1300"]["balance"] == "690.00"
    assert rows["4000"]["credit"] == "1000.00"
    assert rows["4000"]["balance"] == "1000.00", "income shown positive on its credit side"
    assert set(rows) == {"1300", "2120", "4000", "6100"}, "zero rows hidden by default"
    with_zero = tb(books, include_zero="true").json()
    assert len(with_zero["rows"]) > 40


@pytest.mark.django_db
def test_trial_balance_cut_off_and_activity_window(books: dict[str, Any], reviewer: Any) -> None:
    post_through_workflow(books, reviewer, *SALE, day="2026-02-10")
    post_through_workflow(books, reviewer, *SALE, day="2026-05-10")
    assert tb(books, as_of="2026-03-31").json()["total_debit"] == "1190.00"
    window = tb(books, as_of="2026-12-31", date_from="2026-04-01").json()
    assert window["total_debit"] == "1190.00"
    assert tb(books, as_of="2026-12-31").json()["total_debit"] == "2380.00"


@pytest.mark.django_db
def test_trial_balance_reports_unposted_drafts(books: dict[str, Any]) -> None:
    create(books, *SALE)
    body = tb(books).json()
    assert body["unposted_entries"] == 1
    assert body["rows"] == []


@pytest.mark.django_db
def test_corrupted_ledger_refuses_to_render(books: dict[str, Any], reviewer: Any) -> None:
    posted = post_through_workflow(books, reviewer, *SALE)
    set_context(tenant_id=books["ws"]["id"])
    with connection.cursor() as cursor:  # an attacker with DDL rights bypasses the guards
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")  # flush pending deferred checks first
        cursor.execute("ALTER TABLE ledger_journal_line DISABLE TRIGGER ledger_line_guard")
        cursor.execute(
            "UPDATE ledger_journal_line SET debit = debit + 1 WHERE entry_id = %s AND debit > 0",
            [posted["id"]],
        )
        cursor.execute("ALTER TABLE ledger_journal_line ENABLE TRIGGER ledger_line_guard")
    response = tb(books)
    assert response.status_code == 500
    assert response.json()["code"] == "ledger.integrity_failure"


@dataclass(frozen=True)
class FakeAccount:
    id: uuid.UUID
    code: str
    name: str
    type: str
    normal_side: str


FAKE_ACCOUNTS = [
    FakeAccount(uuid.uuid4(), f"{1000 + i}", f"Account {i}", t, s)
    for i, (t, s) in enumerate(
        [
            ("ASSET", "DEBIT"),
            ("LIABILITY", "CREDIT"),
            ("EQUITY", "CREDIT"),
            ("INCOME", "CREDIT"),
            ("EXPENSE", "DEBIT"),
            ("ASSET", "DEBIT"),
        ]
    )
]

balanced_entries = st.lists(
    st.lists(
        st.tuples(st.integers(0, len(FAKE_ACCOUNTS) - 1), st.integers(1, 10**9)),
        min_size=1,
        max_size=6,
    ).flatmap(
        lambda debits: st.tuples(st.just(debits), st.permutations(range(len(FAKE_ACCOUNTS))))
    ),
    min_size=0,
    max_size=30,
)


@settings(max_examples=1000, deadline=None)
@given(entry_sets=balanced_entries)
def test_property_trial_balance_always_balances(entry_sets: list[Any]) -> None:
    """AC-C8: for 1,000 random sets of balanced entries, total debits equal total credits."""
    sums: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    for debits, order in entry_sets:
        total = 0
        for idx, cents in debits:
            account = FAKE_ACCOUNTS[idx]
            d, c = sums.get(account.id, (Decimal(0), Decimal(0)))
            sums[account.id] = (d + Decimal(cents) / 100, c)
            total += cents
        credit_account = FAKE_ACCOUNTS[order[0]]  # one balancing credit line
        d, c = sums.get(credit_account.id, (Decimal(0), Decimal(0)))
        sums[credit_account.id] = (d, c + Decimal(total) / 100)
    rows = reports.build_trial_balance(FAKE_ACCOUNTS, sums)  # type: ignore[arg-type]
    result = reports.TrialBalance(
        as_of=date(2026, 12, 31),
        date_from=None,
        rows=rows,
        unposted_entries=0,
        restated_after_lock=0,
    )
    assert result.total_debit == result.total_credit


@pytest.mark.django_db
def test_snapshot_equals_line_sums_after_many_random_postings(make_user: Make) -> None:
    """AC-C8: the maintained balances equal the sum of posted lines (150 random entries)."""
    rng = random.Random(20261103)  # noqa: S311 - test data
    owner = make_user()
    ctx = tenancy.create_workspace(owner, name="Random", kind="PERSONAL")
    entity_id = tenancy.list_entities(ctx)[0].id
    chart = [a for a in accounts.apply_template(ctx, entity_id, "personal") if a.is_postable]
    periods.create_fiscal_year(ctx, entity_id, start_date=date(2026, 1, 1))
    for n in range(150):
        debit_acc, credit_acc = rng.sample(chart, 2)
        amount = f"{Decimal(rng.randint(1, 5_000_000)) / 100:.2f}"
        entry = entries.create_draft(
            ctx,
            entity_id,
            entries.EntryInput(
                accounting_date=date(2026, 1, 1) + timedelta(days=rng.randint(0, 364)),
                description=f"Random {n}",
                lines=[
                    entries.LineInput(debit_acc.id, debit=amount),
                    entries.LineInput(credit_acc.id, credit=amount),
                ],
            ),
        )
        entries.post(ctx, entity_id, entry.id)
    result = reports.trial_balance(ctx, entity_id, as_of=date(2026, 12, 31))
    assert result.total_debit == result.total_credit
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT l.account_id, sum(l.debit), sum(l.credit) FROM ledger_journal_line l "
            "JOIN ledger_journal_entry e ON e.id = l.entry_id WHERE e.status = 'POSTED' "
            "GROUP BY l.account_id"
        )
        from_lines = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
    snapshot: dict[uuid.UUID, tuple[Decimal, Decimal]] = {}
    for b in AccountBalance.objects.filter(legal_entity_id=entity_id):
        d, c = snapshot.get(b.account_id, (Decimal(0), Decimal(0)))
        snapshot[b.account_id] = (d + b.debit_total, c + b.credit_total)
    assert snapshot == from_lines


# --- general ledger -------------------------------------------------------------------------------


@pytest.mark.django_db
def test_general_ledger_running_balance(books: dict[str, Any], reviewer: Any) -> None:
    post_through_workflow(books, reviewer, *SALE, day="2026-01-15")
    post_through_workflow(
        books, reviewer, ("6100", "300.00", "0"), ("1300", "0", "300.00"), day="2026-02-01"
    )
    post_through_workflow(books, reviewer, *SALE, day="2026-02-20")
    bank = books["accounts"]["1300"]["id"]
    body = (
        books["client"]
        .get(
            f"{books['base']}/reports/general-ledger/{bank}",
            {"date_from": "2026-02-01", "date_to": "2026-02-28"},
        )
        .json()
    )
    assert body["opening_balance"] == "1190.00"
    assert [ln["running_balance"] for ln in body["lines"]] == ["890.00", "2080.00"]
    assert body["closing_balance"] == "2080.00"
    assert body["lines"][0]["entry_ref"] == "GJ-2"
    revenue = books["accounts"]["4000"]["id"]
    income = (
        books["client"]
        .get(
            f"{books['base']}/reports/general-ledger/{revenue}",
            {"date_from": "2026-01-01", "date_to": "2026-12-31"},
        )
        .json()
    )
    assert income["closing_balance"] == "2000.00", "credit-normal account shown positive"


@pytest.mark.django_db
def test_general_ledger_unknown_account_is_404(books: dict[str, Any]) -> None:
    response = books["client"].get(
        f"{books['base']}/reports/general-ledger/{uuid.uuid4()}",
        {"date_from": "2026-01-01", "date_to": "2026-12-31"},
    )
    assert response.status_code == 404


# --- exports (AC-C11) -----------------------------------------------------------------------------


@pytest.mark.django_db
def test_csv_exports_neutralise_formula_injection(books: dict[str, Any], reviewer: Any) -> None:
    body = payload(books, *SALE)
    body["description"] = '=HYPERLINK("https://evil.example","click")'
    body["lines"][0]["memo"] = "+cmd|' /C calc'!A0"
    entry = books["client"].post_json(f"{books['base']}/journal-entries", body).json()
    act(books, entry["id"], "submit")
    act(books, entry["id"], "approve", reviewer)
    act(books, entry["id"], "post", reviewer)
    bank = books["accounts"]["1300"]["id"]
    response = books["client"].get(
        f"{books['base']}/reports/general-ledger/{bank}.csv",
        {"date_from": "2026-01-01", "date_to": "2026-12-31"},
    )
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    posting = rows[2]
    assert posting[2].startswith("'=HYPERLINK")
    assert posting[3].startswith("'+cmd")
    assert posting[4] == "1190.00", "numbers stay numeric"
    tb_csv = books["client"].get(
        f"{books['base']}/reports/trial-balance.csv", {"as_of": "2026-12-31"}
    )
    tb_rows = list(csv.reader(io.StringIO(tb_csv.content.decode())))
    assert tb_rows[-1] == ["", "Total", "", "1190.00", "1190.00"]
    set_context(tenant_id=books["ws"]["id"])
    assert AuditEvent.objects.filter(action="reports.exported").count() == 2


@pytest.mark.parametrize("value", ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])
def test_safe_text_escapes_formula_prefixes(value: str) -> None:
    assert safe_text(value) == "'" + value
    assert safe_text("Normal text") == "Normal text"


@pytest.mark.django_db
def test_read_only_can_read_but_not_export(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    viewer = join(
        books["client"], books["ws"]["slug"], make_user("ro2@example.test"), api_client, "read_only"
    )
    assert tb(books, viewer).status_code == 200
    export = viewer.get(f"{books['base']}/reports/trial-balance.csv", {"as_of": "2026-12-31"})
    assert export.status_code == 403


@pytest.mark.django_db
def test_reports_are_isolated_between_tenants(
    books: dict[str, Any], make_user: Make, api_client: Make
) -> None:
    outsider = api_client(make_user("outsider2@example.test"))
    assert tb(books, outsider).status_code == 404
