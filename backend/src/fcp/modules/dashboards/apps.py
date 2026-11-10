from django.apps import AppConfig


class DashboardsConfig(AppConfig):
    name = "fcp.modules.dashboards"
    label = "dashboards"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from fcp.modules.goals.api import on_evaluation  # noqa: PLC0415

        from .alerts import goal_evaluated  # noqa: PLC0415

        on_evaluation(goal_evaluated)
