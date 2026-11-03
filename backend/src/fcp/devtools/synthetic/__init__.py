"""Deterministic synthetic data generators (ADR-0010: dev and staging use synthetic data only).

The same seed and profile always produce byte-identical output.
"""

from .business import generate_business
from .household import generate_household
from .output import Dataset
from .profiles import BusinessProfile, HouseholdProfile, SpendingCategory

__all__ = [
    "BusinessProfile",
    "Dataset",
    "HouseholdProfile",
    "SpendingCategory",
    "generate_business",
    "generate_household",
]
