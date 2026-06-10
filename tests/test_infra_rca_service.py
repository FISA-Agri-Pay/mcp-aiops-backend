from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aiops_platform.infra_rca.repository import ScheduledRcaJobRecord
from aiops_platform.infra_rca.schemas import (
    AlertmanagerAlert,
    AlertmanagerWebhookRequest,
    AlertWebhookResult,
    IncidentAlertResult,
    IncidentResult,
    ObservabilitySnapshotResult,
    RcaReportEmailRequest,
    RcaReportResult,
    SnapshotItemResult,
)
from aiops_platform.infra_rca.service import (
    InfraRcaService,
    InfraRcaValidationError,
    build_loki_query,
    build_prometheus_query,
    parse_alert_timestamp,
    resolve_dedup_key,
    resolve_fingerprint,
)
from aiops_platform.llmops.schemas import LlmRunResult, NotificationOutboxResult
from aiops_platform.main import create_app
from aiops_platform.orchestration.schemas import JobResult
from aiops_platform.prediction_scaling.schemas import (
    PredictionErrorMetricsResult,
    ScalingEventItem,
    ScalingEventResult,
    ScalingSummaryResult,
)

ALERT_PAYLOAD = {
    "receiver": "aiops-platform",
    "status": "firing",
    "alerts": [
        {
            "status": "firing",
            "labels": {
                "alertname": "HighCPUUsage",
                "namespace": "default",
                "service": "api",
                "workload": "api",
                "severity": "critical",
            },
            "annotations": {
                "summary": "High CPU usage detected",
                "description": "CPU usage exceeded threshold for api service",
            },
            "startsAt": "2026-06-06T01:00:00Z",
            "endsAt": "0001-01-01T00:00:00Z",
            "fingerprint": "highcpu-default-api-001",
        }
    ],
    "commonLabels": {"namespace": "default", "service": "api"},
    "commonAnnotations": {"summary": "High CPU usage detected"},
    "externalURL": "http://localhost:9093",
}


def test_alertmanager_webhook_generates_rca_report() -> None:
    repository = FakeInfraRcaRepository()
    service = InfraRcaService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(repository),
        llmops_service=FakeLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_recipients=[],
    )

    webhook_result = service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD)
    )
    assert webhook_result.job is not None
    assert webhook_result.job.status == "QUEUED"
    assert webhook_result.rca_report is None
    result = service.run_due_rca_jobs().items[0]

    assert result.incident.alert_name == "HighCPUUsage"
    assert result.incident.severity == "CRITICAL"
    assert result.job is not None
    assert result.job.status == "SUCCEEDED"
    assert result.snapshot is not None
    assert result.snapshot.time_start.startswith("2026-06-06 00:50:00")
    assert result.snapshot.time_end.startswith("2026-06-06 01:05:00")
    assert {item.source_type for item in result.snapshot.items} >= {
        "PROMETHEUS",
        "KUBERNETES",
        "KEDA",
        "PREDICTION",
    }
    assert result.rca_report is not None
    assert result.rca_report.status == "COMPLETED"


def test_alertmanager_webhook_sends_preliminary_and_final_rca_email() -> None:
    repository = FakeInfraRcaRepository()
    llmops_service = FakeLlmOpsService()
    email_sender = FakeEmailSender()
    service = InfraRcaService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(repository),
        llmops_service=llmops_service,
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_sender=email_sender,
        email_recipients=["ops@example.com"],
    )

    webhook_result = service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD)
    )
    result = service.run_due_rca_jobs().items[0]

    assert webhook_result.preliminary_notification_ids == ["notification-1"]
    assert result.final_notification_ids == ["notification-3"]
    stages = [
        notification.payload["notification_stage"]
        for notification in llmops_service.notifications
        if "notification_stage" in notification.payload
    ]
    assert stages == ["preliminary", "final"]
    assert [message["recipient"] for message in email_sender.sent_messages] == [
        "ops@example.com",
        "ops@example.com",
    ]


def test_send_rca_report_email_sends_existing_report() -> None:
    repository = FakeInfraRcaRepository()
    llmops_service = FakeLlmOpsService()
    email_sender = FakeEmailSender()
    service = InfraRcaService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(repository),
        llmops_service=llmops_service,
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_sender=email_sender,
        email_recipients=[],
    )
    service.handle_alertmanager_webhook(AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD))
    service.run_due_rca_jobs()

    result = service.send_rca_report_email(
        "rca-report-1",
        RcaReportEmailRequest(recipients=["ops@example.com"]),
    )

    assert result.status == "SENT"
    assert result.notification_ids == ["notification-2"]
    assert email_sender.sent_messages[0]["recipient"] == "ops@example.com"


