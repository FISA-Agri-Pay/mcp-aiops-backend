import asyncio

from fastmcp.client import Client

from aiops_platform.infraops.schemas import (
    ElasticsearchClusterHealthResult,
    ElasticsearchIndexHealthItem,
    ElasticsearchIndexHealthResult,
    ElasticsearchLogSearchResult,
    ElasticsearchQueryResult,
    ElkSnapshotResult,
    KibanaSavedObjectsResult,
    PrometheusQueryResult,
)
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
            "query_prometheus",
            "query_elasticsearch",
            "search_elasticsearch_logs",
            "get_elasticsearch_cluster_health",
            "get_elasticsearch_index_health",
            "get_kibana_saved_objects",
            "create_elk_snapshot",
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


def test_fastmcp_query_prometheus_tool_records_success_audit() -> None:
    class FakeInfraOpsService:
        def query_prometheus(self, query: str, time: str | None = None):
            assert query == "up"
            assert time is None
            return PrometheusQueryResult(
                status="success",
                data={"resultType": "vector", "result": []},
            )

    class FakeAuditService:
        def __init__(self) -> None:
            self.calls = []

        def record_tool_call(self, **kwargs) -> None:
            self.calls.append(kwargs)

    audit_service = FakeAuditService()

    async def run() -> None:
        async with Client(
            create_mcp_server(
                audit_service=audit_service,
                infraops_service=FakeInfraOpsService(),
            )
        ) as client:
            result = await client.call_tool("query_prometheus", {"query": "up"})

        assert result.data == {
            "status": "success",
            "data": {"resultType": "vector", "result": []},
        }
        assert len(audit_service.calls) == 1
        assert audit_service.calls[0]["context"].tool_name == "query_prometheus"
        assert audit_service.calls[0]["call_status"] == "SUCCESS"

    asyncio.run(run())


def test_fastmcp_elasticsearch_health_tools_return_results() -> None:
    class FakeInfraOpsService:
        def get_elasticsearch_cluster_health(self):
            return ElasticsearchClusterHealthResult(
                status="green",
                cluster_name="local",
                number_of_nodes=1,
                active_shards=3,
                relocating_shards=0,
                initializing_shards=0,
                unassigned_shards=0,
                raw={"status": "green", "cluster_name": "local"},
            )

        def get_elasticsearch_index_health(self, index_pattern: str | None = None):
            assert index_pattern == "logs-*"
            return ElasticsearchIndexHealthResult(
                indices=[
                    ElasticsearchIndexHealthItem(
                        index="logs-api-2026.06.04",
                        health="green",
                        status="open",
                        docs_count="10",
                        store_size="20kb",
                    )
                ]
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            cluster = await client.call_tool("get_elasticsearch_cluster_health", {})
            indices = await client.call_tool(
                "get_elasticsearch_index_health",
                {"index_pattern": "logs-*"},
            )

        assert cluster.data["status"] == "green"
        assert cluster.data["cluster_name"] == "local"
        assert indices.data["indices"][0]["index"] == "logs-api-2026.06.04"

    asyncio.run(run())


def test_fastmcp_elasticsearch_query_tools_return_results() -> None:
    class FakeInfraOpsService:
        def query_elasticsearch(self, index_pattern: str, query: dict):
            assert index_pattern == "logs-*"
            assert query == {"query": {"match_all": {}}}
            return ElasticsearchQueryResult(
                index_pattern=index_pattern,
                response={"hits": {"hits": []}},
            )

        def search_elasticsearch_logs(
            self,
            query: str,
            index_pattern: str | None = None,
            size: int = 10,
        ):
            assert query == "level:error"
            assert index_pattern == "logs-*"
            assert size == 5
            return ElasticsearchLogSearchResult(
                index_pattern="logs-*",
                response={"hits": {"hits": []}},
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            raw_query = await client.call_tool(
                "query_elasticsearch",
                {
                    "index_pattern": "logs-*",
                    "query": {"query": {"match_all": {}}},
                },
            )
            log_search = await client.call_tool(
                "search_elasticsearch_logs",
                {"query": "level:error", "index_pattern": "logs-*", "size": 5},
            )

        assert raw_query.data["index_pattern"] == "logs-*"
        assert log_search.data["response"] == {"hits": {"hits": []}}

    asyncio.run(run())


def test_fastmcp_kibana_and_snapshot_tools_return_results() -> None:
    cluster_health = ElasticsearchClusterHealthResult(
        status="green",
        cluster_name="local",
        number_of_nodes=1,
        active_shards=3,
        relocating_shards=0,
        initializing_shards=0,
        unassigned_shards=0,
        raw={"status": "green", "cluster_name": "local"},
    )
    index_health = ElasticsearchIndexHealthResult(
        indices=[
            ElasticsearchIndexHealthItem(
                index="logs-api-2026.06.04",
                health="green",
                status="open",
                docs_count="10",
                store_size="20kb",
            )
        ]
    )

    class FakeInfraOpsService:
        def get_kibana_saved_objects(
            self,
            saved_object_type: str = "dashboard",
            search: str | None = None,
            per_page: int = 20,
        ):
            assert saved_object_type == "dashboard"
            assert search == "api"
            assert per_page == 10
            return KibanaSavedObjectsResult(
                saved_object_type=saved_object_type,
                response={"saved_objects": []},
            )

        def create_elk_snapshot(self, index_pattern: str | None = None):
            assert index_pattern == "logs-*"
            return ElkSnapshotResult(
                cluster_health=cluster_health,
                index_health=index_health,
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            saved_objects = await client.call_tool(
                "get_kibana_saved_objects",
                {
                    "saved_object_type": "dashboard",
                    "search": "api",
                    "per_page": 10,
                },
            )
            snapshot = await client.call_tool(
                "create_elk_snapshot",
                {"index_pattern": "logs-*"},
            )

        assert saved_objects.data["response"] == {"saved_objects": []}
        assert snapshot.data["cluster_health"]["status"] == "green"
        assert snapshot.data["index_health"]["indices"][0]["index"] == "logs-api-2026.06.04"

    asyncio.run(run())
