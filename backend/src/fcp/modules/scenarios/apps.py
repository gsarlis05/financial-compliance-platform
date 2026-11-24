from django.apps import AppConfig


class ScenariosConfig(AppConfig):
    name = "fcp.modules.scenarios"
    label = "scenarios"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import runs  # noqa: F401, PLC0415 (registers the SCENARIO engine)