def test_resolved_alert_records_incident_without_rca() -> None:
    payload = {
        **ALERT_PAYLOAD,
        "status": "resolved",
        "alerts": [{**ALERT_PAYLOAD["alerts"][0], "status": "resolved"}],
    }
    service = InfraRcaService(
        repository=FakeInfraRcaRepository(),
        orchestration_repository=FakeOrchestrationRepository(),
        llmops_service=FakeLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_recipients=[],
    )

    result = service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(payload)
    )

    assert result.incident.status == "RESOLVED"
    assert result.job is None
    assert result.rca_report is None
    assert "skipped" in result.message


def test_duplicate_firing_alert_skips_second_rca_generation() -> None:
    repository = FakeInfraRcaRepository()
    service = InfraRcaService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(repository),
        llmops_service=FakeLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_recipients=[],
    )

    first = service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD)
    )
    second = service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD)
    )

    assert first.duplicate is False
    assert first.job is not None
    assert first.job.status == "QUEUED"
    assert first.rca_report is None
    assert second.duplicate is True
    assert second.job is None
    assert second.rca_report is None
    assert "Duplicate" in second.message
    service.run_due_rca_jobs()
    assert repository.created_rca_reports == 1


def test_prediction_scaling_failure_is_recorded_as_partial_evidence() -> None:
    repository = FakeInfraRcaRepository()
    service = InfraRcaService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(repository),
        llmops_service=FakeLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FailingPredictionScalingService(),
        email_recipients=[],
    )

    service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD)
    )
    result = service.run_due_rca_jobs().items[0]

    assert result.job is not None
    assert result.job.status == "SUCCEEDED"
    assert result.rca_report is not None
    assert result.rca_report.confidence == 0.55
    assert result.snapshot is not None
    failed_items = [item for item in result.snapshot.items if item.last_error]
    assert any("get_scaling_summary failed" in item.last_error for item in failed_items)
    assert any("get_scaling_events failed" in item.last_error for item in failed_items)


def test_llm_failure_does_not_create_rca_report() -> None:
    repository = FakeInfraRcaRepository()
    service = InfraRcaService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(repository),
        llmops_service=FailingLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_recipients=[],
    )

    service.handle_alertmanager_webhook(
        AlertmanagerWebhookRequest.model_validate(ALERT_PAYLOAD)
    )
    result = service.run_due_rca_jobs().items[0]

    assert result.incident.status == "INVESTIGATING"
    assert result.job is not None
    assert result.job.status == "FAILED"
    assert result.rca_report is None
    assert result.snapshot is not None
    assert "LLM generation failed" in result.message
    assert repository.created_rca_reports == 0


def test_invalid_alert_timestamp_raises_validation_error() -> None:
    with pytest.raises(InfraRcaValidationError, match="not-a-date"):
        parse_alert_timestamp("not-a-date")


def test_blank_alert_fingerprint_falls_back_to_hash() -> None:
    labels = {
        "alertname": "HighCPUUsage",
        "namespace": "default",
        "service": "api",
        "workload": "api",
    }

    fingerprint = resolve_fingerprint(AlertmanagerAlert(fingerprint="   "), labels)
    dedup_key = resolve_dedup_key(fingerprint, labels)

    assert fingerprint
    assert fingerprint != ""
    assert dedup_key.endswith(fingerprint)


def test_metric_queries_escape_service_label_values() -> None:
    labels = {"service": 'api"prod\\blue\n'}

    assert build_prometheus_query(labels) == 'up{service="api\\"prod\\\\blue\\n"}'
    assert build_loki_query(labels) == '{service="api\\"prod\\\\blue\\n"}'


def test_metric_queries_fallback_on_blank_service_label() -> None:
    labels = {"service": "   "}

    assert build_prometheus_query(labels) == "up"
    assert build_loki_query(labels) == '{job=~".+"}'


