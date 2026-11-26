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
from fcp.modules.tenancy.api import workspace_ctx

from . import services, templates
from .tables import MAX_BYTES

__all__ = ["router"]

router = Router(tags=["onboarding"])
BASE = "/w/{slug}/entities/{uuid:entity_id}"
Kind = Literal["chart", "counterparties", "opening-balances", "open-items"]
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
    accounts: list[str]
    counterparties: list[str]
    skipped: list[str]
    lines: list[ImportLineOut]
    total_debit: str
    total_credit: str
    entry_id: UUID | None
    files: dict[str, str]


def _out(found: services.Outcome) -> ImportOutcomeOut:
    return ImportOutcomeOut(
        kind=found.kind, committed=found.committed, rows=found.rows,
        problems=[ImportProblemOut(file=p.file, row=p.row, column=p.column, message=p.message)
                  for p in found.problems],
        warnings=found.warnings,
        unknown_accounts=[ImportUnknownAccountOut(code=u.code, name=u.name, rows=list(u.rows))
                          for u in found.unknown_accounts],
        accounts=found.accounts, counterparties=found.counterparties, skipped=found.skipped,
        lines=[ImportLineOut(account_code=ln.account_code, account_name=ln.account_name,
                             debit=f"{ln.debit:.2f}", credit=f"{ln.credit:.2f}",
                             counterparty_code=ln.counterparty_code, reference=ln.reference,
                             due_date=ln.due_date) for ln in found.lines],
        total_debit=f"{found.total_debit:.2f}", total_credit=f"{found.total_credit:.2f}",
        entry_id=found.entry_id, files=found.files,
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
    workspace_ctx(request, slug, entity_id)
    if format == "csv":
        response = HttpResponse(templates.as_csv(kind), content_type="text/csv; charset=utf-8")
    else:
        response = HttpResponse(templates.as_workbook(kind), content_type=XLSX)
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


@router.post(f"{BASE}/imports/opening-balances", response=ImportOutcomeOut)
@requires("ledger.entry.create")
def import_opening_balances(  # noqa: PLR0913, PLR0917 - the form's fields
    request: HttpRequest, slug: str, entity_id: UUID, file: File[UploadedFile],
    as_of: Form[date], open_items: File[UploadedFile | None] = None,
    account_map: Form[str] = "{}", commit: Form[bool] = False,
) -> ImportOutcomeOut:  # fmt: skip
    """The opening trial balance (with the open invoices behind the receivables and payables) as
    one draft entry dated ``as_of``. ``account_map``: a JSON object from a file's account code to
    a chart account code, for accounts the chart does not have."""
    ctx = workspace_ctx(request, slug, entity_id)
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
    return _out(services.import_opening_balances(
        ctx, entity_id, _upload(file), as_of=as_of,
        open_items=_upload(open_items) if open_items is not None else None,
        account_map=mapping, commit=commit,
    ))  # fmt: skip
