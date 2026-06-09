import asyncio

from fastmcp.client import Client

from aiops_platform.farmer_bnpl.service import build_public_id
from aiops_platform.infraops.schemas import (
    BatchRunStatusResult,
    DailyOpsMetricsResult,
    ElasticsearchClusterHealthResult,
    ElasticsearchIndexHealthItem,
    ElasticsearchIndexHealthResult,
    ElasticsearchLogSearchResult,
    ElasticsearchQueryResult,
    ElkSnapshotResult,
    InfraOpsChangePreviewResult,
    InfraOpsSearchResult,
    InfraOpsSourceResult,
    KafkaConsumerLagResult,
    KibanaSavedObjectsResult,
    KubernetesResourceResult,
    LokiQueryResult,
    MultiClusterLokiQueryResult,
    MultiClusterPrometheusQueryResult,
    MultiClusterQuerySourceResult,
    PrometheusQueryResult,
    RcaSnapshotResult,
)
from aiops_platform.main import create_app
from aiops_platform.mcp.registry import list_mcp_tools
from aiops_platform.mcp.server import (
    ELK_TOOL_NAMES,
    KAFKA_TOOL_NAMES,
    MCP_TRANSPORT_MOUNT_PATH,
    create_mcp_server,
    settings as mcp_server_settings,
)
from tests.seed_constants import (
    CREDIT_APP_2_ID,
    CREDIT_APP_3_ID,
    FARMER_1_ID,
    FARMER_2_ID,
    FARMER_3_ID,
    FERTILIZER_ORGANIC_ID,
    MODEL_TRAFFIC_V1_ID,
    MODEL_TRAFFIC_V2_ID,
    PESTICIDE_SAFE_ID,
    PREDICTION_RUN_API_ID,
    SEED_RICE_ID,
)


def test_fastapi_app_mounts_fastmcp_transport() -> None:
    app = create_app()

    assert any(route.path == MCP_TRANSPORT_MOUNT_PATH for route in app.routes)
    assert any(route.path == f"/api/v1{MCP_TRANSPORT_MOUNT_PATH}" for route in app.routes)


def test_fastmcp_server_exposes_registry_tools() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            tools = await client.list_tools()

        assert {tool.name for tool in tools} == {
            "list_mcp_servers",
            "list_mcp_tools",
            "get_mcp_tool_policy",
            "preview_mcp_tool_execution",
            "start_credit_application",
            "save_farmland_info",
            "save_crop_info",
            "save_insurance_info",
            "get_required_documents",
            "submit_credit_documents",
            "get_credit_limit_status",
            "get_user_credit_limit",
            "get_farmer_profile",
            "get_repayment_schedule",
            "get_interest_due",
            "get_overdue_status",
            "get_latest_order_delivery_status",
            "search_products",
            "search_lowest_price_fertilizer",
            "get_product_detail",
            "calculate_cart_total",
            "prepare_bnpl_checkout_payload",
            "create_checkout_intent",
            "add_cart_item",
            "update_cart_item",
            "create_bnpl_checkout",
            "get_crop_calendar",
            "recommend_farming_materials",
            "recommend_fertilizer_requirements",
            "rank_material_options",
            "recommend_product_bundle",
            "get_weather_risk",
            "triage_crop_disease",
            "simulate_crop_income",
            "simulate_season_cashflow",
            "translate_finance_terms_for_farmer",
            "get_credit_review_queue",
            "get_credit_review_detail",
            "summarize_credit_risk",
            "get_bnpl_summary",
            "search_bnpl_users",
            "get_overdue_summary",
            "search_overdue_users",
            "get_bss_score_history",
            "simulate_disaster_credit_risk",
            "create_risk_analysis_snapshot",
            "send_repayment_alert",
            "send_overdue_alerts",
            "get_model_versions",
            "get_prediction_runs",
            "get_prediction_metrics",
            "get_latest_prediction",
            "get_actual_metrics",
            "get_prediction_errors",
            "get_prediction_error_metrics",
            "get_scaling_events",
            "get_scaling_summary",
            "create_prediction_snapshot",
            "create_scaling_analysis_snapshot",
            "query_prometheus",
            "query_loki",
            "query_multi_cluster_prometheus",
            "query_multi_cluster_loki",
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
            "create_rca_snapshot",
            "aggregate_daily_ops_metrics",
            "search_incidents",
            "search_rca_history",
        }

    asyncio.run(run())


