"""RFC 9457 problem details responses (docs/planning/02 §3.5)."""

import structlog
from django.http import HttpRequest, JsonResponse

from fcp.core.errors import DomainError
from fcp.core.money import MoneyError

PROBLEM_CONTENT_TYPE = "application/problem+json"
log = structlog.get_logger(__name__)


def current_correlation_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return value if isinstance(value, str) else None


def problem_response(
    request: HttpRequest,
    *,
    status: int,
    code: str,
    title: str,
    detail: str,
    field_errors: dict[str, list[str]] | None = None,
) -> JsonResponse:
    """Build a problem+json response. ``detail`` must be user-safe (no personal data)."""
    body: dict[str, object] = {
        "type": f"urn:fcp:problem:{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.path,
        "code": code,
        "correlation_id": current_correlation_id(),
    }
    if field_errors:
        body["errors"] = field_errors
    return JsonResponse(body, status=status, content_type=PROBLEM_CONTENT_TYPE)


def response_for_exception(request: HttpRequest, exc: Exception) -> JsonResponse:
    """Map an exception to a problem response, logging it with an appropriate level."""
    if isinstance(exc, DomainError):
        log.info("request.domain_error", error_code=exc.code, status_code=exc.status)
        return problem_response(
            request,
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            field_errors=exc.field_errors,
        )
    if isinstance(exc, MoneyError):
        log.info("request.domain_error", error_code=exc.code, status_code=422)
        return problem_response(
            request, status=422, code=exc.code, title="Invalid monetary value", detail=str(exc)
        )
    log.error("request.unhandled_exception", error_type=type(exc).__name__, exc_info=exc)
    return server_error_response(request)


def server_error_response(request: HttpRequest) -> JsonResponse:
    return problem_response(
        request,
        status=500,
        code="internal_error",
        title="Internal server error",
        detail=(
            "An unexpected error occurred. It has been logged. If it persists, contact support "
            "and quote the correlation ID."
        ),
    )


def handler404(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return problem_response(
        request,
        status=404,
        code="not_found",
        title="Not found",
        detail="The requested resource does not exist or you do not have access to it.",
    )


def handler500(request: HttpRequest) -> JsonResponse:
    return server_error_response(request)
