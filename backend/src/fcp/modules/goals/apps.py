from django.apps import AppConfig


class GoalsConfig(AppConfig):
    name = "fcp.modules.goals"
    label = "goals"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import engine  # noqa: F401, PLC0415 (registers the goal engines)
