from django.apps import AppConfig


class TenancyConfig(AppConfig):
    name = "fcp.modules.tenancy"
    label = "tenancy"
    default_auto_field = "django.db.models.BigAutoField"
