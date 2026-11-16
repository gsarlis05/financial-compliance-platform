"""Chart of accounts (backlog M1-6)."""

import json
from dataclasses import dataclass
from importlib import resources
from typing import Any
from uuid import UUID

from django.db import transaction

from fcp.core.errors import ConflictError, NotFoundError, ValidationFailedError
from fcp.modules.audit_log.api import record as audit
from fcp.modules.tenancy.api import WorkspaceContext, get_entity

from .models import Account, JournalLine

TEMPLATES = ("cy_business", "personal")


@dataclass(frozen=True)
class AccountInput:
    code: str
    name: str
    type: str
    name_el: str = ""
    parent_code: str | None = None
    is_postable: bool = True
    currency: str = ""
    control_type: str = ""


def _audit(ctx: WorkspaceContext, account: Account, action: str, changes: dict[str, Any]) -> None:
    audit(
        tenant_id=ctx.tenant.id,
        actor_user_id=ctx.user.id,
        action=action,
        subject_type="account",
        subject_id=account.id,
        entity_id=account.legal_entity_id,
        changes=changes,
    )


def list_accounts(ctx: WorkspaceContext, entity_id: UUID) -> list[Account]:
    entity = get_entity(ctx, entity_id, "ledger.account.read")
    return list(Account.objects.filter(legal_entity=entity).order_by("code"))


def get_account(ctx: WorkspaceContext, entity_id: UUID, account_id: UUID) -> Account:
    entity = get_entity(ctx, entity_id, "ledger.account.read")
    account: Account | None = Account.objects.filter(legal_entity=entity, id=account_id).first()
    if account is None:
        raise NotFoundError("Account not found.")
    return account


_CONTROL_TYPES = {
    Account.Control.RECEIVABLE: Account.Type.ASSET,
    Account.Control.PAYABLE: Account.Type.LIABILITY,
}


def _validate_control(control_type: str, account_type: str, is_postable: bool) -> None:
    if not control_type:
        return
    if control_type not in _CONTROL_TYPES:
        raise ValidationFailedError(
            "Control type must be RECEIVABLE or PAYABLE.",
            field_errors={"control_type": ["invalid"]},
        )
    if _CONTROL_TYPES[Account.Control(control_type)] != account_type or not is_postable:
        raise ValidationFailedError(
            "Receivables control accounts are postable assets; payables are postable liabilities.",
            field_errors={"control_type": ["does not fit the account type"]},
        )


def _validate(data: AccountInput) -> None:
    if data.type not in Account.Type.values:
        raise ValidationFailedError("Unknown account type.", field_errors={"type": ["invalid"]})
    _validate_control(data.control_type, data.type, data.is_postable)
    code = data.code.strip().upper()
    if not code or len(code) > 20 or not all(c.isalnum() or c in ".-" for c in code):
        raise ValidationFailedError(
            "Account codes use letters, digits, '.' and '-' (up to 20 characters).",
            field_errors={"code": ["invalid format"]},
        )


@transaction.atomic
def create_account(ctx: WorkspaceContext, entity_id: UUID, data: AccountInput) -> Account:
    entity = get_entity(ctx, entity_id, "ledger.account.manage")
    _validate(data)
    code = data.code.strip().upper()
    if Account.objects.filter(legal_entity=entity, code=code).exists():
        raise ConflictError(f"Account code {code} already exists.")
    parent = None
    if data.parent_code:
        parent = Account.objects.filter(legal_entity=entity, code=data.parent_code.upper()).first()
        if parent is None:
            raise ValidationFailedError(
                "Parent account not found.", field_errors={"parent_code": ["not found"]}
            )
        if parent.is_postable:
            raise ValidationFailedError(
                "A parent must be a heading (non-postable) account.",
                field_errors={"parent_code": ["is postable"]},
            )
        if parent.type != data.type:
            raise ValidationFailedError(
                "An account must have the same type as its parent heading.",
                field_errors={"type": ["differs from parent"]},
            )
    account = Account.objects.create(
        tenant=ctx.tenant,
        legal_entity=entity,
        code=code,
        name=data.name.strip(),
        name_el=data.name_el.strip(),
        type=data.type,
        normal_side=Account.NORMAL_SIDE[Account.Type(data.type)],
        parent=parent,
        is_postable=data.is_postable,
        currency=data.currency.upper(),
        control_type=data.control_type,
        created_by=ctx.user,
    )
    _audit(ctx, account, "ledger.account.created",
           {"code": code, "name": account.name, "type": data.type,
            "parent_code": data.parent_code, "is_postable": data.is_postable,
            "control_type": data.control_type})  # fmt: skip
    return account


@transaction.atomic
def update_account(  # noqa: PLR0913 - keyword-only optional fields
    ctx: WorkspaceContext,
    entity_id: UUID,
    account_id: UUID,
    *,
    name: str | None = None,
    name_el: str | None = None,
    status: str | None = None,
    control_type: str | None = None,
) -> Account:
    """Names, status and (until the first posting) the control type can change; code, type and
    hierarchy cannot (they carry history)."""
    get_entity(ctx, entity_id, "ledger.account.manage")
    account = get_account(ctx, entity_id, account_id)
    before = {"name": account.name, "name_el": account.name_el, "status": account.status,
              "control_type": account.control_type}  # fmt: skip
    if status is not None and status not in Account.Status.values:
        raise ValidationFailedError("Unknown status.", field_errors={"status": ["invalid"]})
    if control_type is not None and control_type != account.control_type:
        _validate_control(control_type, account.type, account.is_postable)
        if JournalLine.objects.filter(account=account, entry__status="POSTED").exists():
            raise ConflictError(
                "The control type cannot change once the account has postings; "
                "open a new control account instead."
            )
        account.control_type = control_type
    account.name = name.strip() if name is not None else account.name
    account.name_el = name_el.strip() if name_el is not None else account.name_el
    account.status = status or account.status
    account.save(update_fields=["name", "name_el", "status", "control_type"])
    after = {"name": account.name, "name_el": account.name_el, "status": account.status,
             "control_type": account.control_type}  # fmt: skip
    if after != before:
        _audit(ctx, account, "ledger.account.updated", {"before": before, "after": after})
    return account


def load_template(key: str) -> dict[str, Any]:
    if key not in TEMPLATES:
        raise ValidationFailedError("Unknown template.", field_errors={"template": ["invalid"]})
    text = (
        resources.files("fcp.modules.ledger").joinpath(f"templates/{key}.json").read_text("utf-8")
    )
    data: dict[str, Any] = json.loads(text)
    return data


@transaction.atomic
def apply_template(ctx: WorkspaceContext, entity_id: UUID, key: str) -> list[Account]:
    """Create the template's accounts for an entity whose chart of accounts is still empty."""
    entity = get_entity(ctx, entity_id, "ledger.account.manage")
    if Account.objects.filter(legal_entity=entity).exists():
        raise ConflictError("This entity already has accounts; templates apply to an empty chart.")
    created = []
    for row in load_template(key)["accounts"]:
        created.append(
            create_account(
                ctx,
                entity_id,
                AccountInput(
                    code=row["code"],
                    name=row["name"],
                    name_el=row.get("name_el", ""),
                    type=row["type"],
                    parent_code=row.get("parent"),
                    is_postable=row.get("postable", True),
                    control_type=row.get("control", ""),
                ),
            )
        )
    return created
