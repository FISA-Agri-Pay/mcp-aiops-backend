from time import perf_counter
from typing import Any

from fastmcp import FastMCP

from aiops_platform.mcp.audit import McpToolAuditService, elapsed_ms
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.registry import list_mcp_servers, list_mcp_tools
from aiops_platform.mcp.schemas import (
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolExecutionContext,
    McpToolMetadata,
    McpToolPermission,
)

MCP_TRANSPORT_MOUNT_PATH = "/mcp-server"
MCP_TRANSPORT_PATH = "/mcp"


def _permission_from_query(permission: str | None) -> McpToolPermission | None:
    if permission is None:
        return None
    return McpToolPermission(permission)


def _resolve_registered_tool(server_name: str | None, tool_name: str) -> McpToolMetadata:
    matches = [
        tool
        for tool in list_mcp_tools(server_name=server_name)
        if tool.tool_name == tool_name
    ]
    if not matches:
        raise ValueError("MCP tool is not registered.")
    if len(matches) > 1:
        raise ValueError("server_name is required for duplicated tool names.")
    return matches[0]


def _policy_response(tool: McpToolMetadata) -> dict[str, Any]:
    permission = McpToolPermission(tool.tool_permission)
    policy = resolve_tool_policy(permission)
    return {
        "server_name": tool.server_name,
        "tool_name": tool.tool_name,
        "tool_permission": policy.tool_permission,
        "confirmation_policy": policy.confirmation_policy,
        "execution_policy": policy.execution_policy,
        "call_status": policy.call_status,
    }


def create_mcp_server(audit_service: McpToolAuditService | None = None) -> FastMCP:
    mcp = FastMCP(
        name="aiops-platform-mcp",
        instructions="Use the registry tools to discover allowed AIOps MCP capabilities.",
        on_duplicate_tools="error",
    )

    @mcp.tool(
        name="list_mcp_servers",
        description="List registered AIOps MCP servers from the curated registry.",
        tags={"registry", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def list_servers_tool() -> list[dict[str, Any]]:
        return [server.model_dump(mode="json") for server in list_mcp_servers()]

    @mcp.tool(
        name="list_mcp_tools",
        description="List registered AIOps MCP tools, optionally filtered by server or permission.",
        tags={"registry", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def list_tools_tool(
        server_name: str | None = None,
        permission: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            tool.model_dump(mode="json")
            for tool in list_mcp_tools(
                server_name=server_name,
                permission=_permission_from_query(permission),
            )
        ]

    @mcp.tool(
        name="get_mcp_tool_policy",
        description="Resolve the confirmation and execution policy for a registered MCP tool.",
        tags={"registry", "policy", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_tool_policy_tool(
        tool_name: str,
        server_name: str | None = None,
    ) -> dict[str, Any]:
        tool = _resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        return _policy_response(tool)

    @mcp.tool(
        name="preview_mcp_tool_execution",
        description="Preview policy and audit status for a registered MCP tool execution.",
        tags={"registry", "policy", "audit", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def preview_tool_execution(
        tool_name: str,
        server_name: str,
        request_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        permission = McpToolPermission(tool.tool_permission)
        policy = resolve_tool_policy(permission)
        response = {
            **_policy_response(tool),
            "will_execute": (
                McpExecutionPolicy(policy.execution_policy) == McpExecutionPolicy.ALLOWED
            ),
        }

        if audit_service is not None:
            audit_service.record_tool_call(
                context=McpToolExecutionContext(
                    server_name=tool.server_name,
                    tool_name=tool.tool_name,
                    request_payload=request_payload or {},
                ),
                permission=permission,
                response_payload=response,
                call_status=McpToolCallStatus(policy.call_status),
                latency_ms=elapsed_ms(started_at),
            )

        return response

    return mcp
