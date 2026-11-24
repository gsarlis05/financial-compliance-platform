from django.apps import AppConfig


class TaxRulesConfig(AppConfig):
    name = "fcp.modules.taxrules"
    label = "taxrules"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from fcp.core.db.reference import register_seeder  # noqa: PLC0415

        from .models import TaxRuleSet  # noqa: PLC0415
        from .seed import seed_rules  # noqa: PLC0415

        register_seeder("Tax rule sets", lambda: seed_rules(TaxRuleSet))
