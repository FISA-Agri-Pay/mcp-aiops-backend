from typing import Any

from fastmcp import FastMCP

from aiops_platform.mcp.registry import list_mcp_servers, list_mcp_tools
from aiops_platform.mcp.schemas import McpConfirmationPolicy, McpToolPermission

MCP_TRANSPORT_MOUNT_PATH = "/mcp-server"
MCP_TRANSPORT_PATH = "/mcp"


def _permission_from_query(permission: str | None) -> McpToolPermission | None:
    if permission is None:
        return None
    return McpToolPermission(permission)


def _tool_policy(permission: McpToolPermission) -> dict[str, str]:
    policies = {
        McpToolPermission.READ: {
            "confirmation_policy": McpConfirmationPolicy.NONE.value,
            "execution_policy": "allowed",
        },
        McpToolPermission.WRITE: {
            "confirmation_policy": McpConfirmationPolicy.USER_CONFIRMATION.value,
            "execution_policy": "blocked_until_confirmed",
        },
        McpToolPermission.USER_CONFIRMED_WRITE: {
            "confirmation_policy": McpConfirmationPolicy.USER_CONFIRMATION.value,
            "execution_policy": "blocked_until_confirmed",
        },
        McpToolPermission.OPS_WRITE: {
            "confirmation_policy": McpConfirmationPolicy.ADMIN_APPROVAL.value,
            "execution_policy": "blocked_until_approved",
        },
        McpToolPermission.DESTRUCTIVE: {
            "confirmation_policy": McpConfirmationPolicy.BLOCKED.value,
            "execution_policy": "blocked",
        },
    }
    return policies[permission]


def create_mcp_server() -> FastMCP:
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
        matches = [
            tool
            for tool in list_mcp_tools(server_name=server_name)
            if tool.tool_name == tool_name
        ]
        if not matches:
            raise ValueError("MCP tool is not registered.")
        if len(matches) > 1:
            raise ValueError("server_name is required for duplicated tool names.")

        tool = matches[0]
        permission = McpToolPermission(tool.tool_permission)
        return {
            "server_name": tool.server_name,
            "tool_name": tool.tool_name,
            "tool_permission": permission.value,
            **_tool_policy(permission),
        }

    return mcp
