from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import OrchestrationServiceDep
from aiops_platform.mcp.registry import list_mcp_servers, list_mcp_tools
from aiops_platform.mcp.schemas import (
    McpServerMetadata,
    McpToolCallStatus,
    McpToolMetadata,
    McpToolPermission,
)
from aiops_platform.orchestration.schemas import McpToolCallListResult, McpToolCallResult
from aiops_platform.orchestration.service import OrchestrationNotFoundError

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


@router.get("/tool-calls", response_model=McpToolCallListResult)
def get_mcp_tool_calls(
    service: OrchestrationServiceDep,
    server_name: Annotated[str | None, Query()] = None,
    tool_name: Annotated[str | None, Query()] = None,
    permission: Annotated[McpToolPermission | None, Query()] = None,
    status: Annotated[McpToolCallStatus | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> McpToolCallListResult:
    return service.list_tool_calls(
        server_name=server_name,
        tool_name=tool_name,
        permission=permission,
        status=status,
        limit=limit,
    )


@router.get("/tool-calls/{tool_call_id}", response_model=McpToolCallResult)
def get_mcp_tool_call(
    tool_call_id: str,
    service: OrchestrationServiceDep,
) -> McpToolCallResult:
    try:
        return service.get_tool_call(tool_call_id)
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
