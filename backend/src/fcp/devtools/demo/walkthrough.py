"""The Milestone 1 demo (AC-G5): load "Demo Trading Ltd (Demo)" through the public HTTP API.

invite users → create the chart of accounts → draft → approve → post → reverse → lock periods →
trial balance → integrity check.

Every step goes through the same API the web UI uses (in-process, via Django's test client), so
authentication, CSRF, permissions, segregation of duties, row-level security and the database
guards all apply. Demo users are local records that cannot sign in through the identity provider;
pass ``share_with`` to give an existing (signed-in-before) user access to the demo workspace.

Synthetic data only (ADR-0010). Never run against production.
"""

import hashlib
import io
import json
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.test import Client

from fcp.modules.identity.api import User

from .books import BANK, DemoBooks, build_demo_books
from .camt import Txn, camt053

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

    def upload(self, path: str, content: bytes, fmt: str, name: str, expect: int = 201) -> Any:
        """Multipart upload, as the SPA sends a statement file."""
        from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: PLC0415

        csrf = self.cookies["__Host-fcp_csrftoken"].value
        form = {"file": SimpleUploadedFile(name, content), "format": fmt}
        response = self.post(path, form, headers={"X-CSRFToken": csrf})
        if response.status_code != expect:
            raise DemoStepError(
                f"POST {path} returned {response.status_code}, expected {expect}: "
                f"{response.content[:500]!r}"
            )
        return response.json()

    def upload_document(self, path: str, content: bytes, name: str, expect: int = 201,
                        **form: str) -> Any:  # fmt: skip
        from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: PLC0415

        csrf = self.cookies["__Host-fcp_csrftoken"].value
        data = {"file": SimpleUploadedFile(name, content), **form}
        response = self.post(path, data, headers={"X-CSRFToken": csrf})
        if response.status_code != expect:
            raise DemoStepError(
                f"POST {path} returned {response.status_code}, expected {expect}: "
                f"{response.content[:500]!r}"
            )
        return response.json()

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
    statements: dict[str, Any] = field(default_factory=dict)
    forecast: dict[str, Any] = field(default_factory=dict)


def _demo_invoice_pdf(text: str, amount: str) -> bytes:
    """A one-page synthetic invoice (fictional; never real client data)."""
    import io  # noqa: PLC0415

    from reportlab.lib.pagesizes import A4  # noqa: PLC0415
    from reportlab.pdfgen import canvas  # noqa: PLC0415

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, invariant=True)  # deterministic bytes
    pdf.drawString(72, 760, "INVOICE (Demo) - fictional, for demonstration only")
    pdf.drawString(72, 730, text)
    pdf.drawString(72, 700, f"Total EUR {amount}")
    pdf.save()
    return buffer.getvalue()


def _budget(owner: "DemoClient", accountant: "DemoClient", base: str, year: int) -> dict[str, Any]:
    """A budget for the following year: sales phased like this year's posted actuals, rent as
    quantity x rate, payroll evenly. The accountant submits and the owner approves (SoD)."""
    following = f"{year + 1}-01-01"
    years = owner.call("GET", f"{base}/fiscal-years")
    fy = next((y for y in years if y["start_date"] == following), None)
    if fy is None:
        fy = owner.call("POST", f"{base}/fiscal-years", {"start_date": following}, 201)
    created = accountant.call(
        "POST", f"{base}/budgets", {"name": f"Budget {year + 1}", "fiscal_year_id": fy["id"]}, 201
    )
    version = created["open_version_id"]
    lines = [
        {"taxonomy_code": "REV.SALES", "method": "SEASONAL", "params": {"annual": "600000.00"}},
        {"taxonomy_code": "OPEX.RENT", "method": "DRIVER",
         "params": {"quantity": "1", "rate": "2500.00"}},
        {"taxonomy_code": "OPEX.PAYROLL", "method": "EVEN", "params": {"annual": "108000.00"}},
    ]  # fmt: skip
    accountant.call("PUT", f"{base}/budget-versions/{version}/lines", {"lines": lines})
    accountant.call("POST", f"{base}/budget-versions/{version}/submit", {})
    approved = owner.call("POST", f"{base}/budget-versions/{version}/approve",
                          {"comment": "Demo approval"})  # fmt: skip
    if approved["status"] != "APPROVED":
        raise DemoStepError(f"Budget approval failed: {approved}")
    detail: dict[str, Any] = owner.call("GET", f"{base}/budget-versions/{version}")
    return detail