def test_fastmcp_server_exposes_all_registry_tools() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            system_tools = {
                "list_mcp_servers",
                "list_mcp_tools",
                "get_mcp_tool_policy",
                "preview_mcp_tool_execution",
            }
            exposed_tools = {tool.name for tool in await client.list_tools()} - system_tools

        registry_tools = {tool.tool_name for tool in list_mcp_tools()}
        assert exposed_tools == registry_tools

    asyncio.run(run())


def test_fastmcp_server_hides_elk_tools_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server_settings, "infraops_elk_enabled", False)

    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            tools = {tool.name for tool in await client.list_tools()}

        assert ELK_TOOL_NAMES.isdisjoint(tools)

    asyncio.run(run())


def test_fastmcp_server_hides_kafka_tools_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(mcp_server_settings, "infraops_kafka_enabled", False)

    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            tools = {tool.name for tool in await client.list_tools()}

        assert KAFKA_TOOL_NAMES.isdisjoint(tools)

    asyncio.run(run())


def test_fastmcp_admin_riskops_read_tools_return_results() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            queue = await client.call_tool("get_credit_review_queue", {"limit": 10})
            detail = await client.call_tool(
                "get_credit_review_detail",
                {"application_id": CREDIT_APP_2_ID},
            )
            summary = await client.call_tool("get_bnpl_summary", {})
            disaster = await client.call_tool(
                "simulate_disaster_credit_risk",
                {
                        "region": "gangwon",
                        "disaster_type": "flood",
                        "affected_crop": "custom",
                    },
            )
            snapshot = await client.call_tool(
                "create_risk_analysis_snapshot",
                {"target_type": "USER", "target_id": FARMER_3_ID},
            )

        assert [item["application_id"] for item in queue.data["items"]] == [
            CREDIT_APP_2_ID,
            CREDIT_APP_3_ID,
        ]
        assert detail.data["recommended_action"] == "REQUEST_DOCUMENTS"
        assert summary.data["overdue_amount"] == 670_000
        assert disaster.data["risk_level"] == "HIGH"
        assert snapshot.data["summary"]["risk_level"] == "HIGH"
        assert detail.data["risk_factors"] == ["overdue_balance"]

    asyncio.run(run())


def test_fastmcp_admin_riskops_write_tools_return_confirmation_preview() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            repayment = await client.call_tool(
                "send_repayment_alert",
                {"user_id": FARMER_1_ID, "channel": "KAKAO"},
            )
            overdue = await client.call_tool(
                "send_overdue_alerts",
                {"min_days_overdue": 1, "channel": "SMS"},
            )

        assert repayment.data["tool_permission"] == "WRITE"
        assert repayment.data["call_status"] == "APPROVAL_REQUIRED"
        assert repayment.data["confirmation_policy"] == "USER_CONFIRMATION"
        assert repayment.data["will_execute"] is False
        assert repayment.data["preview"]["dry_run"] is True
        assert repayment.data["preview"]["target_user_ids"] == [FARMER_1_ID]
        assert overdue.data["preview"]["target_user_ids"] == [FARMER_2_ID, FARMER_3_ID]

    asyncio.run(run())


