"""The Milestone 1 demo (AC-G5): load "Demo Trading Ltd (Demo)" through the public HTTP API.

invite users → create the chart of accounts → draft → approve → post → reverse → lock periods →
trial balance → integrity check.

Every step goes through the same API the web UI uses (in-process, via Django's test client), so
authentication, CSRF, permissions, segregation of duties, row-level security and the database
guards all apply. Demo users are local records that cannot sign in through the identity provider;
pass ``share_with`` to give an existing (signed-in-before) user access to the demo workspace.

Synthetic data only (ADR-0010). Never run against production.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.test import Client

from fcp.modules.identity.api import User

from .books import BANK, DemoBooks, build_demo_books

Say = Callable[[str], None]


class DemoStepError(RuntimeError):
    """An API call in the demo did not return the expected status."""


class DemoClient(Client):
    """A signed-in API client that behaves like the SPA (JSON, CSRF header, recent MFA)."""

    def __init__(self, user: User, host: str) -> None:
        super().__init__(enforce_csrf_checks=True, HTTP_HOST=host)
        self.user = user
        self.force_login(user)
        session = self.session
        now = int(time.time())
        # Same keys the OIDC callback sets; recent auth_time satisfies step-up for unlocks.
        session["fcp_auth_time"] = now
        session["fcp_login_at"] = now
        session.save()
        self.call("GET", "/api/me")  # receives the CSRF cookie

    def call(self, method: str, path: str, body: Any = None, expect: int = 200) -> Any:
        headers = {}
        if method != "GET":
            headers["X-CSRFToken"] = self.cookies["__Host-fcp_csrftoken"].value
        response = self.generic(
            method,
            path,
            data=b"" if body is None else _json(body),
            content_type="application/json",
            headers=headers,
        )
        if response.status_code != expect:
            raise DemoStepError(
                f"{method} {path} returned {response.status_code}, expected {expect}: "
                f"{response.content[:500]!r}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


def _json(body: Any) -> bytes:
    return json.dumps(body).encode()


@dataclass
class DemoResult:
    slug: str
    entity_id: str
    entries_posted: int
    trial_balance_total: str
    bank_balance: str
    integrity_status: str
    locked_periods: int
    steps: list[str] = field(default_factory=list)


def _demo_user(role: str) -> User:
    user, _ = User.objects.get_or_create(
        idp_subject=f"demo|{role}",
        defaults={"email": f"demo.{role}@example.test", "display_name": f"Demo {role.title()}"},
    )
    return user


def run(  # noqa: PLR0912, PLR0915 - a linear, narrated script reads best as one function
    *,
    seed: int = 42,
    share_with: str | None = None,
    share_role: str = "finance_manager",
    host: str = "testserver",
    say: Say = print,
    books: DemoBooks | None = None,
) -> DemoResult:
    books = books or build_demo_books(seed)
    year = books.fiscal_year_start.year
    steps: list[str] = []

    def step(message: str) -> None:
        steps.append(message)
        say(f"✔ {message}")

    owner = DemoClient(_demo_user("owner"), host)
    ws = owner.call(
        "POST",
        "/api/workspaces",
        {"name": "Demo Trading", "kind": "BUSINESS", "entity_name": books.company},
        expect=201,
    )
    slug = ws["slug"]
    entity = owner.call("GET", f"/api/w/{slug}/entities")[0]
    base = f"/api/w/{slug}/entities/{entity['id']}"
    step(f"owner created workspace {slug} with entity {books.company}")

    def join(role: str) -> DemoClient:
        user = _demo_user(role)
        issued = owner.call(
            "POST", f"/api/w/{slug}/invitations", {"email": user.email, "role_key": role}, 201
        )
        client = DemoClient(user, host)
        client.call("POST", "/api/invitations/accept", {"token": issued["token"]})
        return client

    accountant = join("accountant")
    reviewer = join("reviewer")
    step("invited and joined: demo accountant (prepares) and demo reviewer (approves, posts)")

    accounts = accountant.call(
        "POST", f"{base}/accounts/apply-template", {"template": "cy_business"}, 201
    )
    by_code = {a["code"]: a["id"] for a in accounts}
    vat_accounts = {a["code"] for a in accounts if a["vat_role"]}
    fiscal_year = accountant.call(
        "POST", f"{base}/fiscal-years", {"start_date": books.fiscal_year_start.isoformat()}, 201
    )
    step(f"chart of accounts applied ({len(accounts)} accounts) and FY{year} created")

    parties: dict[str, str] = {}
    for cp in books.counterparties:
        made = accountant.call("POST", f"{base}/counterparties", {
            "code": cp.code, "name": cp.name, "kind": cp.kind,
            "payment_terms_days": cp.payment_terms_days}, 201)  # fmt: skip
        parties[cp.code] = made["id"]
    step(f"{len(parties)} customers and suppliers registered")

    def lines(rows: list[tuple[str, Decimal, Decimal]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for spec, dr, cr in rows:
            key, _, vat = spec.partition("!")  # "2120!SETTLE": VAT line with code SETTLE
            code, _, party = key.partition("@")  # "1200@C008": control line of customer C008
            line: dict[str, Any] = {"account_id": by_code[code], "debit": f"{dr:.2f}",
                                    "credit": f"{cr:.2f}"}  # fmt: skip
            if party:
                line["counterparty_id"] = parties[party]
            if code in vat_accounts:
                line["vat_code_id"] = f"CY:{vat or 'S19'}:open"
            result.append(line)
        return result

    def draft(accounting_date: date, description: str, rows: list[Any]) -> dict[str, Any]:
        body = {
            "accounting_date": accounting_date.isoformat(),
            "description": description,
            "lines": lines(rows),
        }
        created: dict[str, Any] = accountant.call("POST", f"{base}/journal-entries", body, 201)
        return created

    def through_workflow(entry: dict[str, Any]) -> dict[str, Any]:
        path = f"{base}/journal-entries/{entry['id']}"
        accountant.call("POST", f"{path}/submit")
        reviewer.call("POST", f"{path}/approve")
        posted: dict[str, Any] = reviewer.call("POST", f"{path}/post")
        return posted

    posted = 0
    for demo_entry in books.entries:
        through_workflow(draft(demo_entry.accounting_date, demo_entry.description,
                               demo_entry.netted()))  # fmt: skip
        posted += 1
    step(f"{posted} entries drafted by the accountant, approved and posted by the reviewer")

    # A deliberate mistake, corrected by reversal (posted entries are never edited).
    december = date(year, 12, 31)
    wrong = through_workflow(
        draft(december, "Office cleaning December (Demo) - booked to the wrong account",
              [("6110", Decimal("350.00"), Decimal(0)), (BANK, Decimal(0), Decimal("350.00"))])
    )  # fmt: skip
    reversal = accountant.call(
        "POST",
        f"{base}/journal-entries/{wrong['id']}/reverse",
        {"reason": "Cleaning is an operating expense, not a utility"},
        201,
    )
    through_workflow(reversal)
    through_workflow(
        draft(december, "Office cleaning December (Demo)",
              [("6900", Decimal("350.00"), Decimal(0)), (BANK, Decimal(0), Decimal("350.00"))])
    )  # fmt: skip
    posted += 3
    step(f"entry {wrong['journal']}-{wrong['entry_no']} reversed with a reason and re-posted")

    # Close January..November: soft-close by the accountant, lock by the owner.
    to_lock = [p for p in fiscal_year["periods"] if not p["is_adjustment"] and p["number"] <= 11]
    for period in to_lock:
        status_path = f"{base}/periods/{period['id']}/status"
        accountant.call("POST", status_path, {"status": "SOFT_CLOSED"})
        owner.call("POST", status_path, {"status": "LOCKED"})
    first_customer = next(c.code for c in books.counterparties if c.kind == "CUSTOMER")
    late_invoice = [
        (f"1200@{first_customer}", Decimal("10.00"), Decimal(0)),
        ("4000", Decimal(0), Decimal("10.00")),
    ]
    blocked = draft(date(year, 1, 15), "Late January invoice (Demo) - refused", late_invoice)
    accountant.call("POST", f"{base}/journal-entries/{blocked['id']}/submit")
    reviewer.call("POST", f"{base}/journal-entries/{blocked['id']}/approve")
    reviewer.call("POST", f"{base}/journal-entries/{blocked['id']}/post", expect=409)
    reviewer.call("POST", f"{base}/journal-entries/{blocked['id']}/reject",
                  {"reason": "January is locked; book it in an open period"})  # fmt: skip
    accountant.call("POST", f"{base}/journal-entries/{blocked['id']}/void")
    step(f"periods 1-{len(to_lock)} locked; posting into January is refused (409), "
         "rejected and voided")  # fmt: skip

    tb = reviewer.call("GET", f"{base}/reports/trial-balance?as_of={december.isoformat()}")
    if tb["total_debit"] != tb["total_credit"]:
        raise DemoStepError(
            f"Trial balance does not balance: {tb['total_debit']} / {tb['total_credit']}"
        )
    bank_row = next(r for r in tb["rows"] if r["code"] == BANK)
    expected_bank = books.bank_closing_balance - Decimal("350.00")
    if Decimal(bank_row["balance"]) != expected_bank:
        raise DemoStepError(
            f"Bank balance {bank_row['balance']} differs from the statement ({expected_bank})"
        )
    step(f"trial balance at {december}: {tb['total_debit']} = {tb['total_credit']}; "
         f"bank {bank_row['balance']} matches the synthetic statement")  # fmt: skip

    matched = 0
    for party_id in parties.values():
        created = accountant.call(
            "POST", f"{base}/counterparties/{party_id}/auto-allocate",
            {"as_of": december.isoformat()})  # fmt: skip
        matched += len(created)
    receivable = reviewer.call("GET", f"{base}/reports/ageing?as_of={december}&side=RECEIVABLE")
    payable = reviewer.call("GET", f"{base}/reports/ageing?as_of={december}&side=PAYABLE")
    if not (receivable["reconciles"] and payable["reconciles"]):
        raise DemoStepError("Ageing does not reconcile to the control accounts")
    step(f"{matched} payments matched to invoices; receivables {receivable['total']} and "
         f"payables {payable['total']} reconcile to the ledger")  # fmt: skip

    mapped = accountant.call("POST", f"{base}/account-mapping/apply-defaults",
                             {"template": "cy_business"})["mapped"]  # fmt: skip
    mapping = reviewer.call("GET", f"{base}/account-mapping/completeness?as_of={december}")
    if not mapping["complete"]:
        raise DemoStepError(f"Account mapping incomplete: {mapping['unmapped_blocking']}")
    step(f"{mapped} accounts mapped to the financial taxonomy; mapping complete for statements")

    actuals_check = owner.call("GET", f"/api/w/{slug}/actuals/verify")
    if not actuals_check["ok"]:
        raise DemoStepError(f"Actuals read model differs from the ledger: {actuals_check}")
    step(f"actuals read model up to posting {actuals_check['watermark']} matches the ledger")

    check = owner.call("POST", f"/api/w/{slug}/integrity-checks", None, 201)
    if check["status"] != "PASSED":
        raise DemoStepError(f"Integrity check {check['status']}: {check['results']}")
    step("integrity checks passed (balance, snapshots, gapless numbering, audit chain)")

    if share_with:
        viewer = User.objects.filter(email__iexact=share_with).order_by("created_at").first()
        if viewer is None:
            say(f"! no user with email {share_with}; sign in once through the web UI, then rerun")
        else:
            issued = owner.call("POST", f"/api/w/{slug}/invitations",
                                {"email": viewer.email, "role_key": share_role}, 201)  # fmt: skip
            DemoClient(viewer, host).call(
                "POST", "/api/invitations/accept", {"token": issued["token"]}
            )
            step(f"shared with {viewer.email} as {share_role}")

    return DemoResult(
        slug=slug,
        entity_id=entity["id"],
        entries_posted=posted,
        trial_balance_total=tb["total_debit"],
        bank_balance=bank_row["balance"],
        integrity_status=check["status"],
        locked_periods=len(to_lock),
        steps=steps,
    )


__all__ = ["DemoClient", "DemoResult", "DemoStepError", "run"]