SAMPLE_GOALS = (
    ("Revenue 500k", "REVENUE", "ABSOLUTE", "500000"),
    ("EBITDA margin 20%", "kpi:EBITDA_MARGIN", "ABSOLUTE", "0.20"),
    ("Cash at least 100k", "CASH", "MAINTAIN_MIN", "100000"),
    ("DSO 30 days", "kpi:DSO", "ABSOLUTE", "30"),
    ("Net profit +15%", "NET_PROFIT", "CHANGE_PCT", "0.15"),
    ("Opex -10%", "OPEX", "CHANGE_PCT", "-0.10"),
)


def _goals(owner: "DemoClient", base: str, year: int) -> list[dict[str, Any]]:
    """The six sample goals for the budget year (doc 12 AC-GO2), each evaluated once: baselines
    from this year's actuals, outcomes from the approved budget and the cash forecast."""
    evaluated = []
    for name, metric, target_type, target in SAMPLE_GOALS:
        made = owner.call("POST", f"{base}/goals", {
            "name": name, "metric": metric, "target_type": target_type, "target": target,
            "period_start": f"{year + 1}-01-01", "period_end": f"{year + 1}-12-31",
        }, 201)  # fmt: skip
        result = owner.call("POST", f"{base}/goals/{made['id']}/evaluations", {}, 201)
        if result["run_status"] != "VALID":
            raise DemoStepError(f"Goal evaluation failed: {result}")
        evaluated.append({"name": name, "status": result["status"], "method": result["method"]})
    return evaluated


def _personal(owner: "DemoClient", year: int) -> dict[str, Any]:
    """The owner's own personal workspace (a separate tenant): synthetic opening balances, a
    month of spending and income, and a home valuation (doc 11)."""
    ws = owner.call("POST", "/api/workspaces", {"name": "My finances (Demo)", "kind": "PERSONAL"},
                    201)  # fmt: skip
    entity = owner.call("GET", f"/api/w/{ws['slug']}/entities")[0]
    base = f"/api/w/{ws['slug']}/entities/{entity['id']}/personal"
    owner.call("POST", f"{base}/setup", {})
    acc = {a["code"]: a["id"] for a in owner.call("GET", f"{base}/accounts")}
    day = f"{year}-01-01"
    for code, amount in (("1100", "6500.00"), ("1110", "12000.00"), ("2200", "142000.00")):
        owner.call("POST", f"{base}/opening-balances",
                   {"account_id": acc[code], "date": day, "amount": amount}, 201)  # fmt: skip
    rows = (
        ("RECEIVED", "2500.00", "Salary", "1100", "4000"),
        ("SPENT", "640.00", "Mortgage payment (interest part)", "1100", "6010"),
        ("SPENT", "380.25", "Groceries", "1100", "6100"),
        ("SPENT", "95.40", "Electricity and water", "1100", "6200"),
        ("MOVED", "500.00", "Monthly saving", "1100", "1110"),
    )
    for kind, amount, text, account, other in rows:
        body = {"kind": kind, "date": f"{year}-01-28", "amount": amount, "description": text,
                "account_id": acc[account]}  # fmt: skip
        body["to_account_id" if kind == "MOVED" else "category_id"] = acc[other]
        owner.call("POST", f"{base}/transactions", body, 201)
    owner.call("POST", f"{base}/valuations", {"account_id": acc["1300"], "date": f"{year}-01-31",
                                              "value": "310000.00", "note": "Synthetic estimate"},
               201)  # fmt: skip
    worth: dict[str, Any] = owner.call("GET", f"{base}/net-worth?as_of={year}-01-31")
    owner.call("PUT", f"{base}/budget", {"account_id": acc["6100"], "monthly_amount": "400.00",
                                         "from_month": f"{year}-02-01"})  # fmt: skip
    for body in (
        {"kind": "EMERGENCY_FUND", "name": "Emergency fund", "months": 6,
         "account_ids": [acc["1110"]], "target_date": f"{year + 1}-12-31"},
        {"kind": "SAVINGS", "name": "Savings 20k", "target_amount": "20000.00",
         "account_ids": [acc["1110"]], "target_date": f"{year + 1}-12-31"},
    ):  # fmt: skip
        owner.call("POST", f"{base}/goals", body, 201)
    worth["goals"] = owner.call("GET", f"{base}/goals")
    worth["projection"] = owner.call("GET", f"{base}/projection")
    worth["base"], worth["accounts"] = base, acc
    return worth


