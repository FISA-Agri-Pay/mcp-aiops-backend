from fastapi import FastAPI

from aiops_platform.admin_riskops.service import AdminRiskOpsService
from aiops_platform.api.admin import router as admin_router
from aiops_platform.api.admin_risk import router as admin_risk_router
from aiops_platform.api.farmer import router as farmer_router
from aiops_platform.api.farmer_bnpl import router as farmer_bnpl_router
from aiops_platform.api.health import router as health_router
from aiops_platform.api.jobs import router as jobs_router
from aiops_platform.api.llmops import router as llmops_router
from aiops_platform.api.mcp import router as mcp_router
from aiops_platform.api.rca import router as rca_router
from aiops_platform.api.reports import router as reports_router
from aiops_platform.api.sre import router as sre_router
from aiops_platform.core.config import settings
from aiops_platform.farmer_bnpl.service import FarmerBnplService
from aiops_platform.infra_rca.service import InfraRcaService
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.mcp.server import (
    MCP_TRANSPORT_MOUNT_PATH,
    MCP_TRANSPORT_PATH,
    create_mcp_server,
)
from aiops_platform.ops_reports.service import OpsReportService
from aiops_platform.orchestration.service import OrchestrationService

EXTERNAL_API_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    mcp_asgi_app = create_mcp_server().http_app(path=MCP_TRANSPORT_PATH)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=mcp_asgi_app.lifespan,
    )
    llmops_service = LlmOpsService()
    app.state.llmops_service = llmops_service
    app.state.orchestration_service = OrchestrationService(
        llmops_service=llmops_service,
    )
    app.state.infra_rca_service = InfraRcaService(llmops_service=llmops_service)
    app.state.ops_report_service = OpsReportService(llmops_service=llmops_service)
    app.state.admin_riskops_service = AdminRiskOpsService()
    app.state.farmer_bnpl_service = FarmerBnplService()
    app.include_router(admin_router)
    app.include_router(admin_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.include_router(admin_risk_router)
    app.include_router(farmer_router)
    app.include_router(farmer_bnpl_router)
    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(llmops_router)
    app.include_router(mcp_router)
    app.include_router(mcp_router, prefix=EXTERNAL_API_PREFIX)
    app.include_router(rca_router)
    app.include_router(reports_router)
    app.include_router(sre_router)
    app.include_router(sre_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.mount(MCP_TRANSPORT_MOUNT_PATH, mcp_asgi_app)
    app.mount(f"{EXTERNAL_API_PREFIX}{MCP_TRANSPORT_MOUNT_PATH}", mcp_asgi_app)
    return app


app = create_app()
