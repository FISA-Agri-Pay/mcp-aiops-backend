from fastapi.testclient import TestClient

from aiops_platform.alertmanager_agent.service import AlertmanagerSreAgentService
from aiops_platform.infra_rca.schemas import AlertmanagerWebhookRequest
from aiops_platform.main import create_app


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


def test_alertmanager_sre_agent_plans_pod_crashloop_read_tools() -> None:
    service = AlertmanagerSreAgentService()

    result = service.plan_from_webhook(
        AlertmanagerWebhookRequest.model_validate(POD_CRASH_PAYLOAD)
    )

    tool_names = {tool.tool_name for tool in result.planned_tools}
    assert result.status == "PLANNED"
    assert result.incident_key == (
        "alertmanager:podcrashlooping:onprem:service-catalog:service-catalog:critical"
    )
    assert result.intent == "pod_crashloop"
    assert result.capability == "pod_crashloop_analysis"
    assert "get_k8s_pods" in tool_names
    assert "get_k8s_events" in tool_names
    assert "get_pod_logs" in tool_names
    assert "delete_pod" not in tool_names
    assert "run_kubectl_exec" not in tool_names


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
    service = AlertmanagerSreAgentService()

    result = service.plan_from_webhook(AlertmanagerWebhookRequest.model_validate(payload))

    tool_names = [tool.tool_name for tool in result.planned_tools]
    assert result.intent == "sqs_consume_failure"
    assert result.capability == "sqs_consume_failure_analysis"
    assert "get_sqs_queue_attributes" in tool_names
    assert "get_sqs_dlq_attributes" in tool_names


def test_alertmanager_sre_agent_skips_resolved_payload() -> None:
    payload = {
        **POD_CRASH_PAYLOAD,
        "status": "resolved",
        "alerts": [{**POD_CRASH_PAYLOAD["alerts"][0], "status": "resolved"}],
    }
    service = AlertmanagerSreAgentService()

    result = service.plan_from_webhook(AlertmanagerWebhookRequest.model_validate(payload))

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
