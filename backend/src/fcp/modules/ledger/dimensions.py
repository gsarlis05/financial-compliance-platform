"""Analytical dimensions: departments, projects, cost centres (backlog M2-1, AC-M2-1).

A legal entity defines dimensions and their values. Journal lines carry at most one value per
dimension. Per account, a dimension can be REQUIRED (every posted line needs a value) or BLOCKED
(no line may carry one); otherwise it is optional. Drafts may be incomplete; the rules apply from
submission and are enforced again by the database at posting (migration 0010).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import transaction

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .errors import DimensionError, DimensionRequiredError
from .models import Account, AccountDimensionRule, Dimension, DimensionValue, JournalLine

_CODE_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")


def _code(value: str, field: str = "code", max_length: int = 20) -> str:
    code = value.strip().upper()
    if not code or len(code) > max_length or not set(code) <= _CODE_CHARS:
        raise ValidationFailedError(
            f"Codes use letters, digits, '.', '-' and '_' (up to {max_length} characters).",
            field_errors={field: ["invalid format"]},
        )
    return code


def _audit(ctx: WorkspaceContext, subject_type: str, subject_id: UUID, entity_id: UUID,
           action: str, changes: dict[str, Any]) -> None:  # fmt: skip
    audit(tenant_id=ctx.tenant.id, actor_user_id=ctx.user.id, action=action,
          subject_type=subject_type, subject_id=subject_id, entity_id=entity_id,
          changes=changes)  # fmt: skip


# --- dimensions and values -----------------------------------------------------------------------


def list_dimensions(ctx: WorkspaceContext, entity_id: UUID) -> list[Dimension]:
    entity = get_entity(ctx, entity_id, "ledger.account.read")
    return list(
        Dimension.objects.filter(legal_entity=entity).prefetch_related("values").order_by("code")
    )


def get_dimension(ctx: WorkspaceContext, entity_id: UUID, dimension_id: UUID) -> Dimension:
    entity = get_entity(ctx, entity_id, "ledger.account.read")
    found: Dimension | None = Dimension.objects.filter(legal_entity=entity, id=dimension_id).first()
    if found is None:
        raise NotFoundError("Dimension not found.")
    return found


@transaction.atomic
def create_dimension(
    ctx: WorkspaceContext, entity_id: UUID, *, code: str, name: str, kind: str
) -> Dimension:
    entity = get_entity(ctx, entity_id, "ledger.account.manage")
    code = _code(code)
    if kind not in Dimension.Kind.values:
        raise ValidationFailedError("Unknown dimension kind.", field_errors={"kind": ["invalid"]})
    if Dimension.objects.filter(legal_entity=entity, code=code).exists():
        raise ConflictError(f"Dimension code {code} already exists.")
    dimension = Dimension.objects.create(
        tenant=ctx.tenant, legal_entity=entity, code=code, name=name.strip(), kind=kind,
        created_by=ctx.user,
    )  # fmt: skip
    _audit(ctx, "dimension", dimension.id, entity.id, "ledger.dimension.created",
           {"code": code, "name": dimension.name, "kind": kind})  # fmt: skip
    return dimension


@transaction.atomic
def update_dimension(
    ctx: WorkspaceContext, entity_id: UUID, dimension_id: UUID, *,
    name: str | None = None, status: str | None = None,
) -> Dimension:  # fmt: skip
    """Name and status can change; code and kind cannot (posted lines refer to them)."""
    get_entity(ctx, entity_id, "ledger.account.manage")
    dimension = get_dimension(ctx, entity_id, dimension_id)
    if status is not None and status not in Dimension.Status.values:
        raise ValidationFailedError("Unknown status.", field_errors={"status": ["invalid"]})
    before = {"name": dimension.name, "status": dimension.status}
    dimension.name = name.strip() if name is not None else dimension.name
    dimension.status = status or dimension.status
    dimension.save(update_fields=["name", "status"])
    after = {"name": dimension.name, "status": dimension.status}
    if after != before:
        _audit(ctx, "dimension", dimension.id, dimension.legal_entity_id,
               "ledger.dimension.updated", {"before": before, "after": after})  # fmt: skip
    return dimension


@transaction.atomic
def create_value(
    ctx: WorkspaceContext, entity_id: UUID, dimension_id: UUID, *,
    code: str, name: str, parent_code: str | None = None,
) -> DimensionValue:  # fmt: skip
    get_entity(ctx, entity_id, "ledger.account.manage")
    dimension = get_dimension(ctx, entity_id, dimension_id)
    code = _code(code, max_length=30)
    if DimensionValue.objects.filter(dimension=dimension, code=code).exists():
        raise ConflictError(f"Value code {code} already exists in dimension {dimension.code}.")
    parent = None
    if parent_code:
        parent = DimensionValue.objects.filter(
            dimension=dimension, code=parent_code.strip().upper()
        ).first()
        if parent is None:
            raise ValidationFailedError(
                "Parent value not found in this dimension.",
                field_errors={"parent_code": ["not found"]},
            )
    value = DimensionValue.objects.create(
        tenant=ctx.tenant, dimension=dimension, legal_entity_id=dimension.legal_entity_id,
        code=code, name=name.strip(), parent=parent,
    )  # fmt: skip
    _audit(ctx, "dimension_value", value.id, dimension.legal_entity_id,
           "ledger.dimension_value.created",
           {"dimension": dimension.code, "code": code, "name": value.name,
            "parent_code": parent.code if parent else None})  # fmt: skip
    return value


@transaction.atomic
def update_value(
    ctx: WorkspaceContext, entity_id: UUID, value_id: UUID, *,
    name: str | None = None, status: str | None = None,
) -> DimensionValue:  # fmt: skip
    entity = get_entity(ctx, entity_id, "ledger.account.manage")
    value: DimensionValue | None = (
        DimensionValue.objects.select_related("dimension")
        .filter(legal_entity=entity, id=value_id)
        .first()
    )
    if value is None:
        raise NotFoundError("Dimension value not found.")
    if status is not None and status not in Dimension.Status.values:
        raise ValidationFailedError("Unknown status.", field_errors={"status": ["invalid"]})
    before = {"name": value.name, "status": value.status}
    value.name = name.strip() if name is not None else value.name
    value.status = status or value.status
    value.save(update_fields=["name", "status"])
    after = {"name": value.name, "status": value.status}
    if after != before:
        _audit(ctx, "dimension_value", value.id, entity.id, "ledger.dimension_value.updated",
               {"dimension": value.dimension.code, "code": value.code,
                "before": before, "after": after})  # fmt: skip
    return value


# --- account rules -------------------------------------------------------------------------------


def account_rules(entity_id: UUID, account_ids: Sequence[UUID]) -> dict[UUID, dict[UUID, str]]:
    """{account_id: {dimension_id: rule}} for the given accounts (callers authorise)."""
    result: dict[UUID, dict[UUID, str]] = {}
    for rule in AccountDimensionRule.objects.filter(
        account__legal_entity_id=entity_id, account_id__in=account_ids
    ):
        result.setdefault(rule.account_id, {})[rule.dimension_id] = rule.rule
    return result


@transaction.atomic
def set_account_rules(
    ctx: WorkspaceContext, entity_id: UUID, account_id: UUID, rules: Sequence[tuple[UUID, str]]
) -> list[AccountDimensionRule]:
    """Replace the account's dimension rules. Applies to entries submitted from now on."""
    entity = get_entity(ctx, entity_id, "ledger.account.manage")
    account: Account | None = Account.objects.filter(legal_entity=entity, id=account_id).first()
    if account is None:
        raise NotFoundError("Account not found.")
    dims = {d.id: d for d in Dimension.objects.filter(legal_entity=entity)}
    seen: set[UUID] = set()
    for i, (dimension_id, rule) in enumerate(rules):
        if dimension_id not in dims:
            raise ValidationFailedError(
                "Dimension not found in this entity.",
                field_errors={f"rules.{i}.dimension_id": ["not found"]},
            )
        if rule not in AccountDimensionRule.Rule.values:
            raise ValidationFailedError(
                "Rule must be REQUIRED or BLOCKED.", field_errors={f"rules.{i}.rule": ["invalid"]}
            )
        if dimension_id in seen:
            raise ValidationFailedError(
                "Each dimension can have one rule per account.",
                field_errors={f"rules.{i}.dimension_id": ["duplicate"]},
            )
        seen.add(dimension_id)
    before = sorted(
        (dims[r.dimension_id].code, r.rule)
        for r in AccountDimensionRule.objects.filter(account=account)
        if r.dimension_id in dims
    )
    AccountDimensionRule.objects.filter(account=account).delete()
    created = AccountDimensionRule.objects.bulk_create(
        [
            AccountDimensionRule(tenant=ctx.tenant, account=account, dimension_id=d, rule=r)
            for d, r in rules
        ]
    )
    after = sorted((dims[d].code, r) for d, r in rules)
    if after != before:
        _audit(ctx, "account", account.id, entity.id, "ledger.account.dimension_rules_changed",
               {"code": account.code, "before": before, "after": after})  # fmt: skip
    return created


