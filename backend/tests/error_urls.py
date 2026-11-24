"""URL configuration used only by tests/core/test_errors_and_logging.py."""

import structlog
from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.urls import path

from fcp.core.errors import ValidationFailedError
from fcp.core.money import Money

log = structlog.get_logger("tests.views")


@transaction.non_atomic_requests
def domain_error(_request: HttpRequest) -> JsonResponse:
    raise ValidationFailedError(
        "The journal entry does not balance.",
        field_errors={"lines": ["Debits and credits differ by 0.01."]},
    )


@transaction.non_atomic_requests
def money_error(_request: HttpRequest) -> JsonResponse:
    Money.of("not-a-number", "EUR")
    return JsonResponse({})  # pragma: no cover


@transaction.non_atomic_requests
def unexpected_error(request: HttpRequest) -> JsonResponse:
    # Simulates a bug whose exception message contains sensitive data.
    raise RuntimeError(f"failed for {request.GET.get('email')} iban {request.GET.get('iban')}")


@transaction.non_atomic_requests
def log_sensitive(request: HttpRequest) -> JsonResponse:
    # Simulates a careless developer passing sensitive fields to the logger.
    log.info(
        "customer.updated",
        customer_name=request.GET.get("name"),
        email=request.GET.get("email"),
        iban=request.GET.get("iban"),
        tax_id=request.GET.get("tin"),
        amount=request.GET.get("amount"),
        entity_id="9b7c1a2e-0000-4000-8000-000000000001",
    )
    # An allowed key whose value nevertheless contains sensitive data is pattern-scrubbed.
    log.info("customer.lookup", path=f"/customers/{request.GET.get('email')}")
    return JsonResponse({"status": "ok"})


handler404 = "fcp.core.http.problem.handler404"
handler500 = "fcp.core.http.problem.handler500"

urlpatterns = [
    path("domain-error", domain_error),
    path("money-error", money_error),
    path("boom", unexpected_error),
    path("log-sensitive", log_sensitive),
]
