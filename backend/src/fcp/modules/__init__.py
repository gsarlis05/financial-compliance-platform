"""Bounded-context modules.

Each module exposes its public interface in ``api.py``. Other modules may import only
from ``fcp.modules.<name>.api``; this is enforced by import-linter contracts in CI
(see docs/planning/02-software-architecture.md section 2).
"""
