from typing import Annotated

from fastapi import APIRouter, Query

from aiops_platform.mcp.registry import list_mcp_servers, list_mcp_tools
from aiops_platform.mcp.schemas import McpServerMetadata, McpToolMetadata, McpToolPermission

router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/servers", response_model=list[McpServerMetadata])
def get_mcp_servers() -> list[McpServerMetadata]:
    return list_mcp_servers()


@router.get("/tools", response_model=list[McpToolMetadata])
def get_mcp_tools(
    server_name: Annotated[str | None, Query()] = None,
    permission: Annotated[McpToolPermission | None, Query()] = None,
) -> list[McpToolMetadata]:
    return list_mcp_tools(server_name=server_name, permission=permission)
