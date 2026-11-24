from django.apps import AppConfig


class CashflowConfig(AppConfig):
    name = "fcp.modules.cashflow"
    label = "cashflow"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import engine  # noqa: F401, PLC0415 (registers the CASH_13W engine)
