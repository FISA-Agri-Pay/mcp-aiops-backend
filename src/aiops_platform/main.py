from fastapi import FastAPI

from aiops_platform.api.admin import router as admin_router
from aiops_platform.api.farmer import router as farmer_router
from aiops_platform.api.health import router as health_router
from aiops_platform.api.jobs import router as jobs_router
from aiops_platform.api.llmops import router as llmops_router
from aiops_platform.api.mcp import router as mcp_router
from aiops_platform.api.rca import router as rca_router
from aiops_platform.core.config import settings
from aiops_platform.infra_rca.service import InfraRcaService
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.mcp.server import (
    MCP_TRANSPORT_MOUNT_PATH,
    MCP_TRANSPORT_PATH,
    create_mcp_server,
)
from aiops_platform.orchestration.service import OrchestrationService


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
    app.include_router(admin_router)
    app.include_router(farmer_router)
    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(llmops_router)
    app.include_router(mcp_router)
    app.include_router(rca_router)
    app.mount(MCP_TRANSPORT_MOUNT_PATH, mcp_asgi_app)
    return app


app = create_app()
