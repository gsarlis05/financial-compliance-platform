"""Account → taxonomy mapping and the mapping-completeness check (M2-6, AC-M2-6).

Accounts and balances come from the ``reporting`` gateway (ADR-0007). Each change supersedes the
current mapping row and adds a new one; nothing is overwritten (history: ``mapping_history``).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from fcp.core.errors import NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.reporting.api import AccountRef, account_activity, accounts
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import AccountTaxonomyMap, TaxonomyLine
from .taxonomy import DEFAULT_TAXONOMY, default_map

ZERO = Decimal(0)


def taxonomy_lines(
    ctx: WorkspaceContext, entity_id: UUID, version: str = DEFAULT_TAXONOMY
) -> list[TaxonomyLine]:
    get_entity(ctx, entity_id, "ledger.account.read")
    return list(TaxonomyLine.objects.filter(version_id=version).order_by("order"))


def current_mapping(entity_id: UUID, version: str = DEFAULT_TAXONOMY) -> dict[UUID, TaxonomyLine]:
    """account_id -> its current taxonomy line (callers have authorised the read)."""
    rows = AccountTaxonomyMap.objects.select_related("line").filter(
        legal_entity_id=entity_id, taxonomy_version_id=version, superseded_at__isnull=True
    )
    return {r.account_id: r.line for r in rows}


@dataclass(frozen=True)
class MappingRow:
    account: AccountRef
    line: TaxonomyLine | None
    net_debit: Decimal  # posted debits minus credits up to the date asked for
    has_activity: bool


def mapping_rows(
    ctx: WorkspaceContext, entity_id: UUID, *, as_of: date, version: str = DEFAULT_TAXONOMY
) -> list[MappingRow]:
    get_entity(ctx, entity_id, "ledger.account.read")
    mapped = current_mapping(entity_id, version)
    activity = account_activity(ctx, entity_id, as_of=as_of)
    rows = []
    for account in accounts(ctx, entity_id):
        if not account.is_postable:
            continue
        act = activity.get(account.id)
        rows.append(MappingRow(account, mapped.get(account.id),
                               act.net_debit if act else ZERO,
                               act.has_activity if act else False))  # fmt: skip
    return rows


@dataclass(frozen=True)
class Completeness:
    as_of: date
    version: str
    mapped: int
    unmapped_blocking: list[MappingRow]  # non-zero balance: blocks statements (doc 05 §7)
    unmapped_warning: list[MappingRow]  # activity but zero balance (e.g. cleared suspense)
    unmapped_idle: int  # no activity at all

    @property
    def complete(self) -> bool:
        return not self.unmapped_blocking


def completeness(
    ctx: WorkspaceContext, entity_id: UUID, *, as_of: date, version: str = DEFAULT_TAXONOMY
) -> Completeness:
    rows = mapping_rows(ctx, entity_id, as_of=as_of, version=version)
    unmapped = [r for r in rows if r.line is None]
    return Completeness(
        as_of=as_of,
        version=version,
        mapped=len(rows) - len(unmapped),
        unmapped_blocking=[r for r in unmapped if r.net_debit != 0],
        unmapped_warning=[r for r in unmapped if r.net_debit == 0 and r.has_activity],
        unmapped_idle=sum(1 for r in unmapped if not r.has_activity),
    )


def _account(ctx: WorkspaceContext, entity_id: UUID, account_id: UUID) -> AccountRef:
    found = next((a for a in accounts(ctx, entity_id) if a.id == account_id), None)
    if found is None:
        raise NotFoundError("Account not found.")
    return found


def _audit(ctx: WorkspaceContext, entity_id: UUID, subject_id: object, action: str,
           changes: dict[str, Any]) -> None:  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=action,
          subject_type="account_mapping", subject_id=subject_id, entity_id=entity_id,
          changes=changes)  # fmt: skip


def _supersede_and_add(
    ctx: WorkspaceContext, entity_id: UUID, account: AccountRef, line: TaxonomyLine | None,
    version: str,
) -> bool:  # fmt: skip
    current = (
        AccountTaxonomyMap.objects.select_for_update()
        .filter(
            legal_entity_id=entity_id,
            account_id=account.id,
            taxonomy_version_id=version,
            superseded_at__isnull=True,
        )
        .first()
    )
    if (current.line_id if current else None) == (line.id if line else None):
        return False
    if current is not None:
        current.superseded_at = timezone.now()
        current.save(update_fields=["superseded_at"])
    if line is not None:
        AccountTaxonomyMap.objects.create(
            tenant=ctx.tenant, legal_entity_id=entity_id, account_id=account.id,
            taxonomy_version_id=version, line=line, created_by=ctx.user,
        )  # fmt: skip
    return True


def _line(version: str, code: str, field: str = "line_code") -> TaxonomyLine:
    line: TaxonomyLine | None = TaxonomyLine.objects.filter(version_id=version, code=code).first()
    if line is None:
        raise ValidationFailedError("Unknown taxonomy line.", field_errors={field: ["not found"]})
    return line


@transaction.atomic
def set_mapping(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, line_code: str | None,
    version: str = DEFAULT_TAXONOMY,
) -> TaxonomyLine | None:  # fmt: skip
    """Map an account to a line (or unmap it with ``None``). The line must accept the account
    type: assets, liabilities and equity go to balance-sheet lines, income and expenses to P&L."""
    get_entity(ctx, entity_id, "ledger.account.manage")
    account = _account(ctx, entity_id, account_id)
    if not account.is_postable:
        raise ValidationFailedError(
            "Headings are not mapped; map the postable accounts under them.",
            field_errors={"account_id": ["heading"]},
        )
    line = _line(version, line_code) if line_code else None
    if line is not None and not line.accepts(account.type):
        raise ValidationFailedError(
            f"{line.code} ({line.name}) does not accept {account.type.lower()} accounts.",
            field_errors={"line_code": ["incompatible with the account type"]},
        )
    before = current_mapping(entity_id, version).get(account.id)
    if _supersede_and_add(ctx, entity_id, account, line, version):
        _audit(ctx, entity_id, account.id, "metrics.mapping.changed",
               {"account": account.code, "taxonomy": version,
                "before": before.code if before else None,
                "after": line.code if line else None})  # fmt: skip
    return line


@transaction.atomic
def apply_defaults(
    ctx: WorkspaceContext, entity_id: UUID, template: str, version: str = DEFAULT_TAXONOMY
) -> int:
    """Map still-unmapped accounts using the template's default map. Existing mappings are kept."""
    get_entity(ctx, entity_id, "ledger.account.manage")
    defaults = default_map(template)
    if not defaults:
        raise ValidationFailedError(
            "No default mapping for this template.", field_errors={"template": ["unknown"]}
        )
    mapped = current_mapping(entity_id, version)
    lines = {ln.code: ln for ln in TaxonomyLine.objects.filter(version_id=version)}
    applied = []
    for account in accounts(ctx, entity_id):
        code = defaults.get(account.code)
        line = lines.get(code) if code else None
        if (
            account.is_postable
            and account.id not in mapped
            and line is not None
            and line.accepts(account.type)
            and _supersede_and_add(ctx, entity_id, account, line, version)
        ):
            applied.append([account.code, line.code])
    if applied:
        _audit(ctx, entity_id, template, "metrics.mapping.defaults_applied",
               {"taxonomy": version, "template": template, "mapped": applied})  # fmt: skip
    return len(applied)


def mapping_history(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, version: str = DEFAULT_TAXONOMY
) -> list[AccountTaxonomyMap]:
    get_entity(ctx, entity_id, "ledger.account.read")
    _account(ctx, entity_id, account_id)
    return list(
        AccountTaxonomyMap.objects.select_related("line")
        .filter(legal_entity_id=entity_id, account_id=account_id, taxonomy_version_id=version)
        .order_by("created_at")
    )
