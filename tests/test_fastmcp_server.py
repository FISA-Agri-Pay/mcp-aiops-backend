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
            "preview_mcp_tool_execution",
        }

    asyncio.run(run())


def test_fastmcp_preview_tool_records_audit_when_service_is_provided() -> None:
    class FakeAuditService:
        def __init__(self) -> None:
            self.calls = []

        def record_tool_call(self, **kwargs) -> None:
            self.calls.append(kwargs)

    audit_service = FakeAuditService()

    async def run() -> None:
        async with Client(create_mcp_server(audit_service=audit_service)) as client:
            result = await client.call_tool(
                "preview_mcp_tool_execution",
                {
                    "server_name": "infraops-mcp",
                    "tool_name": "query_prometheus",
                    "request_payload": {"query": "up"},
                },
            )

        assert result.data["will_execute"] is True
        assert len(audit_service.calls) == 1
        assert audit_service.calls[0]["context"].server_name == "infraops-mcp"
        assert audit_service.calls[0]["permission"] == "READ"
        assert audit_service.calls[0]["call_status"] == "SUCCESS"

    asyncio.run(run())


def test_fastmcp_preview_tool_continues_when_audit_fails() -> None:
    class FailingAuditService:
        def record_tool_call(self, **kwargs) -> None:
            raise RuntimeError("audit unavailable")

    async def run() -> None:
        async with Client(create_mcp_server(audit_service=FailingAuditService())) as client:
            result = await client.call_tool(
                "preview_mcp_tool_execution",
                {
                    "server_name": "infraops-mcp",
                    "tool_name": "query_prometheus",
                    "request_payload": {"query": "up"},
                },
            )

        assert result.data["server_name"] == "infraops-mcp"
        assert result.data["tool_name"] == "query_prometheus"
        assert result.data["will_execute"] is True

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
            "call_status": "BLOCKED",
        }

    asyncio.run(run())
