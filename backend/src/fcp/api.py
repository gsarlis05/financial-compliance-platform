"""Root HTTP API: mounts each module's router. Session authentication (with CSRF on unsafe
methods) is the default for every operation."""

from ninja import NinjaAPI
from ninja.security import django_auth

from fcp.core.api.handlers import install_exception_handlers
from fcp.modules.identity.api import router as identity_router
from fcp.modules.tenancy.api import router as tenancy_router

api = NinjaAPI(
    title="Financial Compliance Platform API",
    version="0.1.0",
    auth=django_auth,
    urls_namespace="api",
    docs_url="/docs",
)
install_exception_handlers(api)
api.add_router("/", identity_router)
api.add_router("/", tenancy_router)
