from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from aiops_platform.llmops.schemas import LlmRunResult, NotificationOutboxResult
from aiops_platform.main import create_app
from aiops_platform.ops_reports.schemas import (
    IncludedIncident,
    IncludedRcaReport,
    OpsReportCreateRequest,
    OpsReportDetailResult,
    OpsReportEmailRequest,
    OpsReportEmailResult,
    OpsReportGenerationResult,
    OpsReportListResult,
    OpsReportRcaRefResult,
    OpsReportResult,
    ReportIncidentResult,
    ReportMetricSummaryResult,
)
from aiops_platform.ops_reports.service import OpsReportService, OpsReportValidationError
from aiops_platform.orchestration.schemas import JobResult
from aiops_platform.prediction_scaling.schemas import (
    PredictionErrorMetricsResult,
    ScalingEventItem,
    ScalingEventResult,
    ScalingSummaryResult,
)


def test_daily_ops_report_includes_rca_prediction_and_scaling_evidence() -> None:
    repository = FakeOpsReportRepository()
    service = OpsReportService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(),
        llmops_service=FakeLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_sender=FakeEmailSender(),
    )

    result = service.create_ops_report(
        OpsReportCreateRequest(
            report_type="DAILY",
            report_date=date(2026, 6, 6),
            namespace="default",
            service_name="api",
        )
    )

    assert result.report.report_status == "COMPLETED"
    assert result.job.status == "SUCCEEDED"
    assert result.llm_run is not None
    assert result.llm_run.run_status == "SUCCESS"
    assert result.included_incidents
    assert result.included_rca_reports
    assert result.rca_refs
    assert {summary.source_type for summary in result.metric_summaries} >= {
        "ONPREM_PROMETHEUS",
        "KEDA",
        "SCALING",
        "PREDICTION_ERROR",
    }
    assert repository.tool_calls


def test_ops_report_llm_failure_marks_report_and_job_failed() -> None:
    repository = FakeOpsReportRepository()
    service = OpsReportService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(),
        llmops_service=FailingLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
    )

    result = service.create_ops_report(
        OpsReportCreateRequest(report_type="WEEKLY", report_date=date(2026, 6, 6))
    )

    assert result.report.report_status == "FAILED"
    assert result.job.status == "FAILED"
    assert result.llm_run is not None
    assert result.llm_run.run_status == "VALIDATION_FAILED"


def test_send_ops_report_email_creates_notification_outbox_records() -> None:
    repository = FakeOpsReportRepository()
    service = OpsReportService(
        repository=repository,
        orchestration_repository=FakeOrchestrationRepository(),
        llmops_service=FakeLlmOpsService(),
        infraops_service=FakeInfraOpsService(),
        prediction_scaling_service=FakePredictionScalingService(),
        email_sender=FakeEmailSender(),
    )
    report_result = service.create_ops_report(
        OpsReportCreateRequest(report_type="DAILY", report_date=date(2026, 6, 6))
    )

    result = service.send_ops_report_email(
        report_result.report.report_id,
        OpsReportEmailRequest(
            recipients=["ops@example.com", "sre@example.com"],
            subject="[AIOps] Daily report",
        ),
    )

    assert result.channel == "EMAIL"
    assert result.status == "SENT"
    assert len(result.notification_ids) == 2
    assert repository.reports[report_result.report.report_id].report_status == "SENT"


def test_ops_report_api_uses_configured_service() -> None:
    app = create_app()
    app.state.ops_report_service = FakeEndpointOpsReportService()
    client = TestClient(app)

    response = client.post(
        "/reports/ops",
        json={"report_type": "DAILY", "report_date": "2026-06-06"},
    )

    assert response.status_code == 200
    assert response.json()["report"]["report_id"] == "report-1"


