"""Permission catalogue and system role definitions (doc 04 §3).

Rules encoded here:
- Deny by default: a permission not listed for a role is not granted.
- Segregation of duties: administrators manage people and settings but cannot approve or post
  journal entries (AC-B7); preparers (accountant) cannot approve or post.
- Roles can be granted only by someone who holds every permission of that role (AC-B7).
"""

from .entitlements import Role

PERMISSIONS: dict[str, str] = {
    # workspace administration
    "tenancy.workspace.read": "See the workspace and its legal entities",
    "tenancy.entity.manage": "Create and edit legal entities",
    "tenancy.members.manage": "Invite members and assign roles",
    # chart of accounts and periods
    "ledger.account.read": "See the chart of accounts",
    "ledger.account.manage": "Create and edit accounts",
    "ledger.period.read": "See fiscal years and periods",
    "ledger.period.manage": "Create fiscal years; open and soft-close periods",
    "ledger.period.lock": "Lock periods",
    "ledger.period.post_soft_closed": "Post into soft-closed periods",
    "ledger.period.unlock_request": "Request that a locked period be unlocked",
    "ledger.period.unlock_approve": "Approve a period unlock (two distinct approvers needed)",
    "ledger.settings.manage": "Change ledger controls such as the approval policy",
    # journal entries
    "ledger.entry.read": "See journal entries",
    "ledger.entry.create": "Create, edit and submit draft entries (including reversal drafts)",
    "ledger.entry.approve": "Approve or reject submitted entries",
    "ledger.entry.post": "Post approved entries to the ledger",
    # reporting and evidence
    "reports.read": "See trial balance and general ledger",
    "reports.export": "Export reports",
    "audit.read": "See the audit trail",
    "admin.integrity.read": "See ledger integrity check results",
}

_READ = frozenset(
    {
        "tenancy.workspace.read",
        "ledger.account.read",
        "ledger.period.read",
        "ledger.entry.read",
        "reports.read",
    }
)
_PREPARE = _READ | {
    "ledger.account.manage",
    "ledger.period.manage",
    "ledger.entry.create",
    "ledger.period.unlock_request",
    "reports.export",
}
_REVIEW = _READ | {"ledger.entry.approve", "ledger.entry.post", "reports.export"}
_SIGN_OFF = (
    _PREPARE
    | _REVIEW
    | {
        "ledger.period.lock",
        "ledger.period.post_soft_closed",
        "ledger.period.unlock_approve",
        "ledger.settings.manage",
        "audit.read",
        "admin.integrity.read",
    }
)

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    Role.OWNER: frozenset(PERMISSIONS),
    Role.TENANT_ADMIN: _READ
    | {
        "tenancy.entity.manage",
        "tenancy.members.manage",
        "audit.read",
        "admin.integrity.read",
    },
    Role.PARTNER: _SIGN_OFF | {"tenancy.entity.manage", "tenancy.members.manage"},
    Role.FINANCE_MANAGER: _SIGN_OFF,
    Role.ACCOUNTANT: _PREPARE,
    Role.REVIEWER: _REVIEW,
    Role.CLIENT_USER: _READ,
    # Personal finances: no approval workflow, so household members prepare and post.
    Role.HOUSEHOLD_MEMBER: _PREPARE | {"ledger.entry.post"},
    Role.READ_ONLY: _READ,
}


def permissions_for(role_key: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role_key, frozenset())


def is_known(permission: str) -> bool:
    return permission in PERMISSIONS
