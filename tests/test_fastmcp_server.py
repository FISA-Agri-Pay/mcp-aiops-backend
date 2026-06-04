import asyncio

from fastmcp.client import Client

from aiops_platform.main import create_app
from aiops_platform.mcp.server import MCP_TRANSPORT_MOUNT_PATH, create_mcp_server


def test_fastapi_app_mounts_fastmcp_transport() -> None:
    app = create_app()

    assert any(route.path == MCP_TRANSPORT_MOUNT_PATH for route in app.routes)


def test_fastmcp_server_exposes_registry_tools() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            tools = await client.list_tools()

        assert {tool.name for tool in tools} == {
            "list_mcp_servers",
            "list_mcp_tools",
            "get_mcp_tool_policy",
        }

    asyncio.run(run())


def test_fastmcp_tool_policy_blocks_destructive_tools() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            result = await client.call_tool(
                "get_mcp_tool_policy",
                {"server_name": "infraops-mcp", "tool_name": "delete_pod"},
            )

        assert result.data == {
            "server_name": "infraops-mcp",
            "tool_name": "delete_pod",
            "tool_permission": "DESTRUCTIVE",
            "confirmation_policy": "BLOCKED",
            "execution_policy": "blocked",
        }

    asyncio.run(run())

