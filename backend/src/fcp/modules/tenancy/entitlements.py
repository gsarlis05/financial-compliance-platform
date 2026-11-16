"""Features and roles available per workspace kind (docs/planning/11 §5-6).

Checked server-side; hiding features in the UI is never enough.
"""

from enum import StrEnum

from fcp.core.errors import PermissionDeniedError

from .models import Tenant


class Feature(StrEnum):
    MULTIPLE_ENTITIES = "multiple_entities"
    INVITE_MEMBERS = "invite_members"
    CLIENT_PORTFOLIO = "client_portfolio"


class Role(StrEnum):
    OWNER = "owner"
    TENANT_ADMIN = "tenant_admin"
    PARTNER = "partner"
    ACCOUNTANT = "accountant"
    REVIEWER = "reviewer"
    CLIENT_USER = "client_user"
    FINANCE_MANAGER = "finance_manager"
    HOUSEHOLD_MEMBER = "household_member"
    READ_ONLY = "read_only"
    BUDGET_HOLDER = "budget_holder"  # sees and edits only the departments they own (M4-2)


_FEATURES: dict[str, frozenset[Feature]] = {
    Tenant.Kind.FIRM: frozenset(
        {Feature.MULTIPLE_ENTITIES, Feature.INVITE_MEMBERS, Feature.CLIENT_PORTFOLIO}
    ),
    Tenant.Kind.BUSINESS: frozenset({Feature.MULTIPLE_ENTITIES, Feature.INVITE_MEMBERS}),
    Tenant.Kind.PERSONAL: frozenset({Feature.INVITE_MEMBERS}),
}

_ROLES: dict[str, frozenset[Role]] = {
    Tenant.Kind.FIRM: frozenset(
        {
            Role.OWNER,
            Role.TENANT_ADMIN,
            Role.PARTNER,
            Role.ACCOUNTANT,
            Role.REVIEWER,
            Role.CLIENT_USER,
            Role.READ_ONLY,
            Role.BUDGET_HOLDER,
        }
    ),
    Tenant.Kind.BUSINESS: frozenset(
        {
            Role.OWNER,
            Role.TENANT_ADMIN,
            Role.FINANCE_MANAGER,
            Role.ACCOUNTANT,
            Role.REVIEWER,
            Role.READ_ONLY,
            Role.BUDGET_HOLDER,
        }
    ),
    Tenant.Kind.PERSONAL: frozenset({Role.OWNER, Role.HOUSEHOLD_MEMBER, Role.READ_ONLY}),
}


def has_feature(kind: str, feature: Feature) -> bool:
    return feature in _FEATURES.get(kind, frozenset())


def require_feature(kind: str, feature: Feature) -> None:
    if not has_feature(kind, feature):
        raise PermissionDeniedError(
            f"This is not available in a {kind.lower()} workspace.",
        )


def allowed_roles(kind: str) -> frozenset[Role]:
    return _ROLES.get(kind, frozenset())
