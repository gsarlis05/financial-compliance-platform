from django.apps import AppConfig


class ProjectionsConfig(AppConfig):
    name = "fcp.modules.projections"
    label = "projections"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from . import runs  # noqa: F401, PLC0415 (registers the PROJECTION engine)
