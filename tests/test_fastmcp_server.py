import asyncio

from fastmcp.client import Client

from aiops_platform.infraops.schemas import (
    BatchRunStatusResult,
    ElasticsearchClusterHealthResult,
    ElasticsearchIndexHealthItem,
    ElasticsearchIndexHealthResult,
    ElasticsearchLogSearchResult,
    ElasticsearchQueryResult,
    ElkSnapshotResult,
    InfraOpsChangePreviewResult,
    KafkaConsumerLagResult,
    KibanaSavedObjectsResult,
    KubernetesResourceResult,
    LokiQueryResult,
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
            "query_loki",
            "get_k8s_pods",
            "get_k8s_events",
            "get_k8s_deployments",
            "get_k8s_hpa",
            "get_kafka_consumer_lag",
            "get_batch_run_status",
            "scale_deployment",
            "restart_pod",
            "delete_pod",
            "run_kubectl_exec",
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


def test_fastmcp_loki_tool_returns_results() -> None:
    class FakeInfraOpsService:
        def query_loki(
            self,
            query: str,
            start: str | None = None,
            end: str | None = None,
            limit: int = 100,
        ):
            assert query == '{app="api"}'
            assert start == "1"
            assert end == "2"
            assert limit == 50
            return LokiQueryResult(status="success", data={"result": []})

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            result = await client.call_tool(
                "query_loki",
                {"query": '{app="api"}', "start": "1", "end": "2", "limit": 50},
            )

        assert result.data == {"status": "success", "data": {"result": []}}

    asyncio.run(run())


def test_fastmcp_kubernetes_read_tools_return_results() -> None:
    class FakeInfraOpsService:
        def get_k8s_pods(self, namespace: str | None = None):
            assert namespace == "default"
            return KubernetesResourceResult(
                namespace="default",
                items=[{"metadata": {"name": "api-pod"}}],
                raw={"items": [{"metadata": {"name": "api-pod"}}]},
            )

        def get_k8s_events(self, namespace: str | None = None):
            assert namespace == "default"
            return KubernetesResourceResult(namespace="default", items=[], raw={"items": []})

        def get_k8s_deployments(self, namespace: str | None = None):
            assert namespace == "default"
            return KubernetesResourceResult(namespace="default", items=[], raw={"items": []})

        def get_k8s_hpa(self, namespace: str | None = None):
            assert namespace == "default"
            return KubernetesResourceResult(namespace="default", items=[], raw={"items": []})

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            pods = await client.call_tool("get_k8s_pods", {"namespace": "default"})
            events = await client.call_tool("get_k8s_events", {"namespace": "default"})
            deployments = await client.call_tool(
                "get_k8s_deployments",
                {"namespace": "default"},
            )
            hpa = await client.call_tool("get_k8s_hpa", {"namespace": "default"})

        assert pods.data["items"][0]["metadata"]["name"] == "api-pod"
        assert events.data["namespace"] == "default"
        assert deployments.data["namespace"] == "default"
        assert hpa.data["namespace"] == "default"

    asyncio.run(run())


def test_fastmcp_kafka_and_batch_tools_return_results() -> None:
    class FakeInfraOpsService:
        def get_kafka_consumer_lag(self, consumer_group: str, topic: str | None = None):
            assert consumer_group == "payments"
            assert topic == "orders"
            return KafkaConsumerLagResult(
                consumer_group=consumer_group,
                topic=topic,
                response={"total_lag": 3},
            )

        def get_batch_run_status(self, job_name: str | None = None):
            assert job_name == "daily-close"
            return BatchRunStatusResult(job_name=job_name, response={"runs": []})

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            lag = await client.call_tool(
                "get_kafka_consumer_lag",
                {"consumer_group": "payments", "topic": "orders"},
            )
            batch = await client.call_tool(
                "get_batch_run_status",
                {"job_name": "daily-close"},
            )

        assert lag.data["response"] == {"total_lag": 3}
        assert batch.data["response"] == {"runs": []}

    asyncio.run(run())


def test_fastmcp_ops_write_tools_return_approval_required_preview() -> None:
    class FakeInfraOpsService:
        def preview_scale_deployment(
            self,
            deployment_name: str,
            replicas: int,
            namespace: str | None = None,
        ):
            assert deployment_name == "api"
            assert replicas == 3
            assert namespace == "default"
            return InfraOpsChangePreviewResult(
                action="scale_deployment",
                namespace="default",
                target_kind="deployment",
                target_name="api",
                request_payload={
                    "namespace": "default",
                    "deployment_name": "api",
                    "replicas": 3,
                },
                safety_notes=["No Kubernetes scale request was sent."],
            )

        def preview_restart_pod(self, pod_name: str, namespace: str | None = None):
            assert pod_name == "api-123"
            assert namespace == "default"
            return InfraOpsChangePreviewResult(
                action="restart_pod",
                namespace="default",
                target_kind="pod",
                target_name="api-123",
                request_payload={"namespace": "default", "pod_name": "api-123"},
                safety_notes=["No Kubernetes pod mutation request was sent."],
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
            scale = await client.call_tool(
                "scale_deployment",
                {
                    "deployment_name": "api",
                    "replicas": 3,
                    "namespace": "default",
                },
            )
            restart = await client.call_tool(
                "restart_pod",
                {"pod_name": "api-123", "namespace": "default"},
            )

        assert scale.data["call_status"] == "APPROVAL_REQUIRED"
        assert scale.data["confirmation_policy"] == "ADMIN_APPROVAL"
        assert scale.data["execution_policy"] == "blocked_until_approved"
        assert scale.data["requires_approval"] is True
        assert scale.data["will_execute"] is False
        assert scale.data["preview"]["dry_run"] is True
        assert restart.data["call_status"] == "APPROVAL_REQUIRED"

    asyncio.run(run())
    assert [call["call_status"] for call in audit_service.calls] == [
        "APPROVAL_REQUIRED",
        "APPROVAL_REQUIRED",
    ]


def test_fastmcp_destructive_tools_return_blocked_preview() -> None:
    class FakeInfraOpsService:
        def preview_delete_pod(self, pod_name: str, namespace: str | None = None):
            assert pod_name == "api-123"
            assert namespace == "default"
            return InfraOpsChangePreviewResult(
                action="delete_pod",
                namespace="default",
                target_kind="pod",
                target_name="api-123",
                request_payload={"namespace": "default", "pod_name": "api-123"},
                safety_notes=["No Kubernetes delete request was sent."],
            )

        def preview_kubectl_exec(
            self,
            pod_name: str,
            command: list[str],
            namespace: str | None = None,
        ):
            assert pod_name == "api-123"
            assert command == ["sh", "-c", "date"]
            assert namespace == "default"
            return InfraOpsChangePreviewResult(
                action="run_kubectl_exec",
                namespace="default",
                target_kind="pod",
                target_name="api-123",
                request_payload={
                    "namespace": "default",
                    "pod_name": "api-123",
                    "command": ["sh", "-c", "date"],
                },
                safety_notes=["No Kubernetes exec request was sent."],
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            delete = await client.call_tool(
                "delete_pod",
                {"pod_name": "api-123", "namespace": "default"},
            )
            exec_result = await client.call_tool(
                "run_kubectl_exec",
                {
                    "pod_name": "api-123",
                    "command": ["sh", "-c", "date"],
                    "namespace": "default",
                },
            )

        assert delete.data["call_status"] == "BLOCKED"
        assert delete.data["confirmation_policy"] == "BLOCKED"
        assert delete.data["execution_policy"] == "blocked"
        assert delete.data["is_blocked"] is True
        assert delete.data["will_execute"] is False
        assert exec_result.data["call_status"] == "BLOCKED"

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
