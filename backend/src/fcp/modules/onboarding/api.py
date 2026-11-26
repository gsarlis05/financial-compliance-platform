"""Public interface of the ``onboarding`` module: bringing existing books in (R-2, #245).

Each import is sent first with ``commit=false`` (a preview: every problem listed, nothing kept),
then with ``commit=true``. A commit with any problem creates nothing and returns the problems.
"""

import json
from datetime import date
from typing import Literal
from uuid import UUID

from django.http import HttpRequest, HttpResponse
from ninja import File, Form, Router, Schema
from ninja.files import UploadedFile

from fcp.core.api.permissions import requires
from fcp.core.errors import ValidationFailedError
from fcp.modules.reporting.api import books_start
from fcp.modules.tenancy.api import workspace_ctx

from . import opening, prior, services, templates
from .tables import MAX_BYTES

__all__ = ["router"]

router = Router(tags=["onboarding"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
Kind = Literal["chart", "counterparties", "opening-balances", "open-items", "prior-year"]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ImportProblemOut(Schema):
    file: str
    row: int
    column: str
    message: str


class ImportUnknownAccountOut(Schema):
    code: str
    name: str
    rows: list[int]


class ImportUnknownPartyOut(Schema):
    name: str
    side: str
    rows: list[int]


class ImportPresetOut(Schema):
    key: str
    name: str
    day_first: bool
    status: str
    note: str


class ImportLineOut(Schema):
    account_code: str
    account_name: str
    debit: str
    credit: str
    counterparty_code: str
    reference: str
    due_date: date | None


class ImportOutcomeOut(Schema):
    kind: str
    committed: bool
    rows: int
    problems: list[ImportProblemOut]
    warnings: list[str]
    unknown_accounts: list[ImportUnknownAccountOut]
    unknown_counterparties: list[ImportUnknownPartyOut]
    accounts: list[str]
    counterparties: list[str]
    skipped: list[str]
    lines: list[ImportLineOut]
    total_debit: str
    total_credit: str
    entry_id: UUID | None
    files: dict[str, str]
    months: list[str]


def _out(found: services.Outcome) -> ImportOutcomeOut:
    return ImportOutcomeOut(
        kind=found.kind, committed=found.committed, rows=found.rows,
        problems=[ImportProblemOut(file=p.file, row=p.row, column=p.column, message=p.message)
                  for p in found.problems],
        warnings=found.warnings,
        unknown_accounts=[ImportUnknownAccountOut(code=u.code, name=u.name, rows=list(u.rows))
                          for u in found.unknown_accounts],
        unknown_counterparties=[ImportUnknownPartyOut(name=u.name, side=u.side, rows=list(u.rows))
                                for u in found.unknown_counterparties],
        accounts=found.accounts, counterparties=found.counterparties, skipped=found.skipped,
        lines=[ImportLineOut(account_code=ln.account_code, account_name=ln.account_name,
                             debit=f"{ln.debit:.2f}", credit=f"{ln.credit:.2f}",
                             counterparty_code=ln.counterparty_code, reference=ln.reference,
                             due_date=ln.due_date) for ln in found.lines],
        total_debit=f"{found.total_debit:.2f}", total_credit=f"{found.total_credit:.2f}",
        entry_id=found.entry_id, files=found.files, months=found.months,
    )  # fmt: skip


def _upload(file: UploadedFile) -> services.Upload:
    return services.Upload(name=(file.name or "file")[-120:], data=file.read(MAX_BYTES + 1))


@router.get(f"{BASE}/imports/templates/{{kind}}")
@requires("ledger.account.read")
def import_template(
    request: HttpRequest, slug: str, entity_id: UUID, kind: Kind,
    format: Literal["xlsx", "csv"] = "xlsx",
) -> HttpResponse:  # fmt: skip
    """An empty import template, as an Excel workbook (with a "How to fill in" sheet) or CSV."""
    ctx = workspace_ctx(request, slug, entity_id)
    months = prior.template_months(books_start(ctx, entity_id)) if kind == "prior-year" else ()
    if format == "csv":
        response = HttpResponse(templates.as_csv(kind, months),
                                content_type="text/csv; charset=utf-8")  # fmt: skip
    else:
        response = HttpResponse(templates.as_workbook(kind, months), content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="import-{kind}.{format}"'
    return response


@router.post(f"{BASE}/imports/chart", response=ImportOutcomeOut)
@requires("ledger.account.manage")
def import_chart(
    request: HttpRequest, slug: str, entity_id: UUID, file: File[UploadedFile],
    commit: Form[bool] = False,
) -> ImportOutcomeOut:  # fmt: skip
    """Accounts from the chart template; accounts already in the chart, identical, are skipped."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.import_chart(ctx, entity_id, _upload(file), commit=commit))


@router.post(f"{BASE}/imports/counterparties", response=ImportOutcomeOut)
@requires("registers.counterparty.manage")
def import_counterparties(
    request: HttpRequest, slug: str, entity_id: UUID, file: File[UploadedFile],
    commit: Form[bool] = False,
) -> ImportOutcomeOut:  # fmt: skip
    """Customers and suppliers from the template; identical ones already set up are skipped."""
    ctx = workspace_ctx(request, slug, entity_id)
    return _out(services.import_counterparties(ctx, entity_id, _upload(file), commit=commit))


@router.get(f"{BASE}/imports/presets", response=list[ImportPresetOut])
@requires("ledger.account.read")
def import_presets(request: HttpRequest, slug: str, entity_id: UUID) -> list[ImportPresetOut]:
    """Accounting packages whose report exports are read by their column names; a preset only
    sets the date order. Each is to be confirmed against a real export."""
    workspace_ctx(request, slug, entity_id)
    return [ImportPresetOut(key=p.key, name=p.name, day_first=p.day_first, status=p.status,
                            note=p.note) for p in templates.PRESETS.values()]  # fmt: skip


def _mapping(account_map: str) -> dict[str, str]:
    try:
        mapping = json.loads(account_map or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationFailedError("The account mapping is not valid JSON.",
                                    field_errors={"account_map": ["invalid"]}) from exc  # fmt: skip
    if not isinstance(mapping, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()
    ):
        raise ValidationFailedError("The account mapping must map codes to codes.",
                                    field_errors={"account_map": ["invalid"]})  # fmt: skip
    return mapping


@router.post(f"{BASE}/imports/opening-balances", response=ImportOutcomeOut)
@requires("ledger.entry.create")
def import_opening_balances(  # noqa: PLR0913, PLR0917 - the form's fields
    request: HttpRequest, slug: str, entity_id: UUID, file: File[UploadedFile],
    as_of: Form[date], open_items: File[UploadedFile | None] = None,
    aged_receivables: File[UploadedFile | None] = None,
    aged_payables: File[UploadedFile | None] = None,
    account_map: Form[str] = "{}", results_account: Form[str] = "",
    date_order: Form[Literal["day", "month"]] = "day",
    create_counterparties: Form[bool] = False, commit: Form[bool] = False,
) -> ImportOutcomeOut:  # fmt: skip
    """The opening trial balance (the template, an accountant's or a package's trial balance) as
    one draft entry dated ``as_of``, with the open invoices behind the receivables and payables
    (the template, or a package's aged receivables and payables reports).

    - ``account_map``: a JSON object from a file's account (code, or name when there is no code)
      to a chart account code;
    - ``results_account``: an equity account to carry the income and expense balances into;
    - ``date_order``: how the files' dates are written (day or month first);
    - ``create_counterparties``: create the customers and suppliers the reports name that are
      not set up yet."""
    ctx = workspace_ctx(request, slug, entity_id)
    optional = {"open_items": open_items, "aged_receivables": aged_receivables,
                "aged_payables": aged_payables}  # fmt: skip
    req = opening.OpeningRequest(
        as_of=as_of, trial_balance=_upload(file),
        **{k: _upload(v) for k, v in optional.items() if v is not None},
        account_map=_mapping(account_map), results_account=results_account.strip(),
        day_first=date_order == "day", create_counterparties=create_counterparties,
    )  # fmt: skip
    return _out(opening.import_opening_balances(ctx, entity_id, req, commit=commit))


@router.post(f"{BASE}/imports/prior-year", response=ImportOutcomeOut)
@requires("ledger.entry.create")
def import_prior_year(  # noqa: PLR0913, PLR0917 - the form's fields
    request: HttpRequest, slug: str, entity_id: UUID, file: File[UploadedFile],
    account_map: Form[str] = "{}",
    profit_and_loss: Form[Literal["year_to_date", "month"]] = "year_to_date",
    commit: Form[bool] = False,
) -> ImportOutcomeOut:  # fmt: skip
    """The months before the books start, from a monthly trial balance, kept as comparatives
    (no entries). ``profit_and_loss``: income and expense written year to date (as a monthly
    trial balance shows them) or as each month's own amount."""
    ctx = workspace_ctx(request, slug, entity_id)
    req = prior.PriorRequest(upload=_upload(file), account_map=_mapping(account_map),
                             year_to_date=profit_and_loss == "year_to_date")  # fmt: skip
    return _out(prior.import_prior_year(ctx, entity_id, req, commit=commit))