def test_alertmanager_webhook_api_uses_configured_service() -> None:
    app = create_app()
    app.state.infra_rca_service = FakeEndpointRcaService()
    client = TestClient(app)

    response = client.post("/alerts/webhook", json=ALERT_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["incident"]["incident_id"] == "incident-1"


def test_alertmanager_api_alert_alias_uses_configured_service() -> None:
    app = create_app()
    app.state.infra_rca_service = FakeEndpointRcaService()
    client = TestClient(app)

    response = client.post("/api/alerts", json=ALERT_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["incident"]["incident_id"] == "incident-1"


class Dumpable:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, **kwargs: object) -> dict[str, Any]:
        return self.payload


class FakeInfraOpsService:
    def create_rca_snapshot(self, **kwargs: object) -> Dumpable:
        return Dumpable(
            {
                "incident_key": kwargs["incident_key"],
                "partial": False,
                "sources": [
                    {"source": "prometheus", "status": "SUCCESS", "data": {"up": 1}},
                    {"source": "kubernetes", "status": "SUCCESS", "data": {"pods": []}},
                ],
            }
        )


class FakePredictionScalingService:
    def get_scaling_summary(self, **kwargs: object) -> ScalingSummaryResult:
        return ScalingSummaryResult(
            namespace=kwargs.get("namespace"),
            workload=kwargs.get("workload"),
            total_events=1,
            prediction_driven_events=1,
            latest_desired_replicas=4,
            max_desired_replicas=4,
            recommendation="Prediction-driven scale-up was observed.",
        )

    def get_scaling_events(self, **kwargs: object) -> ScalingEventResult:
        return ScalingEventResult(
            namespace=kwargs.get("namespace"),
            workload=kwargs.get("workload"),
            limit=20,
            items=[
                ScalingEventItem(
                    scaling_event_id="scaling-1",
                    namespace="default",
                    workload="api",
                    event_type="SCALE_UP",
                    trigger_source="PREDICTION",
                    occurred_at="2026-06-06T01:01:00",
                    previous_replicas=2,
                    desired_replicas=4,
                    reason="predicted_rps crossed threshold",
                    related_prediction_run_id="prediction-run-1",
                )
            ],
        )

    def get_prediction_error_metrics(self, **kwargs: object) -> PredictionErrorMetricsResult:
        return PredictionErrorMetricsResult(
            prediction_run_id=kwargs["prediction_run_id"],
            metric_name="http_requests_per_second",
            sample_count=3,
            mean_absolute_error=6.7,
            mean_absolute_percentage_error=0.05,
            root_mean_squared_error=7.1,
        )


class FailingPredictionScalingService:
    def get_scaling_summary(self, **kwargs: object) -> ScalingSummaryResult:
        raise RuntimeError("scaling summary unavailable")

    def get_scaling_events(self, **kwargs: object) -> ScalingEventResult:
        raise RuntimeError("scaling events unavailable")


class FakeOrchestrationRepository:
    def __init__(self, rca_repository: FakeInfraRcaRepository | None = None) -> None:
        self._rca_repository = rca_repository

    def create_job(
        self,
        *,
        job_type: str,
        entity_type: str,
        entity_id: str,
        status: str,
        scheduled_at: str | None = None,
        job_context: dict[str, Any] | None = None,
    ):
        job_id = "00000000-0000-0000-0000-000000000101"
        if self._rca_repository is not None and job_context is not None:
            self._rca_repository.scheduled_jobs.append(
                ScheduledRcaJobRecord(
                    job_id=job_id,
                    incident_id=entity_id,
                    scheduled_at=scheduled_at,
                    context=job_context,
                )
            )
        return JobResult(
            job_id=job_id,
            job_type=job_type,
            status=status,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at="2026-06-06T01:00:00",
            updated_at="2026-06-06T01:00:00",
        )

    def finish_job(self, *, job_id: str, status: str, error_message: str | None = None):
        return JobResult(
            job_id=job_id,
            job_type="rca",
            status=status,
            entity_type="incidents",
            entity_id="incident-1",
            created_at="2026-06-06T01:00:00",
            updated_at="2026-06-06T01:00:01",
            error_message=error_message,
        )


class FakeLlmOpsService:
    def __init__(self) -> None:
        self.notifications: list[NotificationOutboxResult] = []
        self.status_updates: list[dict[str, object]] = []

    def run_rca_completion(self, **kwargs: object) -> LlmRunResult:
        return LlmRunResult(
            llm_run_id="00000000-0000-0000-0000-000000000201",
            provider="fake",
            model="fake-agentic-planner",
            prompt_version_id=None,
            prompt_key="rca.infra.v1",
            run_status="SUCCESS",
            job_id=kwargs.get("job_id"),
            session_id=None,
            masked_input={},
            masked_output={"answer": "CPU saturation correlated with prediction scale-up."},
            output_schema={"type": "object"},
            validation_errors=[],
            latency_ms=0,
            created_at="2026-06-06T01:00:01",
        )

    def create_notification(self, **kwargs: object) -> NotificationOutboxResult:
        notification = NotificationOutboxResult(
            notification_id=f"notification-{len(self.notifications) + 1}",
            channel=str(kwargs.get("channel") or "DASHBOARD").upper(),
            recipient=kwargs.get("recipient"),
            notification_status="PENDING",
            payload=kwargs.get("payload") or {},
            related_table=kwargs.get("related_table"),
            related_public_id=kwargs.get("related_public_id"),
            idempotency_key=kwargs.get("idempotency_key"),
            attempts=0,
            created_at="2026-06-06T01:00:02",
        )
        self.notifications.append(notification)
        return notification

    def update_notification_status(
        self,
        notification_id: str,
        *,
        status: str,
        last_error: str | None = None,
    ) -> NotificationOutboxResult:
        self.status_updates.append(
            {
                "notification_id": notification_id,
                "status": status,
                "last_error": last_error,
            }
        )
        notification = next(
            item for item in self.notifications if item.notification_id == notification_id
        )
        updated = notification.model_copy(
            update={"notification_status": status, "last_error": last_error}
        )
        self.notifications = [
            updated if item.notification_id == notification_id else item
            for item in self.notifications
        ]
        return updated


class FailingLlmOpsService(FakeLlmOpsService):
    def run_rca_completion(self, **kwargs: object) -> LlmRunResult:
        return LlmRunResult(
            llm_run_id="00000000-0000-0000-0000-000000000202",
            provider="fake",
            model="fake-agentic-planner",
            prompt_version_id=None,
            prompt_key="rca.infra.v1",
            run_status="VALIDATION_FAILED",
            job_id=kwargs.get("job_id"),
            session_id=None,
            masked_input={},
            masked_output={},
            output_schema={"type": "object"},
            validation_errors=["answer is required"],
            latency_ms=0,
            created_at="2026-06-06T01:00:01",
            last_error="LLM output validation failed.",
        )


class FakeInfraRcaRepository:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.items: list[SnapshotItemResult] = []
        self.duplicate = duplicate
        self.created_rca_reports = 0
        self.incident: IncidentResult | None = None
        self.rca_report: RcaReportResult | None = None
        self.seen_fingerprints: set[str] = set()
        self.scheduled_jobs: list[ScheduledRcaJobRecord] = []

    def upsert_incident(self, **kwargs: object) -> IncidentResult:
        self.incident = IncidentResult(
            incident_id="incident-1",
            dedup_key=str(kwargs["dedup_key"]),
            source_type="ALERTMANAGER",
            status=kwargs["status"],
            severity=kwargs["severity"],
            alert_name=kwargs.get("alert_name"),
            namespace=kwargs.get("namespace"),
            workload=kwargs.get("workload"),
            service_name=kwargs.get("service_name"),
            summary=kwargs.get("summary"),
            starts_at=stringify_dt(kwargs.get("starts_at")),
            ends_at=stringify_dt(kwargs.get("ends_at")),
            created_at="2026-06-06T01:00:00",
            updated_at="2026-06-06T01:00:00",
        )
        return self.incident

    def upsert_incident_alert(self, **kwargs: object):
        fingerprint = str(kwargs["fingerprint"])
        duplicate = self.duplicate or fingerprint in self.seen_fingerprints
        self.seen_fingerprints.add(fingerprint)
        return (
            IncidentAlertResult(
                incident_alert_id="incident-alert-1",
                incident_id=kwargs["incident_id"],
                fingerprint=fingerprint,
                status=kwargs["status"],
                starts_at=stringify_dt(kwargs.get("starts_at")),
                ends_at=stringify_dt(kwargs.get("ends_at")),
                received_at="2026-06-06T01:00:00",
            ),
            duplicate,
        )

    def update_incident_status(self, incident_id: str, *, status: str):
        if self.incident is None:
            return None
        self.incident = self.incident.model_copy(
            update={"status": status, "updated_at": "2026-06-06T01:00:01"}
        )
        return self.incident

    def create_observability_snapshot(self, **kwargs: object) -> ObservabilitySnapshotResult:
        return ObservabilitySnapshotResult(
            snapshot_id="snapshot-1",
            incident_id=kwargs["incident_id"],
            snapshot_type="RCA",
            time_start=stringify_dt(kwargs["time_start"]),
            time_end=stringify_dt(kwargs["time_end"]),
            status="COLLECTING",
            summary=kwargs["summary"],
            items=[],
            created_at="2026-06-06T01:00:00",
        )

    def add_snapshot_item(self, **kwargs: object) -> SnapshotItemResult:
        item = SnapshotItemResult(
            snapshot_item_id=f"snapshot-item-{len(self.items) + 1}",
            source_type=kwargs["source_type"],
            tool_name=kwargs["tool_name"],
            summary=kwargs.get("summary"),
            last_error=kwargs.get("last_error"),
        )
        self.items.append(item)
        return item

    def complete_observability_snapshot(self, snapshot_id: str, *, status: str, summary: str):
        return ObservabilitySnapshotResult(
            snapshot_id=snapshot_id,
            incident_id="incident-1",
            snapshot_type="RCA",
            time_start="2026-06-06 00:50:00",
            time_end="2026-06-06 01:05:00",
            status=status,
            summary=summary,
            items=[],
            created_at="2026-06-06T01:00:00",
        )

    def create_rca_report(self, **kwargs: object) -> RcaReportResult:
        self.created_rca_reports += 1
        self.rca_report = RcaReportResult(
            rca_report_id="rca-report-1",
            incident_id=kwargs["incident_id"],
            llm_run_id=kwargs["llm_run_id"],
            snapshot_id=kwargs["snapshot_id"],
            status=kwargs["status"],
            summary=kwargs["summary"],
            probable_root_cause=kwargs["probable_root_cause"],
            impact=kwargs["impact"],
            timeline=kwargs["timeline"],
            evidence=kwargs["evidence"],
            recommended_actions=kwargs["recommended_actions"],
            confidence=kwargs["confidence"],
            prompt_version=kwargs["prompt_version"],
            created_at="2026-06-06T01:00:01",
        )
        return self.rca_report

    def get_rca_report(self, rca_report_id: str) -> RcaReportResult | None:
        if self.rca_report is not None and self.rca_report.rca_report_id == rca_report_id:
            return self.rca_report
        return None

    def record_mcp_tool_call(self, **kwargs: object) -> str:
        return f"tool-call-{kwargs['tool_name']}"

    def list_due_rca_jobs(self, **kwargs: object) -> list[ScheduledRcaJobRecord]:
        return self.scheduled_jobs[: int(kwargs["limit"])]

    def mark_rca_job_running(self, job_id: str) -> bool:
        return any(job.job_id == job_id for job in self.scheduled_jobs)


class FakeEndpointRcaService:
    def handle_alertmanager_webhook(self, request: AlertmanagerWebhookRequest):
        incident = IncidentResult(
            incident_id="incident-1",
            dedup_key="HighCPUUsage:default:api",
            source_type="ALERTMANAGER",
            status="ANALYZED",
            severity="CRITICAL",
            alert_name="HighCPUUsage",
            namespace="default",
            workload="api",
            service_name="api",
            summary="High CPU usage detected",
            starts_at="2026-06-06T01:00:00",
            ends_at=None,
            created_at="2026-06-06T01:00:00",
            updated_at="2026-06-06T01:00:01",
        )
        alert = IncidentAlertResult(
            incident_alert_id="incident-alert-1",
            incident_id="incident-1",
            fingerprint="highcpu-default-api-001",
            status="FIRING",
            starts_at="2026-06-06T01:00:00",
            ends_at=None,
            received_at="2026-06-06T01:00:00",
        )
        return AlertWebhookResult(
            incident=incident,
            alert=alert,
            message="ok",
        )


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str]] = []

    def send_html(self, *, recipient: str, subject: str, html_body: str) -> None:
        self.sent_messages.append(
            {
                "recipient": recipient,
                "subject": subject,
                "html_body": html_body,
            }
        )


def stringify_dt(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value)