def _counterpart(owner: "DemoClient", personal: dict[str, Any], business: str,
                 director_loans: str, since: str) -> dict[str, Any]:  # fmt: skip
    """Opt-in counterpart hint (M5-3): link the business director's loan account, read the
    suggestions in the business workspace, and confirm one in the personal books."""
    base, acc = personal["base"], personal["accounts"]
    slug, entity_id = business.split("/")[3], business.split("/")[5]
    made = owner.call("POST", f"{base}/counterpart-links", {
        "business_slug": slug, "business_entity_id": entity_id,
        "business_account_id": director_loans, "label": "Demo Trading · 2020 Director loans",
        "account_id": acc["1100"], "category_id": acc["4000"], "since": since,
    }, 201)  # fmt: skip
    gl = owner.call("GET", f"{business}/reports/general-ledger/{director_loans}"
                           f"?date_from={since}&date_to={since[:4]}-12-31")  # fmt: skip
    hints = [ln for ln in gl["lines"] if ln["debit"] != "0.00"]
    if not hints:
        raise DemoStepError(f"No counterpart suggestion: {gl}")
    first = hints[0]
    owner.call("POST", f"{base}/counterpart-links/{made['id']}/confirm", {
        "business_entry_id": first["entry_id"], "date": first["accounting_date"],
        "amount": first["debit"], "description": f"{made['label']}: {first['description']}",
    }, 201)  # fmt: skip
    return {"suggested": len(hints), "confirmed": first["debit"]}


def _cash_forecast(owner: "DemoClient", base: str, year: int) -> dict[str, Any]:
    """Synthetic commitments for Demo Trading, then the 13-week forecast from 4 January."""
    following = year + 1
    for path, body in (
        (
            "obligations",
            {
                "name": "Warehouse rent (Demo)",
                "category": "RENT",
                "direction": "OUTFLOW",
                "amount": "2500.00",
                "frequency": "MONTHLY",
                "day_of_month": 1,
                "start_date": f"{year}-01-01",
                "adjust": "FOLLOWING",
                "contractual": True,
            },
        ),
        (
            "obligations",
            {
                "name": "Payroll (Demo)",
                "category": "PAYROLL",
                "direction": "OUTFLOW",
                "amount": "9000.00",
                "frequency": "MONTHLY",
                "day_of_month": 25,
                "start_date": f"{year}-01-25",
                "adjust": "PRECEDING",
                "contractual": True,
            },
        ),
        (
            "obligations",
            {
                "name": "Utilities estimate (Demo)",
                "category": "UTILITIES",
                "direction": "OUTFLOW",
                "amount": "450.00",
                "frequency": "MONTHLY",
                "day_of_month": 12,
                "start_date": f"{year}-01-12",
                "adjust": "FOLLOWING",
                "contractual": False,
            },
        ),
        (
            "debt-instruments",
            {
                "name": "Term loan (Demo)",
                "kind": "TERM_LOAN",
                "principal": "50000.00",
                "start_date": f"{year}-07-01",
                "maturity_date": f"{year + 5}-07-01",
                "rate_type": "FIXED",
                "fixed_rate": "0.05",
                "day_count": "ACT_365",
                "repayment_type": "ANNUITY",
            },
        ),
        (
            "debt-instruments",
            {
                "name": "Overdraft (Demo)",
                "kind": "OVERDRAFT",
                "facility_limit": "20000.00",
                "start_date": f"{year}-01-01",
                "rate_type": "FIXED",
                "fixed_rate": "0.08",
            },
        ),
        (
            "tax-payments",
            {
                "kind": "VAT",
                "period_label": f"{year}-Q4",
                "amount": "6200.00",
                "due_date": f"{following}-02-10",
                "nature": "EXPECTED",
                "reference": "Synthetic estimate (Demo)",
            },
        ),
        (
            "cash-items",
            {
                "day": f"{following}-01-20",
                "amount": "5000.00",
                "category": "GRANT",
                "reason": "Synthetic export grant (Demo)",
            },
        ),
    ):
        owner.call("POST", f"{base}/{path}", body, 201)
    owner.call(
        "PUT",
        f"{base}/cash-forecast-settings",
        {"minimum_cash": "30000.00", "unreconciled_warning_days": 7},
    )
    forecast: dict[str, Any] = owner.call(
        "POST", f"{base}/cash-forecasts", {"as_of": f"{following}-01-04"}, 201
    )
    replay = owner.call("POST", f"{base}/calc-runs/{forecast['run_id']}/reproduce", {})
    if forecast["status"] != "VALID" or not replay["reproduced"]:
        raise DemoStepError(f"The cash forecast is not valid or not reproducible: {replay}")
    return forecast


