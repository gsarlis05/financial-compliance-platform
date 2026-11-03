"""Public interface of the ``reporting`` module: the read gateway to historical figures.

ADR-0007: planning and CFO modules (``metrics``, ``cashflow``, ``budgeting``, ...) never import the
ledger; they read actuals only through this module. M2-6 adds account balances; M2-7 adds the
``reporting.actuals`` read model (monthly facts and daily cash).
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID

from ninja import Router

from fcp.modules.ledger.api import account_list, trial_balance_rows
from fcp.modules.tenancy.api import WorkspaceContext

__all__ = ["AccountActivity", "AccountRef", "account_activity", "accounts", "router"]

router = Router(tags=["reporting"])


@dataclass(frozen=True)
class AccountRef:
    id: UUID
    code: str
    name: str
    name_el: str
    type: str
    normal_side: str
    is_postable: bool
    status: str


@dataclass(frozen=True)
class AccountActivity:
    account_id: UUID
    debit_total: Decimal
    credit_total: Decimal

    @property
    def has_activity(self) -> bool:
        return bool(self.debit_total or self.credit_total)

    @property
    def net_debit(self) -> Decimal:
        return self.debit_total - self.credit_total


def accounts(ctx: WorkspaceContext, entity_id: UUID) -> list[AccountRef]:
    """The entity's chart of accounts (requires ``ledger.account.read``)."""
    return [
        AccountRef(a.id, a.code, a.name, a.name_el, a.type, a.normal_side, a.is_postable, a.status)
        for a in account_list(ctx, entity_id)
    ]


def account_activity(
    ctx: WorkspaceContext, entity_id: UUID, *, as_of: date
) -> dict[UUID, AccountActivity]:
    """Posted totals per postable account up to ``as_of`` (requires ``reports.read``)."""
    return {
        r.account_id: AccountActivity(r.account_id, r.debit_total, r.credit_total)
        for r in trial_balance_rows(ctx, entity_id, as_of=as_of)
    }
