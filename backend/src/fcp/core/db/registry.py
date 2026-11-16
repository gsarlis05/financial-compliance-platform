"""Classification of every database table (doc 04 §5).

A CI test fails when a table exists that is neither tenant-owned (has a ``tenant_id`` column and
FORCE row-level security) nor listed here as global. New global tables need a reviewed reason.
"""

GLOBAL_TABLES: dict[str, str] = {
    "django_migrations": "Django migration history",
    "django_content_type": "Django framework metadata",
    "django_session": "Server-side sessions; keyed by an unguessable session id",
    "auth_permission": "Django framework metadata (unused by the application)",
    "auth_group": "Django framework metadata (unused by the application)",
    "auth_group_permissions": "Django framework metadata (unused by the application)",
    "identity_user": "Global identities; one person may belong to several workspaces",
    "tenancy_tenant": "Workspaces themselves; protected by RLS on id/membership instead",
}

# Tables the runtime role may only INSERT into and SELECT from (no UPDATE or DELETE).
APPEND_ONLY_TABLES: set[str] = set()
