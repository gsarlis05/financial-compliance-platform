"""Root HTTP API: mounts each module's router. Session authentication (with CSRF on unsafe
methods) is the default for every operation."""

from ninja import NinjaAPI
from ninja.security import django_auth

from fcp.core.api.handlers import install_exception_handlers
from fcp.modules.audit_log.routes import router as audit_router
from fcp.modules.banking.api import router as banking_router
from fcp.modules.documents.api import router as documents_router
from fcp.modules.identity.api import router as identity_router
from fcp.modules.ledger.api import router as ledger_router
from fcp.modules.metrics.api import router as metrics_router
from fcp.modules.registers.api import router as registers_router
from fcp.modules.reporting.api import router as reporting_router
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
api.add_router("/", audit_router)
api.add_router("/", ledger_router)
api.add_router("/", registers_router)
api.add_router("/", banking_router)
api.add_router("/", documents_router)
api.add_router("/", metrics_router)
api.add_router("/", reporting_router)
