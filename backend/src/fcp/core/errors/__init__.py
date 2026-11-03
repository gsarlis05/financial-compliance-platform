"""Typed domain errors that map to RFC 9457 problem responses (docs/planning/02 §3.5).

Raise a subclass of ``DomainError`` with a stable ``code`` and a user-safe, actionable message.
Never put personal data, amounts or document content in an error message.
"""

from typing import ClassVar


class DomainError(Exception):
    """Base class for errors that are shown to the user as problem+json responses."""

    code: ClassVar[str] = "error"
    status: ClassVar[int] = 400
    title: ClassVar[str] = "Request could not be processed"

    def __init__(self, detail: str, *, field_errors: dict[str, list[str]] | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.field_errors = field_errors or {}


class ValidationFailedError(DomainError):
    code = "validation_failed"
    status = 422
    title = "Validation failed"


class NotFoundError(DomainError):
    """Also used for resources in another tenant, to avoid disclosing that they exist."""

    code = "not_found"
    status = 404
    title = "Not found"


class PermissionDeniedError(DomainError):
    code = "permission_denied"
    status = 403
    title = "Permission denied"


class ConflictError(DomainError):
    code = "conflict"
    status = 409
    title = "Conflict"


__all__ = [
    "ConflictError",
    "DomainError",
    "NotFoundError",
    "PermissionDeniedError",
    "ValidationFailedError",
]
