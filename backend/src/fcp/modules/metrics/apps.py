from django.apps import AppConfig


class MetricsConfig(AppConfig):
    name = "fcp.modules.metrics"
    label = "metrics"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from fcp.core.db.reference import register_seeder  # noqa: PLC0415

        from .taxonomy import seed_taxonomies  # noqa: PLC0415

        register_seeder("Financial taxonomy", seed_taxonomies)