# --- line tags -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class LineTag:
    dimension: Dimension
    value: DimensionValue


def resolve_tags(
    entity_id: UUID, lines: Sequence[Sequence[UUID]], *, allow_inactive: bool = False
) -> list[list[LineTag]]:
    """Validate the dimension values of each line (structure only: drafts may be incomplete).

    ``lines[i]`` is the list of value ids of line i. Rejects unknown or inactive values, values of
    another entity, and two values of the same dimension on one line. Account rules (REQUIRED and
    BLOCKED) are checked at submission and posting by ``check_rules``.
    """
    wanted = {v for ids in lines for v in ids}
    values = {
        v.id: v
        for v in DimensionValue.objects.select_related("dimension").filter(
            legal_entity_id=entity_id, id__in=wanted
        )
    }
    result: list[list[LineTag]] = []
    for i, ids in enumerate(lines):
        tags: list[LineTag] = []
        used: set[UUID] = set()
        for value_id in ids:
            value = values.get(value_id)
            if value is None:
                raise DimensionError(
                    "The dimension value does not exist in this entity.",
                    field_errors={f"lines.{i}.dimension_value_ids": ["not found"]},
                )
            if not allow_inactive and (
                value.status != Dimension.Status.ACTIVE
                or value.dimension.status != Dimension.Status.ACTIVE
            ):
                raise DimensionError(
                    f"{value.dimension.code} {value.code} is inactive and cannot be used.",
                    field_errors={f"lines.{i}.dimension_value_ids": ["inactive"]},
                )
            if value.dimension_id in used:
                raise DimensionError(
                    f"A line can carry only one {value.dimension.code} value.",
                    field_errors={f"lines.{i}.dimension_value_ids": ["duplicate dimension"]},
                )
            used.add(value.dimension_id)
            tags.append(LineTag(value.dimension, value))
        result.append(tags)
    return result


