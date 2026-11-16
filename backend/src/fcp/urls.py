"""Root URL configuration."""

from django.db import transaction
from django.http import HttpRequest, JsonResponse
from django.urls import path

from fcp.api import api
from fcp.modules.identity import views as auth_views


@transaction.non_atomic_requests
def healthz(_request: HttpRequest) -> JsonResponse:
    """Liveness probe. Static response; touches neither the database nor any tenant data."""
    return JsonResponse({"status": "ok"})


handler404 = "fcp.core.http.problem.handler404"
handler500 = "fcp.core.http.problem.handler500"

urlpatterns = [
    path("healthz", healthz, name="healthz"),
    path("auth/login", auth_views.login_view, name="login"),
    path("auth/callback", auth_views.callback_view, name="oidc-callback"),
    path("auth/logout", auth_views.logout_view, name="logout"),
    path("api/", api.urls),
]
