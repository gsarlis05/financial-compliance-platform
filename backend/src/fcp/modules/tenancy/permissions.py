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
    "tenancy.workspace.export": "Download a full export of the workspace's data",
    "tenancy.workspace.delete": "Request, confirm or cancel the deletion of the workspace",
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
    # registers: customers, suppliers and open items (M2-2)
    "registers.counterparty.read": "See customers, suppliers and their open items",
    "registers.counterparty.manage": "Create and edit customers and suppliers",
    "registers.allocation.manage": "Match payments to invoices (allocate and unallocate)",
    "registers.commitment.read": "See recurring obligations, loans, facilities and holidays",
    "registers.commitment.manage": "Record recurring obligations, loans, facilities and holidays",
    # banking (M2-5)
    "banking.read": "See bank accounts, statements and reconciliations",
    "banking.account.manage": "Create bank accounts and their CSV column mappings",
    "banking.statement.manage": "Import statements, match, ignore and book statement lines",
    "banking.reconcile": "Reconcile a bank account to its statement",
    # documents (M2-4)
    "documents.read": "See and download documents",
    "documents.upload": "Upload documents",
    "documents.link": "Attach documents to entries and open items",
    # planning: calculation runs (M3-2), forecasts and what-ifs (M3)
    "planning.read": "See forecasts, calculation runs and how each number was computed",
    "planning.run": "Run forecasts and calculations, and check that a run reproduces",
    "planning.publish": "Publish a calculation run (it then never changes)",
    # budgets (M4)
    "budget.read": "See budgets, their versions and approval trail",
    "budget.edit": "Create budgets, edit draft versions, submit them and start revisions",
    "budget.approve": "Approve, return or lock submitted budget versions",
    "budget.settings.manage": "Change budget controls such as segregation of duties",
    "budget.department": (
        "Open budgets: with budget.read and budget.edit everything, otherwise only the "
        "departments you are named owner of"
    ),
    # KPIs (M4-5)
    "kpi.definition.manage": "Propose workspace KPIs and new versions of them",
    "kpi.definition.approve": "Approve or reject workspace KPIs proposed by someone else",
    "kpi.operational.manage": "Enter operational metrics such as headcount or customers",
    # goals (M4-6)
    "goal.manage": "Set goals, change their targets and retire them",
    # alerts (M4-7)
    "alert.acknowledge": "Acknowledge alerts on goals and budgets",
    # dashboard (M4-8)
    "dashboard.manage_default": "Set the dashboard layout everyone starts from",
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
        "registers.counterparty.read",
        "registers.commitment.read",
        "reports.read",
        "banking.read",
        "documents.read",
        "planning.read",
        "budget.read",
        "budget.department",
    }
)
_PREPARE = _READ | {
    "ledger.account.manage",
    "ledger.period.manage",
    "ledger.entry.create",
    "ledger.period.unlock_request",
    "registers.counterparty.manage",
    "registers.allocation.manage",
    "registers.commitment.manage",
    "banking.account.manage",
    "banking.statement.manage",
    "banking.reconcile",
    "documents.upload",
    "documents.link",
    "planning.run",
    "budget.edit",
    "kpi.definition.manage",
    "kpi.operational.manage",
    "goal.manage",
    "alert.acknowledge",
    "reports.export",
}
_REVIEW = _READ | {
    "ledger.entry.approve",
    "ledger.entry.post",
    "reports.export",
    "alert.acknowledge",
}
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
        "planning.publish",
        "budget.approve",
        "budget.settings.manage",
        "kpi.definition.approve",
        "dashboard.manage_default",
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
    # A department's budget owner: only the budgets and departments named for them (AC-BU6).
    Role.BUDGET_HOLDER: frozenset(
        {"tenancy.workspace.read", "ledger.account.read", "ledger.period.read", "budget.department"}
    ),
}


def permissions_for(role_key: str) -> frozenset[str]:
    return ROLE_PERMISSIONS.get(role_key, frozenset())


def is_known(permission: str) -> bool:
    return permission in PERMISSIONS