def test_fastmcp_prediction_scaling_tools_return_results() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            models = await client.call_tool(
                "get_model_versions",
                {"service_name": "api", "limit": 10},
            )
            latest = await client.call_tool(
                "get_latest_prediction",
                {
                    "metric_name": "http_requests_per_second",
                    "namespace": "default",
                    "workload": "api",
                },
            )
            errors = await client.call_tool(
                "get_prediction_error_metrics",
                {"prediction_run_id": PREDICTION_RUN_API_ID},
            )
            snapshot = await client.call_tool(
                "create_scaling_analysis_snapshot",
                {"namespace": "default", "workload": "api"},
            )

        assert [item["model_version_id"] for item in models.data["items"]] == [
            MODEL_TRAFFIC_V2_ID,
            MODEL_TRAFFIC_V1_ID,
        ]
        assert latest.data["prediction_run_id"] == PREDICTION_RUN_API_ID
        assert latest.data["predicted_value"] == 150.0
        assert errors.data["sample_count"] == 3
        assert errors.data["mean_absolute_error"] == 6.67
        assert snapshot.data["summary"]["prediction_driven_events"] == 1
        assert snapshot.data["evidence"]["related_prediction_run_ids"] == [
            PREDICTION_RUN_API_ID
        ]

    asyncio.run(run())


def test_fastmcp_farm_advisory_tools_return_bnpl_ready_results() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            calendar = await client.call_tool(
                "get_crop_calendar",
                {"crop_type": "rice", "region": "jeonbuk"},
            )
            bundle = await client.call_tool(
                "recommend_product_bundle",
                {"crop_type": "rice", "area_hectare": 1.0},
            )
            cashflow = await client.call_tool(
                "simulate_season_cashflow",
                {
                    "crop_type": "rice",
                    "area_hectare": 1.0,
                    "starting_cash": 100_000,
                    "bnpl_limit": 1_000_000,
                },
            )
            term = await client.call_tool(
                "translate_finance_terms_for_farmer",
                {"term": "credit limit"},
            )

        assert calendar.data["stages"][0]["stage"] == "planning"
        assert bundle.data["cart_items"] == [
            {"product_id": FERTILIZER_ORGANIC_ID, "quantity": 12},
            {"product_id": SEED_RICE_ID, "quantity": 3},
            {"product_id": PESTICIDE_SAFE_ID, "quantity": 2},
        ]
        assert bundle.data["estimated_budget"] == 432_000
        assert cashflow.data["recommended_bnpl_amount"] == 332_000
        assert "maximum BNPL amount" in term.data["plain_language"]

    asyncio.run(run())


def test_fastmcp_farmer_bnpl_read_tools_return_results() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            products = await client.call_tool(
                "search_products",
                {"query": "fertilizer", "limit": 10},
            )
            total = await client.call_tool(
                "calculate_cart_total",
                {
                    "items": [
                        {"product_id": FERTILIZER_ORGANIC_ID, "quantity": 2},
                        {"product_id": SEED_RICE_ID, "quantity": 1},
                    ]
                },
            )
            payload = await client.call_tool(
                "prepare_bnpl_checkout_payload",
                {
                    "user_id": FARMER_1_ID,
                    "items": [{"product_id": FERTILIZER_ORGANIC_ID, "quantity": 2}],
                },
            )

        assert len(products.data["items"]) == 2
        assert all(item["category"] == "fertilizer" for item in products.data["items"])
        assert total.data["total_amount"] == 84_000
        assert payload.data["eligible"] is True
        assert payload.data["payload"]["total_amount"] == 48_000

    asyncio.run(run())


def test_fastmcp_farmer_bnpl_write_tools_return_user_confirmation_preview() -> None:
    async def run() -> None:
        async with Client(create_mcp_server()) as client:
            application = await client.call_tool(
                "start_credit_application",
                {
                    "user_id": FARMER_1_ID,
                    "requested_amount": 1_500_000,
                    "crop_type": "rice",
                },
            )
            checkout = await client.call_tool(
                "create_bnpl_checkout",
                {
                    "user_id": FARMER_1_ID,
                    "checkout_intent_id": "checkout-intent-preview",
                    "confirmation_token": "confirm-1",
                },
            )

        assert application.data["tool_permission"] == "WRITE"
        assert application.data["call_status"] == "APPROVAL_REQUIRED"
        assert application.data["confirmation_policy"] == "USER_CONFIRMATION"
        assert application.data["will_execute"] is False
        assert application.data["preview"]["application_id"] == build_public_id(
            "credit-app",
            FARMER_1_ID,
        )
        assert checkout.data["tool_permission"] == "USER_CONFIRMED_WRITE"
        assert checkout.data["call_status"] == "APPROVAL_REQUIRED"
        assert checkout.data["preview"]["payment_method"] == "BNPL"

    asyncio.run(run())


