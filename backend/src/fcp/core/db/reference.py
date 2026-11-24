"""Registry of reference-data seeders (VAT catalogue, financial taxonomy, ...).

Modules register an idempotent seeder in their ``AppConfig.ready()``; the
``seed_reference_data`` command runs them all. Core never imports modules: the dependency points
from modules to core only.
"""

from collections.abc import Callable

_SEEDERS: dict[str, Callable[[], int]] = {}


def register_seeder(name: str, seeder: Callable[[], int]) -> None:
    """``seeder()`` upserts the reference data and returns the number of rows now current."""
    _SEEDERS[name] = seeder


def run_seeders() -> dict[str, int]:
    return {name: seeder() for name, seeder in sorted(_SEEDERS.items())}
