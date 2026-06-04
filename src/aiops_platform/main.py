from fastapi import FastAPI

from aiops_platform.api.health import router as health_router
from aiops_platform.api.mcp import router as mcp_router
from aiops_platform.core.config import settings
from aiops_platform.mcp.server import (
    MCP_TRANSPORT_MOUNT_PATH,
    MCP_TRANSPORT_PATH,
    create_mcp_server,
)


def create_app() -> FastAPI:
    mcp_asgi_app = create_mcp_server().http_app(path=MCP_TRANSPORT_PATH)
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=mcp_asgi_app.lifespan,
    )
    app.include_router(health_router)
    app.include_router(mcp_router)
    app.mount(MCP_TRANSPORT_MOUNT_PATH, mcp_asgi_app)
    return app


app = create_app()
