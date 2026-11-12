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
    "ledger_vat_code": "Reference data: VAT code catalogue per jurisdiction (no tenant data)",
    "metrics_taxonomy_version": "Reference data: financial taxonomy versions (no tenant data)",
    "metrics_taxonomy_line": "Reference data: financial taxonomy lines (no tenant data)",
    "kpi_definition": "Reference data: KPI library definitions (no tenant data)",
    "tenancy_workspace_deletion": (
        "Deletion requests and purge records; they outlive the workspace, and hold only IDs, "
        "dates and row counts"
    ),
}

# Tables the runtime role may only INSERT into and SELECT from (no UPDATE or DELETE).
APPEND_ONLY_TABLES: set[str] = {
    "audit_log_event",
    "assets_depreciation_run_line",
    "banking_reconciliation",
    "budgeting_event",
    "budgeting_explanation",
    "budgeting_review",
    "documents_document",
    "goals_evaluation",
    "personal_counterpart_decision",
    "metrics_calc_result",
    "metrics_calc_lineage",
}

# Narrow SECURITY DEFINER functions the runtime role may execute (each returns IDs only).
RUNTIME_FUNCTIONS: set[str] = {
    "banking_pending_tenant_ids()",
    "cashflow_forecast_tenant_ids()",
    "projections_rolling_tenant_ids()",
    # Engagement grants (M5-4): each returns only what the caller is entitled to.
    "app_firm_lookup(text)",
    "app_firm_engagements()",
    "app_engagement_access(text)",
    "app_engaged_workspaces()",
}

# Reference-data tables the runtime role may only SELECT from (changed by migrations only).
READ_ONLY_TABLES: set[str] = {
    "ledger_vat_code",
    "metrics_taxonomy_version",
    "metrics_taxonomy_line",
    "kpi_definition",
}
