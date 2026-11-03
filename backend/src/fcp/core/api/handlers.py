"""Map Django Ninja errors to RFC 9457 problem responses, consistent with the rest of the app."""

from typing import Any

from django.http import HttpRequest, HttpResponse
from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from fcp.core.errors import DomainError
from fcp.core.http.problem import problem_response, response_for_exception
from fcp.core.money import MoneyError


def _field_errors(errors: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for error in errors:
        location = [str(part) for part in error.get("loc", ()) if part not in ("body", "payload")]
        key = ".".join(location) or "request"
        result.setdefault(key, []).append(str(error.get("msg", "Invalid value")))
    return result


def install_exception_handlers(api: NinjaAPI) -> None:
    @api.exception_handler(ValidationError)
    def validation(request: HttpRequest, exc: ValidationError) -> HttpResponse:
        return problem_response(
            request,
            status=422,
            code="validation_failed",
            title="Validation failed",
            detail="Some fields are invalid. Correct them and try again.",
            field_errors=_field_errors(list(exc.errors)),
        )

    @api.exception_handler(AuthenticationError)
    def unauthenticated(request: HttpRequest, exc: AuthenticationError) -> HttpResponse:
        return problem_response(
            request,
            status=401,
            code="auth.unauthenticated",
            title="Sign-in required",
            detail="Your session has expired or you are not signed in. Sign in to continue.",
        )

    @api.exception_handler(HttpError)
    def http_error(request: HttpRequest, exc: HttpError) -> HttpResponse:
        return problem_response(
            request,
            status=exc.status_code,
            code="http_error",
            title="Request could not be processed",
            detail=str(exc),
        )

    @api.exception_handler(DomainError)
    def domain(request: HttpRequest, exc: DomainError) -> HttpResponse:
        return response_for_exception(request, exc)

    @api.exception_handler(MoneyError)
    def money(request: HttpRequest, exc: MoneyError) -> HttpResponse:
        return response_for_exception(request, exc)

    @api.exception_handler(Exception)
    def unexpected(request: HttpRequest, exc: Exception) -> HttpResponse:
        return response_for_exception(request, exc)
