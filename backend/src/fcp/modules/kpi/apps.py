from django.apps import AppConfig


class KpiConfig(AppConfig):
    name = "fcp.modules.kpi"
    label = "kpi"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from fcp.core.db.reference import register_seeder  # noqa: PLC0415

        from . import engine  # noqa: F401, PLC0415 (registers the KPI_SET engine)
        from .library import seed_libraries  # noqa: PLC0415

        register_seeder("KPI library", seed_libraries)
