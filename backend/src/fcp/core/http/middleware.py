"""Request middleware: correlation IDs, request logging and problem responses."""

import re
import time
import uuid
from collections.abc import Callable

import structlog
from django.http import HttpRequest, HttpResponse

from .problem import response_for_exception

CORRELATION_HEADER = "X-Request-ID"
_SAFE_CORRELATION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")

log = structlog.get_logger(__name__)

type GetResponse = Callable[[HttpRequest], HttpResponse]


class CorrelationIdMiddleware:
    """Assign a correlation ID per request and bind it to every log line.

    An incoming ``X-Request-ID`` is reused only when it is a short, safe token (so it cannot be
    used for log injection); otherwise a new UUID is generated. The ID is returned in the
    response header and in problem responses.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        incoming = request.headers.get(CORRELATION_HEADER, "")
        correlation_id = incoming if _SAFE_CORRELATION_ID.match(incoming) else str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
        try:
            response = self.get_response(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response[CORRELATION_HEADER] = correlation_id
        return response


class RequestLogMiddleware:
    """Log one line per request: method, path (no query string), status and duration."""

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.perf_counter_ns()
        response = self.get_response(request)
        log.info(
            "request.completed",
            method=request.method,
            path=request.path,
            status_code=response.status_code,
            duration_ms=(time.perf_counter_ns() - started) // 1_000_000,
        )
        return response


class ProblemDetailsMiddleware:
    """Convert exceptions raised by views into RFC 9457 problem responses."""

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_exception(self, request: HttpRequest, exception: Exception) -> HttpResponse:
        return response_for_exception(request, exception)