def check_rules(entity_id: UUID, lines: Sequence[JournalLine]) -> None:
    """Submission and posting: REQUIRED dimensions present, BLOCKED ones absent, values active."""
    rules = account_rules(entity_id, [ln.account_id for ln in lines])
    dims = {d.id: d for d in Dimension.objects.filter(legal_entity_id=entity_id)}
    for ln in sorted(lines, key=lambda x: x.line_no):
        i = ln.line_no - 1
        tags = list(ln.dimension_tags.all())
        tagged = {t.dimension_id for t in tags}
        for dimension_id, rule in rules.get(ln.account_id, {}).items():
            code = dims[dimension_id].code
            if rule == AccountDimensionRule.Rule.REQUIRED and dimension_id not in tagged:
                raise DimensionRequiredError(
                    f"Line {ln.line_no}: account {ln.account.code} requires a {code} value.",
                    field_errors={f"lines.{i}.dimension_value_ids": [f"{code} required"]},
                )
            if rule == AccountDimensionRule.Rule.BLOCKED and dimension_id in tagged:
                raise DimensionError(
                    f"Line {ln.line_no}: account {ln.account.code} does not allow {code}.",
                    field_errors={f"lines.{i}.dimension_value_ids": [f"{code} not allowed"]},
                )
        for t in tags:
            if t.value.status != Dimension.Status.ACTIVE or dims[t.dimension_id].status != (
                Dimension.Status.ACTIVE
            ):
                raise DimensionError(
                    f"Line {ln.line_no}: {dims[t.dimension_id].code} {t.value.code} is inactive.",
                    field_errors={f"lines.{i}.dimension_value_ids": ["inactive"]},
                )
