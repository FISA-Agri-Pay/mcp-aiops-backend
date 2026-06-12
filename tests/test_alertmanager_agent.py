from datetime import UTC, datetime

from fastapi.testclient import TestClient

from aiops_platform.agent.dispatcher import build_tool_result, resolve_registered_tool
from aiops_platform.agent.schemas import AgentToolExecutionResult, AgentToolPlan
from aiops_platform.alertmanager_agent.service import AlertmanagerSreAgentService
from aiops_platform.infra_rca.schemas import AlertmanagerWebhookRequest
from aiops_platform.main import create_app
from aiops_platform.mcp.schemas import McpExecutionPolicy, McpToolCallStatus

MUTATING_TOOL_NAMES = {
    "scale_deployment",
    "restart_pod",
    "delete_pod",
    "run_kubectl_exec",
}

POD_CRASH_PAYLOAD = {
    "receiver": "aiops-platform",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "PodCrashLooping",
                "cluster": "onprem",
                "namespace": "service-catalog",
                "service": "service-catalog",
                "pod": "service-catalog-abc",
                "severity": "critical",
            },
            "annotations": {
                "summary": "Pod service-catalog-abc is crash looping",
            },
            "startsAt": "2026-06-12T01:00:00Z",
            "fingerprint": "pod-crash-001",
        }
    ],
}


def build_firing_payload(
    *,
    alertname: str,
    service: str,
    namespace: str,
    cluster: str = "onprem",
    severity: str = "critical",
    summary: str,
    extra_labels: dict[str, str] | None = None,
    extra_annotations: dict[str, str] | None = None,
) -> dict[str, object]:
    labels = {
        "alertname": alertname,
        "cluster": cluster,
        "namespace": namespace,
        "service": service,
        "severity": severity,
    }
    if extra_labels is not None:
        labels.update(extra_labels)
    annotations = {"summary": summary}
    if extra_annotations is not None:
        annotations.update(extra_annotations)
    return {
        "receiver": "aiops-platform",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": labels,
                "annotations": annotations,
                "fingerprint": f"{alertname.lower()}-001",
            }
        ],
    }


def plan_from_payload(payload: dict[str, object]):
    service = AlertmanagerSreAgentService()
    return service.plan_from_webhook(AlertmanagerWebhookRequest.model_validate(payload))


def tool_names(result) -> set[str]:
    return {tool.tool_name for tool in result.planned_tools}


def assert_dry_run_read_only_plan(result) -> None:
    assert result.dry_run is True
    assert result.status == "PLANNED"
    assert MUTATING_TOOL_NAMES.isdisjoint(tool_names(result))


def assert_common_rca_context_tools(result) -> None:
    names = tool_names(result)
    assert {
        "get_topology_snapshot",
        "search_topology_knowledge",
        "get_service_routing_path",
        "get_service_dependency_map",
        "get_alertmanager_alerts",
        "query_multi_cluster_prometheus",
        "query_multi_cluster_loki",
        "get_service_trace_summary",
        "search_traces",
        "get_recent_deployments",
        "create_rca_snapshot",
    }.issubset(names)


def test_alertmanager_sre_agent_plans_pod_crashloop_read_tools() -> None:
    result = plan_from_payload(POD_CRASH_PAYLOAD)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert result.incident_key == (
        "alertmanager:podcrashlooping:onprem:service-catalog:service-catalog:critical"
    )
    assert result.intent == "pod_crashloop"
    assert result.capability == "pod_crashloop_analysis"
    assert "get_k8s_pods" in names
    assert "get_k8s_events" in names
    assert "get_pod_logs" in names


def test_alertmanager_sre_agent_dry_run_checkout_500_tool_plan() -> None:
    payload = build_firing_payload(
        alertname="Checkout5xxHigh",
        service="service-catalog",
        namespace="service-catalog",
        cluster="aws-eks",
        summary="checkout endpoint returns HTTP 500 from the catalog API",
    )

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "checkout_500"
    assert result.capability == "checkout_500_analysis"
    assert "get_alb_target_health" in names
    assert "get_cloudfront_origin_mapping" in names
    assert "get_cloudfront_distribution_status" in names
    assert "get_rollout_status" in names