def test_ops_report_request_rejects_blank_timezone() -> None:
    with pytest.raises(ValueError, match="timezone is required"):
        OpsReportCreateRequest(
            report_type="DAILY",
            report_date=date(2026, 6, 6),
            timezone=" ",
        )

    request = OpsReportCreateRequest(
        report_type="DAILY",
        report_date=date(2026, 6, 6),
        namespace=" ",
        service_name=" api ",
    )
    assert request.timezone == "Asia/Seoul"
    assert request.namespace is None
    assert request.service_name == "api"


def test_send_ops_report_email_validation_error_returns_400() -> None:
    app = create_app()
    app.state.ops_report_service = FailingEndpointOpsReportService()
    client = TestClient(app)

    response = client.post(
        "/reports/ops/report-1/send-email",
        json={"recipients": ["ops@example.com"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "email request is invalid."


class Dumpable:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def model_dump(self, **kwargs: object) -> dict[str, Any]:
        return self.payload


class FakeInfraOpsService:
    def aggregate_daily_ops_metrics(self, **kwargs: object) -> Dumpable:
        return Dumpable(
            {
                "report_date": kwargs.get("report_date"),
                "partial": False,
                "metrics": {"avg_rps": 42, "p95_latency_ms": 120},
                "sources": [{"source": "prometheus", "status": "SUCCESS"}],
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
            recommendation="Prediction-driven scaling was observed.",
        )

    def get_scaling_events(self, **kwargs: object) -> ScalingEventResult:
        return ScalingEventResult(
            namespace=kwargs.get("namespace"),
            workload=kwargs.get("workload"),
            limit=100,
            items=[
                ScalingEventItem(
                    scaling_event_id="scaling-1",
                    namespace="default",
                    workload="api",
                    event_type="SCALE_UP",
                    trigger_source="PREDICTION",
                    occurred_at="2026-06-06T01:00:00",
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
            metric_name="predicted_rps",
            sample_count=3,
            mean_absolute_error=4.2,
            mean_absolute_percentage_error=0.08,
            root_mean_squared_error=5.1,
        )


class FakeOrchestrationRepository:
    def create_job(self, *, job_type: str, entity_type: str, entity_id: str, status: str):
        return JobResult(
            job_id="job-1",
            job_type=job_type,
            status=status,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at="2026-06-06T00:00:00",
            updated_at="2026-06-06T00:00:00",
        )

    def finish_job(self, *, job_id: str, status: str, error_message: str | None = None):
        return JobResult(
            job_id=job_id,
            job_type="daily_report",
            status=status,
            entity_type="ops_reports",
            entity_id="report-1",
            created_at="2026-06-06T00:00:00",
            updated_at="2026-06-06T00:00:01",
            error_message=error_message,
        )


class FakeLlmOpsService:
    def __init__(self) -> None:
        self.notifications: dict[str, NotificationOutboxResult] = {}

    def run_ops_report_completion(self, **kwargs: object) -> LlmRunResult:
        return LlmRunResult(
            llm_run_id="llm-run-1",
            provider="fake",
            model="fake-agentic-planner",
            prompt_version_id=None,
            prompt_key=f"ops_report.{str(kwargs['report_type']).lower()}.v1",
            run_status="SUCCESS",
            job_id=kwargs.get("job_id"),
            session_id=None,
            masked_input={},
            masked_output={"answer": "Operations remained stable with one RCA."},
            output_schema={"type": "object"},
            validation_errors=[],
            latency_ms=0,
            created_at="2026-06-06T00:00:01",
        )

    def create_notification(self, **kwargs: object) -> NotificationOutboxResult:
        recipient = str(kwargs.get("recipient"))
        notification = NotificationOutboxResult(
            notification_id=f"notification-{recipient}",
            channel="EMAIL",
            recipient=recipient,
            notification_status="PENDING",
            payload=kwargs.get("payload") or {},
            attempts=0,
            created_at="2026-06-06T00:00:02",
        )
        self.notifications[notification.notification_id] = notification
        return notification

    def update_notification_status(
        self,
        notification_id: str,
        *,
        status: str,
        last_error: str | None = None,
    ) -> NotificationOutboxResult:
        notification = self.notifications[notification_id].model_copy(
            update={"notification_status": status, "last_error": last_error}
        )
        self.notifications[notification_id] = notification
        return notification


class FakeEmailSender:
    def send_html(self, *, recipient: str, subject: str, html_body: str) -> None:
        assert recipient
        assert subject
        assert html_body


class FailingLlmOpsService(FakeLlmOpsService):
    def run_ops_report_completion(self, **kwargs: object) -> LlmRunResult:
        return LlmRunResult(
            llm_run_id="llm-run-failed",
            provider="fake",
            model="fake-agentic-planner",
            prompt_version_id=None,
            prompt_key="ops_report.weekly.v1",
            run_status="VALIDATION_FAILED",
            job_id=kwargs.get("job_id"),
            session_id=None,
            masked_input={},
            masked_output={},
            output_schema={"type": "object"},
            validation_errors=["answer is required"],
            latency_ms=0,
            created_at="2026-06-06T00:00:01",
            last_error="answer is required",
        )


class FakeOpsReportRepository:
    def __init__(self) -> None:
        self.reports: dict[str, OpsReportResult] = {}
        self.report_incidents: list[ReportIncidentResult] = []
        self.rca_refs: list[OpsReportRcaRefResult] = []
        self.metric_summaries: list[ReportMetricSummaryResult] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.incidents = [
            IncludedIncident(
                incident_id="incident-1",
                status="ANALYZED",
                severity="CRITICAL",
                alert_name="HighCPUUsage",
                namespace="default",
                workload="api",
                service_name="api",
                summary="High CPU usage detected",
                starts_at="2026-06-06T01:00:00",
                created_at="2026-06-06T01:00:00",
            )
        ]
        self.rcas = [
            IncludedRcaReport(
                rca_report_id="rca-1",
                incident_id="incident-1",
                status="COMPLETED",
                summary="CPU saturation RCA",
                probable_root_cause="Traffic spike",
                confidence=0.75,
                created_at="2026-06-06T01:05:00",
            )
        ]

    def create_ops_report(self, **kwargs: object) -> OpsReportResult:
        report_id = f"report-{len(self.reports) + 1}"
        report = OpsReportResult(
            report_id=report_id,
            report_type=kwargs["report_type"],
            period_start=str(kwargs["period_start"]),
            period_end=str(kwargs["period_end"]),
            timezone=kwargs["timezone"],
            title=kwargs["title"],
            summary=kwargs.get("summary"),
            sections=kwargs["sections"],
            metrics=kwargs["metrics"],
            llm_run_id=kwargs.get("llm_run_id"),
            report_status=kwargs["status"],
            created_at="2026-06-06T00:00:01",
        )
        self.reports[report_id] = report
        return report

    def update_ops_report_status(self, report_id: str, *, status: str):
        report = self.reports.get(report_id)
        if report is None:
            return None
        self.reports[report_id] = report.model_copy(update={"report_status": status})
        return self.reports[report_id]

    def get_ops_report(self, report_id: str):
        return self.reports.get(report_id)

    def list_ops_reports(self, **kwargs: object):
        return list(self.reports.values())[: kwargs["limit"]]

    def list_incidents_for_period(self, **kwargs: object):
        return self.incidents

    def list_rca_reports_for_period(self, **kwargs: object):
        return self.rcas

    def add_report_incident(self, **kwargs: object) -> ReportIncidentResult:
        result = ReportIncidentResult(
            report_incident_id=f"report-incident-{len(self.report_incidents) + 1}",
            report_id=kwargs["report_id"],
            incident_id=kwargs["incident_id"],
            summary=kwargs.get("summary"),
            created_at="2026-06-06T00:00:01",
        )
        self.report_incidents.append(result)
        return result

    def add_report_rca_ref(self, **kwargs: object) -> OpsReportRcaRefResult:
        result = OpsReportRcaRefResult(
            report_rca_ref_id=f"report-rca-ref-{len(self.rca_refs) + 1}",
            report_id=kwargs["report_id"],
            rca_report_id=kwargs["rca_report_id"],
            incident_id=kwargs["incident_id"],
            included_reason=kwargs["included_reason"],
            created_at="2026-06-06T00:00:01",
        )
        self.rca_refs.append(result)
        return result

    def add_metric_summary(self, **kwargs: object) -> ReportMetricSummaryResult:
        result = ReportMetricSummaryResult(
            metric_summary_id=f"metric-summary-{len(self.metric_summaries) + 1}",
            report_id=kwargs["report_id"],
            source_type=kwargs["source_type"],
            namespace=kwargs.get("namespace"),
            service_name=kwargs.get("service_name"),
            metric_name=kwargs["metric_name"],
            period_start=str(kwargs["period_start"]),
            period_end=str(kwargs["period_end"]),
            summary_values=kwargs["summary_values"],
            created_at="2026-06-06T00:00:01",
        )
        self.metric_summaries.append(result)
        return result

    def list_report_incidents(self, report_id: str):
        return self.incidents

    def list_report_rca_reports(self, report_id: str):
        return self.rcas

    def list_report_rca_refs(self, report_id: str):
        return [ref for ref in self.rca_refs if ref.report_id == report_id]

    def list_report_metric_summaries(self, report_id: str):
        return [summary for summary in self.metric_summaries if summary.report_id == report_id]

    def record_mcp_tool_call(self, **kwargs: object) -> str:
        self.tool_calls.append(dict(kwargs))
        return f"tool-call-{len(self.tool_calls)}"


class FakeEndpointOpsReportService:
    def create_ops_report(self, request: OpsReportCreateRequest):
        return build_endpoint_generation_result()

    def list_ops_reports(self, **kwargs: object):
        result = build_endpoint_generation_result()
        return OpsReportListResult(limit=20, items=[result.report])

    def get_ops_report(self, report_id: str):
        result = build_endpoint_generation_result()
        return OpsReportDetailResult(
            report=result.report,
            included_incidents=result.included_incidents,
            included_rca_reports=result.included_rca_reports,
            metric_summaries=result.metric_summaries,
            rca_refs=result.rca_refs,
        )

    def list_metric_summaries(self, report_id: str):
        return build_endpoint_generation_result().metric_summaries

    def send_ops_report_email(self, report_id: str, request: OpsReportEmailRequest):
        return OpsReportEmailResult(report_id=report_id, notification_ids=["notification-1"])


class FailingEndpointOpsReportService(FakeEndpointOpsReportService):
    def send_ops_report_email(self, report_id: str, request: OpsReportEmailRequest):
        raise OpsReportValidationError("email request is invalid.")


def build_endpoint_generation_result() -> OpsReportGenerationResult:
    report = OpsReportResult(
        report_id="report-1",
        report_type="DAILY",
        period_start="2026-06-06T00:00:00",
        period_end="2026-06-07T00:00:00",
        timezone="Asia/Seoul",
        title="Daily operations report",
        summary="ok",
        sections=[],
        metrics={},
        llm_run_id="llm-run-1",
        report_status="COMPLETED",
        created_at="2026-06-06T00:00:01",
    )
    job = JobResult(
        job_id="job-1",
        job_type="daily_report",
        status="SUCCEEDED",
        entity_type="ops_reports",
        entity_id="report-1",
        created_at="2026-06-06T00:00:00",
        updated_at="2026-06-06T00:00:01",
    )
    return OpsReportGenerationResult(
        report=report,
        included_incidents=[],
        included_rca_reports=[],
        metric_summaries=[],
        rca_refs=[],
        job=job,
        llm_run=None,
    )
