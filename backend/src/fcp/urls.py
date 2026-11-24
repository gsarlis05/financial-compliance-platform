"""Root URL configuration."""

from django.db import DatabaseError, connection, transaction
from django.http import HttpRequest, JsonResponse
from django.urls import path

from fcp.api import api
from fcp.modules.identity import views as auth_views


@transaction.non_atomic_requests
def healthz(_request: HttpRequest) -> JsonResponse:
    """Liveness probe. Static response; touches neither the database nor any tenant data."""
    return JsonResponse({"status": "ok"})


@transaction.non_atomic_requests
def readyz(_request: HttpRequest) -> JsonResponse:
    """Readiness probe: the database answers. Reads no table, so no tenant data is involved."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        return JsonResponse({"status": "unavailable", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


handler404 = "fcp.core.http.problem.handler404"
handler500 = "fcp.core.http.problem.handler500"

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("auth/login", auth_views.login_view, name="login"),
    path("auth/callback", auth_views.callback_view, name="oidc-callback"),
    path("auth/logout", auth_views.logout_view, name="logout"),
    path("api/", api.urls),
]
