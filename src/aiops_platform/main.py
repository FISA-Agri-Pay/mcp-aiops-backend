from fastapi import FastAPI

from aiops_platform.api.health import router as health_router
from aiops_platform.api.mcp import router as mcp_router
from aiops_platform.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    app.include_router(health_router)
    app.include_router(mcp_router)
    return app


app = create_app()
