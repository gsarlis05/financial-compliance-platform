from django.apps import AppConfig


class AuditLogConfig(AppConfig):
    name = "fcp.modules.audit_log"
    label = "audit_log"
    default_auto_field = "django.db.models.BigAutoField"