def test_alertmanager_sre_agent_dry_run_sqs_publish_failure_tool_plan() -> None:
    payload = build_firing_payload(
        alertname="SqsPublishFailure",
        service="service-catalog",
        namespace="service-catalog",
        summary="service-catalog failed to sendMessage to SQS",
    )

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "sqs_publish_failure"
    assert result.capability == "sqs_publish_failure_analysis"
    assert "get_sqs_queue_attributes" in names
    assert "get_sqs_dlq_attributes" in names


def test_alertmanager_sre_agent_maps_sqs_dlq_to_consume_failure() -> None:
    payload = {
        "status": "firing",
        "commonLabels": {"cluster": "aws-eks", "namespace": "service-payment"},
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "SqsDLQMessagesVisible",
                    "service": "service-payment",
                    "queue": "credit-payment-requested-dlq.fifo",
                    "severity": "warning",
                },
                "annotations": {
                    "summary": "SQS DLQ has visible messages",
                },
            }
        ],
    }

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "sqs_consume_failure"
    assert result.capability == "sqs_consume_failure_analysis"
    assert "get_sqs_queue_attributes" in names
    assert "get_sqs_dlq_attributes" in names


def test_alertmanager_sre_agent_dry_run_pin_event_missing_tool_plan() -> None:
    payload = build_firing_payload(
        alertname="PinVerificationEventMissing",
        service="service-payment",
        namespace="default",
        summary="PIN verification completed but downstream event was not observed",
    )

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "pin_verification_missing"
    assert result.capability == "pin_verification_missing_analysis"
    assert "get_sqs_queue_attributes" in names
    assert "get_sqs_dlq_attributes" in names


def test_alertmanager_sre_agent_dry_run_cloudfront_alb_eks_routing_tool_plan() -> None:
    payload = build_firing_payload(
        alertname="ALBTargetUnhealthy",
        service="service-catalog",
        namespace="service-catalog",
        cluster="aws-eks",
        summary="CloudFront to ALB to EKS target health is unhealthy",
    )

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "routing_failure"
    assert result.capability == "edge_routing_analysis"
    assert "get_alb_target_health" in names
    assert "get_cloudfront_origin_mapping" in names
    assert "get_cloudfront_distribution_status" in names


def test_alertmanager_sre_agent_dry_run_cloudfront_alb_onprem_routing_tool_plan() -> None:
    payload = build_firing_payload(
        alertname="OnpremMetalLBRoutingFailure",
        service="service-payment",
        namespace="default",
        cluster="onprem",
        summary="CloudFront to ALB to on-prem MetalLB routing failed",
    )

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "routing_failure"
    assert result.capability == "edge_routing_analysis"
    assert "get_cloudfront_origin_mapping" in names
    assert "get_cloudfront_distribution_status" in names
    assert "get_alb_target_health" not in names


def test_alertmanager_sre_agent_dry_run_db_hikaricp_tool_plan() -> None:
    payload = build_firing_payload(
        alertname="HikariPoolExhausted",
        service="service-payment",
        namespace="default",
        summary="HikariCP connection pool is exhausted and PostgreSQL connections time out",
    )

    result = plan_from_payload(payload)

    names = tool_names(result)
    assert_dry_run_read_only_plan(result)
    assert_common_rca_context_tools(result)
    assert result.intent == "db_hikaricp_issue"
    assert result.capability == "db_connection_analysis"
    assert "get_rollout_status" in names
    assert "query_multi_cluster_prometheus" in names
    assert "query_multi_cluster_loki" in names
    assert "get_service_trace_summary" in names


def test_alertmanager_sre_agent_skips_resolved_payload() -> None:
    payload = {
        **POD_CRASH_PAYLOAD,
        "status": "resolved",
        "alerts": [{**POD_CRASH_PAYLOAD["alerts"][0], "status": "resolved"}],
    }

    result = plan_from_payload(payload)

    assert result.status == "SKIPPED"
    assert result.planned_tools == []
    assert result.skipped_reason is not None