def _engagement(owner: "DemoClient", host: str, slug: str, year: int) -> dict[str, Any]:
    """A firm is let into the client's own workspace (M5-4): granted by the owner, staffed by the
    firm, used through the grant, then revoked with immediate effect."""
    partner = DemoClient(_demo_user("partner"), host)
    firm = partner.call("POST", "/api/workspaces", {"name": "Demo Accountants", "kind": "FIRM"},
                        201)  # fmt: skip
    until = f"{year + 2}-12-31T23:59:59Z"
    made = owner.call("POST", f"/api/w/{slug}/engagements", {
        "firm_slug": firm["slug"], "scope_roles": ["accountant", "read_only"],
        "valid_until": until}, 201)  # fmt: skip
    me = partner.call("GET", f"/api/w/{firm['slug']}/members")[0]["membership_id"]
    partner.call("POST", f"/api/w/{firm['slug']}/client-engagements/{made['id']}/staff",
                 {"membership_id": me}, 201)  # fmt: skip
    inside = partner.call("GET", f"/api/w/{slug}")
    rows = partner.call("GET", f"/api/w/{firm['slug']}/portfolio?month={year}-12-01")
    owner.call("POST", f"/api/w/{slug}/engagements/{made['id']}/revoke", {})
    partner.call("GET", f"/api/w/{slug}", expect=404)
    after = partner.call("GET", f"/api/w/{firm['slug']}/portfolio?month={year}-12-01")
    if [r["client_slug"] for r in rows] != [slug] or after:
        raise DemoStepError(f"The firm portfolio does not follow the grant: {rows} / {after}")
    return {"firm": firm["name"], "roles": inside["roles"], "clients": len(rows)}


def _fixed_assets(owner: "DemoClient", base: str, by_code: dict[str, str],
                  year: int) -> dict[str, Any]:  # fmt: skip
    """Two synthetic assets bought in December, and January's depreciation prepared as a draft
    entry (M6-1). The register only prepares; the normal workflow approves and posts it."""
    common = {"asset_account_id": by_code["1010"], "accumulated_account_id": by_code["1019"],
              "expense_account_id": by_code["6600"], "acquired_on": f"{year}-12-10"}  # fmt: skip
    for body in (
        {"code": "VAN-1", "name": "Delivery van (Demo)", "category": "VEHICLES",
         "cost": "24000.00", "useful_life_months": 48},
        {"code": "IT-1", "name": "Laptops (Demo)", "category": "IT_EQUIPMENT", "cost": "3600.00",
         "useful_life_months": 36, "method": "DECLINING_BALANCE", "annual_rate": "40"},
    ):  # fmt: skip
        owner.call("POST", f"{base}/fixed-assets", {**common, **body}, 201)
    run: dict[str, Any] = owner.call("POST", f"{base}/depreciation-runs",
                                     {"month": f"{year + 1}-01-01"}, 201)  # fmt: skip
    return run


