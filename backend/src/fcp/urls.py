"""Root URL configuration."""

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.urls import path


@transaction.non_atomic_requests
def healthz(_request: HttpRequest) -> JsonResponse:
    """Liveness probe. Static response; touches neither the database nor any tenant data."""
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz", healthz, name="healthz"),
]
