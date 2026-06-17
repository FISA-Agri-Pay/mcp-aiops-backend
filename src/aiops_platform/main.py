from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aiops_platform.admin_riskops.service import AdminRiskOpsService
from aiops_platform.alertmanager_agent.service import AlertmanagerSreAgentService
from aiops_platform.alertmanager_agent.watcher import build_sre_inspection_watcher
from aiops_platform.api.admin import router as admin_router
from aiops_platform.api.admin_risk import router as admin_risk_router
from aiops_platform.api.alertmanager import (
    inspection_router as alertmanager_inspection_router,
)
from aiops_platform.api.alertmanager import router as alertmanager_router
from aiops_platform.api.farmer import router as farmer_router
from aiops_platform.api.farmer_bnpl import router as farmer_bnpl_router
from aiops_platform.api.health import router as health_router
from aiops_platform.api.jobs import router as jobs_router
from aiops_platform.api.llmops import router as llmops_router
from aiops_platform.api.mcp import router as mcp_router
from aiops_platform.api.metrics import router as metrics_router
from aiops_platform.api.prediction_scaling import router as prediction_scaling_router
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
from aiops_platform.prediction_scaling.agent import PredictiveScalingSlackAgentService
from aiops_platform.prediction_scaling.watcher import build_predictive_scaling_slack_watcher

EXTERNAL_API_PREFIX = "/api/v1"


def parse_cors_allow_origins(value: str) -> list[str]:
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def create_app() -> FastAPI:
    mcp_asgi_app = create_mcp_server().http_app(path=MCP_TRANSPORT_PATH)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp_asgi_app.lifespan(app):
            watchers = [
                getattr(app.state, "predictive_scaling_slack_watcher", None),
                getattr(app.state, "sre_inspection_watcher", None),
            ]
            for watcher in watchers:
                if watcher is not None:
                    watcher.start()
            try:
                yield
            finally:
                for watcher in watchers:
                    if watcher is not None:
                        watcher.stop()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    cors_allow_origins = parse_cors_allow_origins(settings.cors_allow_origins)
    if cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
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
    alertmanager_sre_agent_service = AlertmanagerSreAgentService(
        llmops_service=llmops_service,
    )
    app.state.alertmanager_sre_agent_service = alertmanager_sre_agent_service
    predictive_scaling_slack_agent_service = PredictiveScalingSlackAgentService(
        sre_agent_service=alertmanager_sre_agent_service,
    )
    app.state.predictive_scaling_slack_agent_service = (
        predictive_scaling_slack_agent_service
    )
    app.state.predictive_scaling_slack_watcher = build_predictive_scaling_slack_watcher(
        agent_service=predictive_scaling_slack_agent_service,
    )
    app.state.sre_inspection_watcher = build_sre_inspection_watcher(
        agent_service=alertmanager_sre_agent_service,
    )
    app.include_router(admin_router)
    app.include_router(admin_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.include_router(admin_risk_router)
    app.include_router(farmer_router)
    app.include_router(farmer_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.include_router(farmer_bnpl_router)
    app.include_router(farmer_bnpl_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.include_router(health_router)
    app.include_router(jobs_router)
    app.include_router(llmops_router)
    app.include_router(metrics_router)
    app.include_router(mcp_router)
    app.include_router(mcp_router, prefix=EXTERNAL_API_PREFIX)
    app.include_router(prediction_scaling_router)
    app.include_router(prediction_scaling_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.include_router(rca_router)
    app.include_router(reports_router)
    app.include_router(sre_router)
    app.include_router(sre_router, prefix=f"{EXTERNAL_API_PREFIX}/aiops")
    app.include_router(alertmanager_router)
    app.include_router(alertmanager_router, prefix=EXTERNAL_API_PREFIX)
    app.include_router(alertmanager_inspection_router)
    app.include_router(alertmanager_inspection_router, prefix=EXTERNAL_API_PREFIX)
    app.mount(MCP_TRANSPORT_MOUNT_PATH, mcp_asgi_app)
    app.mount(f"{EXTERNAL_API_PREFIX}{MCP_TRANSPORT_MOUNT_PATH}", mcp_asgi_app)
    return app


app = create_app()
