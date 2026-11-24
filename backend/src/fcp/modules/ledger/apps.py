from django.apps import AppConfig


class LedgerConfig(AppConfig):
    name = "fcp.modules.ledger"
    label = "ledger"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from fcp.core.db.reference import register_seeder  # noqa: PLC0415

        from .models import VatCode  # noqa: PLC0415
        from .vat import seed_catalogue  # noqa: PLC0415

        register_seeder("VAT code catalogue", lambda: seed_catalogue(VatCode))
