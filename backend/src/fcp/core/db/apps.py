from typing import Any

from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _apply_grants_after_migrate(**kwargs: Any) -> None:
    from .grants import apply_runtime_grants

    apply_runtime_grants(using=kwargs.get("using", "default"))


class CoreDbConfig(AppConfig):
    name = "fcp.core.db"
    label = "core_db"

    def ready(self) -> None:
        # A module-level receiver: Django holds receivers by weak reference, so a closure
        # defined here would be garbage-collected and the grants would silently never run.
        post_migrate.connect(
            _apply_grants_after_migrate, sender=self, dispatch_uid="fcp.core.db.grants"
        )