def test_alertmanager_sre_webhook_api_returns_dry_run_plan() -> None:
    client = TestClient(create_app())

    response = client.post("/infra-rca/alertmanager/webhook", json=POD_CRASH_PAYLOAD)

    assert response.status_code == 200
    result = response.json()
    assert result["dry_run"] is True
    assert result["status"] == "PLANNED"
    assert result["intent"] == "pod_crashloop"
    assert {tool["tool_name"] for tool in result["planned_tools"]} >= {
        "get_k8s_pods",
        "get_k8s_events",
    }


def test_external_alertmanager_sre_webhook_api_is_exposed() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/infra-rca/alertmanager/webhook",
        json=POD_CRASH_PAYLOAD,
    )

    assert response.status_code == 200
    assert response.json()["trigger_type"] == "ALERTMANAGER"


class FakeReadOnlyDispatcher:
    def __init__(self) -> None:
        self.plans: list[AgentToolPlan] = []

    def execute(self, plan: AgentToolPlan) -> AgentToolExecutionResult:
        self.plans.append(plan)
        tool = resolve_registered_tool(
            server_name=plan.server_name,
            tool_name=plan.tool_name,
        )
        return build_tool_result(
            tool=tool,
            request_payload=plan.request_payload,
            response_payload={
                "ok": True,
                "tool_name": plan.tool_name,
            },
            call_status=McpToolCallStatus.SUCCESS,
            execution_policy=McpExecutionPolicy.ALLOWED,
        )


def test_alertmanager_sre_agent_execute_collects_read_only_evidence_bundle() -> None:
    dispatcher = FakeReadOnlyDispatcher()
    service = AlertmanagerSreAgentService(
        dispatcher=dispatcher,
        now_provider=lambda: datetime(2026, 6, 12, 1, 20, tzinfo=UTC),
    )

    result = service.handle_webhook(
        AlertmanagerWebhookRequest.model_validate(POD_CRASH_PAYLOAD),
        execute=True,
    )

    executed_tool_names = [plan.tool_name for plan in dispatcher.plans]
    assert result.dry_run is False
    assert result.status == "COLLECTED"
    assert result.incident_window is not None
    assert result.incident_window.anchor_time == "2026-06-12T01:00:00Z"
    assert result.incident_window.start == "2026-06-12T00:45:00Z"
    assert result.incident_window.end == "2026-06-12T01:20:00Z"
    assert "create_rca_snapshot" == executed_tool_names[-1]
    assert result.context_bundle is not None
    assert result.context_bundle["incident_window"] == result.incident_window.model_dump(
        mode="json"
    )
    assert result.context_bundle["alertmanager"]["incident_key"] == result.incident_key
    assert result.rca_snapshot is not None
    assert any(
        plan.tool_name == "query_multi_cluster_loki"
        and plan.request_payload["start"] == "2026-06-12T00:45:00Z"
        and plan.request_payload["end"] == "2026-06-12T01:20:00Z"
        for plan in dispatcher.plans
    )
    assert any(
        plan.tool_name == "query_multi_cluster_prometheus"
        and plan.request_payload["time"] == "2026-06-12T01:20:00Z"
        for plan in dispatcher.plans
    )
    rca_plan = dispatcher.plans[-1]
    assert rca_plan.tool_name == "create_rca_snapshot"
    assert rca_plan.request_payload["incident_key"] == result.incident_key
    assert rca_plan.request_payload["context_bundle"]["schema_version"] == (
        "incident_context_bundle.v1"
    )


def test_alertmanager_sre_webhook_execute_query_uses_collection_mode() -> None:
    app = create_app()
    app.state.alertmanager_sre_agent_service = AlertmanagerSreAgentService(
        dispatcher=FakeReadOnlyDispatcher(),
        now_provider=lambda: datetime(2026, 6, 12, 1, 20, tzinfo=UTC),
    )
    client = TestClient(app)

    response = client.post(
        "/infra-rca/alertmanager/webhook?execute=true",
        json=POD_CRASH_PAYLOAD,
    )

    assert response.status_code == 200
    result = response.json()
    assert result["dry_run"] is False
    assert result["status"] == "COLLECTED"
    assert result["incident_window"]["start"] == "2026-06-12T00:45:00Z"
    assert result["executed_tools"]