def _assumptions(owner: "DemoClient", base: str, year: int) -> dict[str, Any]:
    """Assumptions for the two years after the demo year, started from its actuals with revenue
    growing 10% a year, then approved (M6-2)."""
    made = owner.call("POST", f"{base}/assumption-sets", {
        "name": f"Plan {year + 1}-{year + 2} (Demo)", "cutover": f"{year}-12-31", "months": 24,
        "start_from": "ACTUALS", "revenue_growth": "10"}, 201)  # fmt: skip
    approved: dict[str, Any] = owner.call(
        "POST", f"{base}/assumption-sets/{made['id']}/approve", {}
    )
    grid = owner.call("GET", f"{base}/assumption-sets/{made['id']}")
    first = {(r["driver"], r["line"]): r["values"][0] for r in grid["rows"]}
    return {**approved, "gross_margin": first[("gross_margin", "")], "dso": first[("dso", "")]}


def _projection(owner: "DemoClient", base: str, set_id: str) -> dict[str, Any]:
    """The three statements from the approved assumptions, checked and published (M6-3)."""
    run = owner.call("POST", f"{base}/projections", {"assumption_set_id": set_id}, 201)
    if run["status"] != "VALID":
        raise DemoStepError(
            f"The projection is {run['status']}: {run['error'] or run['invariants']}"
        )
    owner.call("POST", f"{base}/calc-runs/{run['id']}/publish", {})
    got = owner.call("GET", f"{base}/projections/{run['id']}?granularity=YEAR")
    rows = got["rows"]
    return {
        **run,
        "checks": sum(run["invariants"].values()),
        "cash": rows["BS.CASH"][-1],
        "revenue": rows["PL.REVENUE"][-1],
        "net_income": rows["PL.NET_INCOME"][-1],
    }


def _rolling(owner: "DemoClient", base: str, set_id: str) -> dict[str, Any]:
    """A rolling 12-month forecast from the approved assumptions, run once (M6-4)."""
    owner.call("PUT", f"{base}/rolling-forecast", {"assumption_set_id": set_id, "horizon": 12})
    got: dict[str, Any] = owner.call("POST", f"{base}/rolling-forecast/refresh", {})
    if got["latest"] is None or got["latest"]["status"] != "VALID" or got["stale"]:
        raise DemoStepError(f"The rolling forecast did not run cleanly: {got['stale_reasons']}")
    return got