def test_create_mcp_server_preserves_positional_infraops_service_argument() -> None:
    class FakeInfraOpsService:
        def query_prometheus(self, query: str, time: str | None = None):
            assert query == "up"
            assert time is None
            return PrometheusQueryResult(
                status="success",
                data={"resultType": "vector", "result": []},
            )

    async def run() -> None:
        async with Client(create_mcp_server(None, FakeInfraOpsService())) as client:
            result = await client.call_tool("query_prometheus", {"query": "up"})

        assert result.data["status"] == "success"

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


def test_fastmcp_multi_cluster_observability_tools_return_results() -> None:
    class FakeInfraOpsService:
        def query_multi_cluster_prometheus(self, query: str, time: str | None = None):
            assert query == "up"
            assert time is None
            return MultiClusterPrometheusQueryResult(
                query=query,
                time=time,
                partial=True,
                sources=[
                    MultiClusterQuerySourceResult(
                        source="onprem",
                        status="SUCCESS",
                        data={"status": "success", "data": {"result": []}},
                    ),
                    MultiClusterQuerySourceResult(
                        source="aws",
                        status="FAILED",
                        error="source unavailable",
                    ),
                ],
            )

        def query_multi_cluster_loki(
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
            return MultiClusterLokiQueryResult(
                query=query,
                start=start,
                end=end,
                limit=limit,
                partial=False,
                sources=[
                    MultiClusterQuerySourceResult(
                        source="onprem",
                        status="SUCCESS",
                        data={"status": "success", "data": {"result": []}},
                    )
                ],
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            prometheus = await client.call_tool(
                "query_multi_cluster_prometheus",
                {"query": "up"},
            )
            loki = await client.call_tool(
                "query_multi_cluster_loki",
                {"query": '{app="api"}', "start": "1", "end": "2", "limit": 50},
            )

        assert prometheus.data["partial"] is True
        assert [source["source"] for source in prometheus.data["sources"]] == [
            "onprem",
            "aws",
        ]
        assert prometheus.data["sources"][1]["status"] == "FAILED"
        assert loki.data["partial"] is False
        assert loki.data["sources"][0]["source"] == "onprem"

    asyncio.run(run())


def test_fastmcp_kubernetes_read_tools_return_results() -> None:
    class FakeInfraOpsService:
        def get_k8s_pods(self, namespace: str | None = None, source: str | None = None):
            assert namespace == "default"
            assert source == "onprem"
            return KubernetesResourceResult(
                source="onprem",
                namespace="default",
                items=[{"metadata": {"name": "api-pod"}}],
                raw={"items": [{"metadata": {"name": "api-pod"}}]},
            )

        def get_k8s_events(self, namespace: str | None = None, source: str | None = None):
            assert namespace == "default"
            assert source == "onprem"
            return KubernetesResourceResult(
                source="onprem",
                namespace="default",
                items=[],
                raw={"items": []},
            )

        def get_k8s_deployments(
            self,
            namespace: str | None = None,
            source: str | None = None,
        ):
            assert namespace == "default"
            assert source == "onprem"
            return KubernetesResourceResult(
                source="onprem",
                namespace="default",
                items=[],
                raw={"items": []},
            )

        def get_k8s_hpa(self, namespace: str | None = None, source: str | None = None):
            assert namespace == "default"
            assert source == "onprem"
            return KubernetesResourceResult(
                source="onprem",
                namespace="default",
                items=[],
                raw={"items": []},
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            pods = await client.call_tool(
                "get_k8s_pods",
                {"namespace": "default", "source": "onprem"},
            )
            events = await client.call_tool(
                "get_k8s_events",
                {"namespace": "default", "source": "onprem"},
            )
            deployments = await client.call_tool(
                "get_k8s_deployments",
                {"namespace": "default", "source": "onprem"},
            )
            hpa = await client.call_tool(
                "get_k8s_hpa",
                {"namespace": "default", "source": "onprem"},
            )

        assert pods.data["items"][0]["metadata"]["name"] == "api-pod"
        assert pods.data["source"] == "onprem"
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


def test_fastmcp_rca_and_daily_report_tools_return_results() -> None:
    class FakeInfraOpsService:
        def create_rca_snapshot(
            self,
            incident_key: str | None = None,
            namespace: str | None = None,
            index_pattern: str | None = None,
            prometheus_query: str = "up",
            loki_query: str = '{job=~".+"}',
            loki_limit: int = 100,
            kafka_consumer_group: str | None = None,
            kafka_topic: str | None = None,
            batch_job_name: str | None = None,
        ):
            assert incident_key == "INC-1"
            assert namespace == "default"
            assert index_pattern == "logs-*"
            assert prometheus_query == "up"
            assert loki_query == '{app="api"}'
            assert loki_limit == 50
            assert kafka_consumer_group == "payments"
            assert kafka_topic == "orders"
            assert batch_job_name == "daily-close"
            return RcaSnapshotResult(
                incident_key=incident_key,
                partial=True,
                sources=[
                    InfraOpsSourceResult(
                        source="prometheus",
                        status="SUCCESS",
                        data={"status": "success"},
                    ),
                    InfraOpsSourceResult(
                        source="kafka",
                        status="FAILED",
                        error="source unavailable",
                    ),
                ],
            )

        def aggregate_daily_ops_metrics(
            self,
            report_date: str | None = None,
            namespace: str | None = None,
            index_pattern: str | None = None,
            prometheus_query: str = "up",
            kafka_consumer_group: str | None = None,
            kafka_topic: str | None = None,
            batch_job_name: str | None = None,
        ):
            assert report_date == "2026-06-05"
            assert namespace == "default"
            return DailyOpsMetricsResult(
                report_date=report_date,
                partial=False,
                metrics={"successful_sources": 6, "failed_sources": 0},
                sources=[
                    InfraOpsSourceResult(
                        source="prometheus",
                        status="SUCCESS",
                        data={"status": "success"},
                    )
                ],
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            snapshot = await client.call_tool(
                "create_rca_snapshot",
                {
                    "incident_key": "INC-1",
                    "namespace": "default",
                    "index_pattern": "logs-*",
                    "prometheus_query": "up",
                    "loki_query": '{app="api"}',
                    "loki_limit": 50,
                    "kafka_consumer_group": "payments",
                    "kafka_topic": "orders",
                    "batch_job_name": "daily-close",
                },
            )
            daily = await client.call_tool(
                "aggregate_daily_ops_metrics",
                {"report_date": "2026-06-05", "namespace": "default"},
            )

        assert snapshot.data["incident_key"] == "INC-1"
        assert snapshot.data["partial"] is True
        assert snapshot.data["sources"][1]["status"] == "FAILED"
        assert daily.data["metrics"]["successful_sources"] == 6

    asyncio.run(run())


def test_fastmcp_incident_and_rca_history_search_tools_return_results() -> None:
    class FakeInfraOpsService:
        def search_incidents(self, query: str | None = None, limit: int = 20):
            assert query == "payment"
            assert limit == 10
            return InfraOpsSearchResult(
                query=query,
                limit=limit,
                items=[],
                source="incidents",
                note="not connected",
            )

        def search_rca_history(self, query: str | None = None, limit: int = 20):
            assert query == "latency"
            assert limit == 5
            return InfraOpsSearchResult(
                query=query,
                limit=limit,
                items=[],
                source="rca_history",
                note="not connected",
            )

    async def run() -> None:
        async with Client(create_mcp_server(infraops_service=FakeInfraOpsService())) as client:
            incidents = await client.call_tool(
                "search_incidents",
                {"query": "payment", "limit": 10},
            )
            history = await client.call_tool(
                "search_rca_history",
                {"query": "latency", "limit": 5},
            )

        assert incidents.data["source"] == "incidents"
        assert incidents.data["items"] == []
        assert history.data["source"] == "rca_history"
        assert history.data["items"] == []

    asyncio.run(run())
