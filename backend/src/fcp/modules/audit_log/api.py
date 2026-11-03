"""Public interface of the ``audit_log`` module.

Other modules call ``record(...)`` inside the transaction of every change they make. The HTTP
routes live in ``routes.py`` (mounted by the root API) so that this module does not depend on
``tenancy``, which itself records audit events.
"""

from .chain import ChainStatus, digest, record, verify

__all__ = ["ChainStatus", "digest", "record", "verify"]