def _export_and_deletion(owner: "DemoClient", slug: str) -> dict[str, Any]:
    """The full export of the workspace, checked against its own manifest; and the two-step
    deletion of a throwaway workspace, cancelled inside the grace period (M5-6)."""
    csrf = owner.cookies["__Host-fcp_csrftoken"].value
    response = owner.post(f"/api/w/{slug}/export", "{}", content_type="application/json",
                          headers={"X-CSRFToken": csrf})  # fmt: skip
    if response.status_code != 200:
        raise DemoStepError(f"Export returned {response.status_code}: {response.content[:300]!r}")
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    manifest = json.loads(archive.read("manifest.json"))
    for table, meta in manifest["tables"].items():
        data = archive.read(f"tables/{table}.jsonl")
        if (
            hashlib.sha256(data).hexdigest() != meta["sha256"]
            or len(data.splitlines()) != meta["rows"]
        ):
            raise DemoStepError(f"The export of {table} does not match its manifest.")
    body = {"name": "Old project (Demo)", "kind": "BUSINESS",
            "entity_name": "Old project Ltd (Demo)"}  # fmt: skip
    spare = owner.call("POST", "/api/workspaces", body, 201)
    url = f"/api/w/{spare['slug']}/deletion"
    owner.call("POST", url, {}, 201)
    confirmed = owner.call("POST", f"{url}/confirm", {"workspace_name": "Old project (Demo)"})
    owner.call("POST", f"{url}/cancel", {})
    return {"tables": len(manifest["tables"]), "files": len(manifest["files"]),
            "rows": sum(t["rows"] for t in manifest["tables"].values()),
            "grace_days": confirmed["grace_days"]}  # fmt: skip


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
    cleaning_entry = through_workflow(
        draft(december, "Office cleaning December (Demo)",
              [("6900", Decimal("350.00"), Decimal(0)), (BANK, Decimal(0), Decimal("350.00"))])
    )  # fmt: skip
    posted += 3
    step(f"entry {wrong['journal']}-{wrong['entry_no']} reversed with a reason and re-posted")

    # Documents (M2-4): the cleaning invoice is attached as evidence; a test virus is refused.
    invoice = _demo_invoice_pdf(f"Cleaning services December {year} (Demo)", "350.00")
    attached = accountant.upload_document(f"{base}/documents", invoice, "cleaning-invoice.pdf",
                                          entry_id=cleaning_entry["id"])  # fmt: skip
    accountant.upload_document(f"{base}/documents", invoice, "cleaning-invoice-copy.pdf",
                               expect=200)  # fmt: skip
    eicar = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
    refused = accountant.upload_document(f"{base}/documents", eicar, "notes.txt", expect=422)
    if refused.get("code") != "documents.malware_detected":
        raise DemoStepError(f"The test virus was not refused: {refused}")
    step(
        f"invoice {attached['filename']} attached to the cleaning entry (virus-scanned, type "
        "checked; the same file again is the same document); the EICAR test virus was refused"
    )

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

    # Bank (M2-5): the synthetic statement for the year, plus the December cleaning payment.
    cleaning = Txn(december, Decimal("-350.00"), "Office cleaning December (Demo)", "", "",
                   "CLEAN-12")  # fmt: skip
    txns = [
        Txn(day, amount, text, ref, "", f"BANK-{n:04d}")
        for n, (day, amount, text, ref) in enumerate(books.bank_transactions, start=1)
    ]
    statement = camt053(
        [*txns, cleaning],
        iban="CY00DEMO0000000000000000000000",
        opening=books.opening_cash,
        statement_id=f"DEMO-{year}",
        period=(books.fiscal_year_start, december),
    )
    ledger_bank = next(a for a in accountant.call("GET", f"{base}/accounts") if a["code"] == BANK)
    # Synthetic IBANs have deliberately invalid check digits (never a real account), so the bank
    # account is created without one; the statement still names its (fictional) account.
    bank_account = owner.call("POST", f"{base}/bank-accounts",
                              {"ledger_account_id": ledger_bank["id"],
                               "name": "Current account (Demo)"}, 201)  # fmt: skip
    bank_url = f"{base}/bank-accounts/{bank_account['id']}"
    imported = accountant.upload(f"{bank_url}/imports", statement, "CAMT053", f"demo-{year}.xml")
    if imported["status"] != "DONE":
        raise DemoStepError(f"Statement import failed: {imported}")
    accountant.upload(f"{bank_url}/imports", statement, "CAMT053", f"demo-{year}.xml", expect=409)
    auto = accountant.call("POST", f"{bank_url}/auto-match", {})["matched"]
    reconciled = accountant.call("POST", f"{bank_url}/reconcile", {"as_of": december.isoformat()})
    if not reconciled["reconciled"]:
        raise DemoStepError(f"Bank does not reconcile: {reconciled}")
    step(f"bank statement imported ({imported['lines_created']} lines); importing it again created "
         f"no duplicates; {auto} matched to ledger entries automatically; reconciled at "
         f"{december}: ledger {reconciled['ledger_balance']} = statement "
         f"{reconciled['statement_balance']}")  # fmt: skip

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

    statements = reviewer.call(
        "GET", f"{base}/statements?date_from={books.fiscal_year_start}&date_to={december}"
        "&comparative=none")  # fmt: skip
    if not statements["ok"]:
        raise DemoStepError(f"Statement checks failed: {statements}")
    totals = {r["code"]: r["current"] for r in statements["balance_sheet"]["rows"]}
    result = {r["code"]: r["current"] for r in statements["profit_and_loss"]["rows"]}
    cash = {r["code"]: r["current"] for r in statements["cash_flow"]["rows"]}
    if cash["CF.CASH_CLOSING"] != bank_row["balance"]:
        raise DemoStepError("The cash flow statement does not end at the bank balance")
    step(f"statements for {year}: balance sheet balances at {totals['BS.TOTAL_ASSETS']}; "
         f"profit {result['PL.RESULT']} = movement in equity; cash flow ends at the bank "
         f"balance {cash['CF.CASH_CLOSING']}")  # fmt: skip

    fiscal_year = next(y for y in owner.call("GET", f"{base}/fiscal-years")
                       if y["start_date"] == books.fiscal_year_start.isoformat())  # fmt: skip
    retained = next(a for a in owner.call("GET", f"{base}/accounts") if a["code"] == "3200")
    closing = owner.call("POST", f"{base}/fiscal-years/{fiscal_year['id']}/close",
                         {"retained_earnings_account_id": retained["id"]}, 201)  # fmt: skip
    reviewer.call("POST", f"{base}/journal-entries/{closing['id']}/approve", {})
    reviewer.call("POST", f"{base}/journal-entries/{closing['id']}/post", {})
    year_end = owner.call("GET", f"{base}/fiscal-years/{fiscal_year['id']}/close")
    if year_end["status"] != "CLOSED" or not all(c["ok"] for c in year_end["checks"]):
        raise DemoStepError(f"Year-end close failed its checks: {year_end}")
    after = reviewer.call(
        "GET", f"{base}/statements?date_from={books.fiscal_year_start}&date_to={december}"
        "&comparative=none")  # fmt: skip
    closed = {r["code"]: r["current"] for r in after["balance_sheet"]["rows"]}
    unchanged = {r["code"]: r["current"] for r in after["profit_and_loss"]["rows"]}
    if (not after["ok"] or unchanged["PL.RESULT"] != result["PL.RESULT"]
            or closed["BS.EQUITY.RETAINED"] != result["PL.RESULT"]
            or closed["BS.TOTAL_ASSETS"] != totals["BS.TOTAL_ASSETS"]):  # fmt: skip
        raise DemoStepError(f"Statements after the close do not agree: {after}")
    step(f"year {year} closed by the reviewed closing entry: profit {result['PL.RESULT']} moved "
         f"to retained earnings; income and expense accounts are zero and the {year + 1} opening "
         "balances equal the closing balance sheet")  # fmt: skip

    check = owner.call("POST", f"/api/w/{slug}/integrity-checks", None, 201)
    if check["status"] != "PASSED":
        raise DemoStepError(f"Integrity check {check['status']}: {check['results']}")
    step(
        "integrity checks passed (balance, snapshots, gapless numbering, closed years, audit chain)"
    )

    forecast = _cash_forecast(owner, base, year)
    first = forecast["first_shortfall"]
    step(
        f"13-week cash forecast from {forecast['as_of']}: opening cash "
        f"{forecast['opening_cash']}, week 13 closing {forecast['weeks'][-1]['closing']}; "
        + (
            f"first shortfall below the minimum on {first['date']}"
            if first
            else "no shortfall below the minimum"
        )
        + f"; run {forecast['status']} and reproducible"
    )

    budget = _budget(owner, accountant, base, year)
    sales = next(ln for ln in budget["lines"] if ln["taxonomy_code"] == "REV.SALES")
    step(
        f"budget {year + 1} prepared by the accountant, approved by the owner: total "
        f"{budget['total']}; sales {sales['total']} phased like {year} ({sales['phasing_note']})"
    )

    goals = _goals(owner, base, year)
    step(f"{len(goals)} sample goals for {year + 1} set with frozen {year} baselines and "
         "evaluated: " + "; ".join(f"{g['name']} {g['status']}" for g in goals))  # fmt: skip
    raised = owner.call("GET", f"{base}/alerts")
    step(f"{len(raised)} in-app alert(s) raised by the evaluations: "
         + "; ".join(a["title"] for a in raised))  # fmt: skip
    period = {"preset": "YTD", "month": f"{year}-12-01", "comparison": "BUDGET"}
    owner.call("POST", f"{base}/dashboard/refresh", period)
    query = "&".join(f"{k}={v}" for k, v in period.items())
    board = owner.call("GET", f"{base}/dashboard?{query}")
    shown = {w["type"]: w["status"] for w in board["widgets"]}
    cards = next(w for w in board["widgets"] if w["type"] == "kpis")["data"].get("cards", [])
    step(f"CFO dashboard for {year} year to date: " + ", ".join(f"{k} {v}" for k, v in
         shown.items()) + f"; {len(cards)} KPI cards")  # fmt: skip
    worth = _personal(owner, year)
    valued = ", including a home valuation (estimate)" if worth["includes_valuations"] else ""
    goal_list = "; ".join(f"{g['name']} {g['status']}" for g in worth["goals"])
    step(f"personal workspace (separate books): net worth {worth['net_worth']} on "
         f"{worth['as_of']}{valued}")  # fmt: skip
    step(f"personal budget (groceries 400 a month) and {len(worth['goals'])} goals: {goal_list}; "
         f"12-month projection from cash {worth['projection']['opening_cash']}")  # fmt: skip
    repaid = through_workflow(
        draft(
            date(year + 1, 1, 15),
            "Director loan repaid (Demo)",
            [("2020", Decimal("1500.00"), Decimal("0")), (BANK, Decimal("0"), Decimal("1500.00"))],
        )
    )
    hint = _counterpart(owner, worth, base, by_code["2020"], repaid["accounting_date"])
    step(
        f"counterpart hint (opt-in): {hint['suggested']} business payment to the owner "
        f"suggested, {hint['confirmed']} recorded in the personal books only after confirmation"
    )
    refused = owner.call("GET", f"/api/w/{slug}/portfolio?month={year}-12-01", expect=403)
    step(f"client portfolio refused in a business workspace (firms only): {refused['detail']}")
    engaged = _engagement(owner, host, slug, year)
    step(f"engagement grant: {engaged['firm']} let in as {' + '.join(engaged['roles'])}, "
         f"{engaged['clients']} client in the firm portfolio; after the owner revoked it, the "
         "firm's next request is refused and the client is gone from its portfolio")  # fmt: skip

    run = _fixed_assets(accountant, base, by_code, year)
    posted_dep = through_workflow({"id": run["entry_id"]})
    step(f"fixed-asset register: 2 assets; depreciation for {year + 1}-01 prepared by the "
         f"accountant as a draft entry of {run['total']}, then approved and posted by the "
         f"reviewer as {posted_dep['journal']}-{posted_dep['entry_no']}")  # fmt: skip
    plan = _assumptions(owner, base, year)
    margin, dso = plan["gross_margin"], plan["dso"]
    step(f"assumptions for {year + 1}-{year + 2} started from {year} actuals (revenue +10% a "
         f"year) and approved: gross margin {margin}%, DSO {dso} days")  # fmt: skip
    projected = _projection(owner, base, plan["id"])
    step(f"three-statement projection {year + 1}-{year + 2}: {projected['status']}, "
         f"{projected['checks']} invariants hold, published; {year + 2}: revenue "
         f"{projected['revenue']}, net income {projected['net_income']}, closing cash "
         f"{projected['cash']}")  # fmt: skip
    year_ahead = owner.call("GET", f"{base}/outlook?day={year + 1}-06-30")
    kinds = [c["nature"] for c in year_ahead["columns"] if c["granularity"] == "MONTH"]
    step(f"full-year outlook {year + 1}: {kinds.count('ACTUAL')} actual and "
         f"{kinds.count('FORECAST')} forecast months from the published projection; revenue "
         f"{year_ahead['rows']['PL.REVENUE'][-1]}")  # fmt: skip
    rolled = _rolling(owner, base, plan["id"])
    step(f"rolling forecast: the next {rolled['horizon']} months from the approved assumptions, "
         f"{rolled['latest']['status']}, current; re-run hourly when the books move")  # fmt: skip
    exported = _export_and_deletion(owner, slug)
    step(f"full export of the workspace: {exported['tables']} tables and {exported['files']} "
         "document file(s), every file matching its count and hash in the manifest; a spare "
         f"workspace's deletion confirmed with {exported['grace_days']} days' grace, then "
         "cancelled")  # fmt: skip

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
        forecast=forecast,
        steps=steps,
        statements=statements,
    )


__all__ = ["DemoClient", "DemoResult", "DemoStepError", "run"]
