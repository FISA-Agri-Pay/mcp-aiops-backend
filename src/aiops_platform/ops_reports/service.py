from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiops_platform.infraops.service import InfraOpsService
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.ops_reports.repository import OpsReportRepository, SqlOpsReportRepository
from aiops_platform.ops_reports.schemas import (
    IncludedIncident,
    IncludedRcaReport,
    OpsReportCreateRequest,
    OpsReportDetailResult,
    OpsReportEmailRequest,
    OpsReportEmailResult,
    OpsReportGenerationResult,
    OpsReportListResult,
    OpsReportResult,
    ReportMetricSummaryResult,
)
from aiops_platform.orchestration.repository import (
    OrchestrationRepository,
    SqlOrchestrationRepository,
)
from aiops_platform.prediction_scaling.service import PredictionScalingService


class OpsReportNotFoundError(LookupError):
    pass


class OpsReportValidationError(ValueError):
    pass


MAX_REPORT_ITEMS = 100


@dataclass(frozen=True)
class ReportPeriod:
    period_start: datetime
    period_end: datetime
    display_start: str
    display_end: str


class OpsReportService:
    def __init__(
        self,
        *,
        repository: OpsReportRepository | None = None,
        orchestration_repository: OrchestrationRepository | None = None,
        llmops_service: LlmOpsService | None = None,
        infraops_service: InfraOpsService | None = None,
        prediction_scaling_service: PredictionScalingService | None = None,
    ) -> None:
        self._repository = repository or SqlOpsReportRepository()
        self._orchestration_repository = (
            orchestration_repository or SqlOrchestrationRepository()
        )
        self._llmops_service = llmops_service or LlmOpsService()
        self._infraops_service = infraops_service or InfraOpsService.from_settings()
        self._prediction_scaling_service = (
            prediction_scaling_service or PredictionScalingService()
        )

    def create_ops_report(
        self,
        request: OpsReportCreateRequest,
    ) -> OpsReportGenerationResult:
        period = resolve_report_period(request.report_date, request.report_type, request.timezone)
        job = self._orchestration_repository.create_job(
            job_type=f"{request.report_type.lower()}_report",
            entity_type="ops_reports",
            entity_id="",
            status="RUNNING",
        )
        try:
            incidents = self._repository.list_incidents_for_period(
                period_start=period.period_start,
                period_end=period.period_end,
                namespace=request.namespace,
                service_name=request.service_name,
                limit=MAX_REPORT_ITEMS,
            )
            rca_reports = (
                self._repository.list_rca_reports_for_period(
                    period_start=period.period_start,
                    period_end=period.period_end,
                    namespace=request.namespace,
                    service_name=request.service_name,
                    limit=MAX_REPORT_ITEMS,
                )
                if request.include_rca
                else []
            )
            metric_inputs = self._collect_metric_inputs(
                request=request,
                period=period,
                job_id=job.job_id,
            )
            metrics = build_report_metrics(
                request=request,
                period=period,
                incidents=incidents,
                rca_reports=rca_reports,
                metric_inputs=metric_inputs,
            )
            llm_run = self._llmops_service.run_ops_report_completion(
                report_type=request.report_type,
                period={
                    "start": period.display_start,
                    "end": period.display_end,
                    "timezone": request.timezone,
                },
                incidents=[incident.model_dump(mode="json") for incident in incidents],
                rca_reports=[rca.model_dump(mode="json") for rca in rca_reports],
                metric_summaries=metric_inputs,
                job_id=job.job_id,
            )
            report_status = "COMPLETED" if llm_run.run_status == "SUCCESS" else "FAILED"
            summary = (
                str(llm_run.masked_output.get("answer"))
                if llm_run.run_status == "SUCCESS"
                else f"Ops report LLM generation failed: {llm_run.run_status}"
            )
            report = self._repository.create_ops_report(
                report_type=request.report_type,
                period_start=period.period_start,
                period_end=period.period_end,
                timezone=request.timezone,
                title=build_report_title(request, period),
                summary=summary,
                sections=build_report_sections(
                    incidents=incidents,
                    rca_reports=rca_reports,
                    metric_inputs=metric_inputs,
                ),
                metrics=metrics,
                llm_run_id=llm_run.llm_run_id,
                status=report_status,
            )
            self._persist_report_children(
                report=report,
                period=period,
                incidents=incidents,
                rca_reports=rca_reports,
                metric_inputs=metric_inputs,
                request=request,
            )
            finished_job = self._orchestration_repository.finish_job(
                job_id=job.job_id,
                status="SUCCEEDED" if llm_run.run_status == "SUCCESS" else "FAILED",
                error_message=llm_run.last_error if llm_run.run_status != "SUCCESS" else None,
            )
            detail = self.get_ops_report(report.report_id)
            return OpsReportGenerationResult(
                report=detail.report,
                included_incidents=detail.included_incidents,
                included_rca_reports=detail.included_rca_reports,
                metric_summaries=detail.metric_summaries,
                rca_refs=detail.rca_refs,
                job=finished_job or job,
                llm_run=llm_run,
            )
        except Exception as exc:
            failed_job = self._orchestration_repository.finish_job(
                job_id=job.job_id,
                status="FAILED",
                error_message=f"Ops report generation failed: {exc.__class__.__name__}",
            )
            report = self._repository.create_ops_report(
                report_type=request.report_type,
                period_start=period.period_start,
                period_end=period.period_end,
                timezone=request.timezone,
                title=build_report_title(request, period),
                summary=f"Ops report generation failed: {exc.__class__.__name__}",
                sections=[],
                metrics={
                    "namespace": request.namespace,
                    "service_name": request.service_name,
                    "error": exc.__class__.__name__,
                },
                llm_run_id=None,
                status="FAILED",
            )
            return OpsReportGenerationResult(
                report=report,
                included_incidents=[],
                included_rca_reports=[],
                metric_summaries=[],
                rca_refs=[],
                job=failed_job or job,
                llm_run=None,
            )

    def list_ops_reports(
        self,
        *,
        report_type: str | None = None,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        namespace: str | None = None,
        service_name: str | None = None,
        limit: int = 20,
    ) -> OpsReportListResult:
        clamped_limit = min(max(limit, 1), 100)
        normalized_report_type = normalize_optional_report_type(report_type)
        normalized_status = normalize_optional_report_status(status)
        start = datetime.combine(date_from, time.min) if date_from else None
        end = datetime.combine(date_to + timedelta(days=1), time.min) if date_to else None
        return OpsReportListResult(
            report_type=normalized_report_type,
            status=normalized_status,
            limit=clamped_limit,
            items=self._repository.list_ops_reports(
                report_type=normalized_report_type,
                status=normalized_status,
                date_from=start,
                date_to=end,
                namespace=normalize_optional_text(namespace),
                service_name=normalize_optional_text(service_name),
                limit=clamped_limit,
            ),
        )

    def get_ops_report(self, report_id: str) -> OpsReportDetailResult:
        report = self._repository.get_ops_report(report_id)
        if report is None:
            raise OpsReportNotFoundError("operations report was not found.")
        return OpsReportDetailResult(
            report=report,
            included_incidents=self._repository.list_report_incidents(report.report_id),
            included_rca_reports=self._repository.list_report_rca_reports(report.report_id),
            metric_summaries=self._repository.list_report_metric_summaries(report.report_id),
            rca_refs=self._repository.list_report_rca_refs(report.report_id),
        )

    def list_metric_summaries(self, report_id: str) -> list[ReportMetricSummaryResult]:
        if self._repository.get_ops_report(report_id) is None:
            raise OpsReportNotFoundError("operations report was not found.")
        return self._repository.list_report_metric_summaries(report_id)

    def send_ops_report_email(
        self,
        report_id: str,
        request: OpsReportEmailRequest,
    ) -> OpsReportEmailResult:
        detail = self.get_ops_report(report_id)
        subject = request.subject or f"[AIOps] {detail.report.title}"
        html_body = build_report_email_html(detail)
        notification_ids = []
        for recipient in request.recipients:
            notification = self._llmops_service.create_notification(
                channel="email",
                title=subject,
                content=html_body,
                payload={
                    "report_id": report_id,
                    "subject": subject,
                    "html_body": html_body,
                    "format": request.format,
                },
                recipient=recipient,
            )
            notification_ids.append(notification.notification_id)
        self._repository.update_ops_report_status(report_id, status="SENT")
        return OpsReportEmailResult(
            report_id=report_id,
            notification_ids=notification_ids,
        )

    def _collect_metric_inputs(
        self,
        *,
        request: OpsReportCreateRequest,
        period: ReportPeriod,
        job_id: str,
    ) -> list[dict[str, Any]]:
        items = [self._collect_infra_metrics(request=request, job_id=job_id)]
        if request.include_prediction_scaling:
            items.extend(self._collect_prediction_scaling_metrics(request=request, job_id=job_id))
        return items

    def _collect_infra_metrics(
        self,
        *,
        request: OpsReportCreateRequest,
        job_id: str,
    ) -> dict[str, Any]:
        request_payload = {
            "report_date": request.report_date.isoformat(),
            "namespace": request.namespace,
            "prometheus_query": "up",
        }
        try:
            result = self._infraops_service.aggregate_daily_ops_metrics(**request_payload)
            response_payload = result.model_dump(mode="json")
            self._record_tool_call(
                server_name="infraops-mcp",
                tool_name="aggregate_daily_ops_metrics",
                request_payload=request_payload,
                response_payload=response_payload,
                call_status="SUCCESS",
                job_id=job_id,
            )
            return {
                "source_type": "ONPREM_PROMETHEUS",
                "metric_name": "daily_ops_metrics",
                "summary_values": response_payload,
            }
        except Exception as exc:
            self._record_tool_call(
                server_name="infraops-mcp",
                tool_name="aggregate_daily_ops_metrics",
                request_payload=request_payload,
                response_payload=None,
                call_status="FAILED",
                job_id=job_id,
                last_error=exc.__class__.__name__,
            )
            return {
                "source_type": "ONPREM_PROMETHEUS",
                "metric_name": "daily_ops_metrics",
                "summary_values": {
                    "status": "FAILED",
                    "error": exc.__class__.__name__,
                },
            }

    def _collect_prediction_scaling_metrics(
        self,
        *,
        request: OpsReportCreateRequest,
        job_id: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        summary_request = {"namespace": request.namespace, "workload": request.service_name}
        try:
            summary = self._prediction_scaling_service.get_scaling_summary(
                **summary_request
            )
            summary_payload = summary.model_dump(mode="json")
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_scaling_summary",
                request_payload=summary_request,
                response_payload=summary_payload,
                call_status="SUCCESS",
                job_id=job_id,
            )
            items.append(
                {
                    "source_type": "KEDA",
                    "metric_name": "scaling_summary",
                    "summary_values": summary_payload,
                }
            )
        except Exception as exc:
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_scaling_summary",
                request_payload=summary_request,
                response_payload=None,
                call_status="FAILED",
                job_id=job_id,
                last_error=exc.__class__.__name__,
            )
            items.append(
                {
                    "source_type": "KEDA",
                    "metric_name": "scaling_summary",
                    "summary_values": {"status": "FAILED", "error": exc.__class__.__name__},
                }
            )
        events_request = {
            "namespace": request.namespace,
            "workload": request.service_name,
            "limit": MAX_REPORT_ITEMS,
        }
        try:
            events = self._prediction_scaling_service.get_scaling_events(**events_request)
            events_payload = events.model_dump(mode="json")
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_scaling_events",
                request_payload=events_request,
                response_payload=events_payload,
                call_status="SUCCESS",
                job_id=job_id,
            )
            items.append(
                {
                    "source_type": "SCALING",
                    "metric_name": "scaling_events",
                    "summary_values": events_payload,
                }
            )
            related_run_ids = {
                event.related_prediction_run_id
                for event in events.items
                if event.related_prediction_run_id is not None
            }
        except Exception as exc:
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_scaling_events",
                request_payload=events_request,
                response_payload=None,
                call_status="FAILED",
                job_id=job_id,
                last_error=exc.__class__.__name__,
            )
            items.append(
                {
                    "source_type": "SCALING",
                    "metric_name": "scaling_events",
                    "summary_values": {"status": "FAILED", "error": exc.__class__.__name__},
                }
            )
            return items
        for prediction_run_id in sorted(related_run_ids):
            error_request = {"prediction_run_id": prediction_run_id}
            try:
                error_metrics = self._prediction_scaling_service.get_prediction_error_metrics(
                    **error_request
                )
                error_payload = error_metrics.model_dump(mode="json")
                self._record_tool_call(
                    server_name="prediction-scaling-mcp",
                    tool_name="get_prediction_error_metrics",
                    request_payload=error_request,
                    response_payload=error_payload,
                    call_status="SUCCESS",
                    job_id=job_id,
                )
                items.append(
                    {
                        "source_type": "PREDICTION_ERROR",
                        "metric_name": "prediction_error_metrics",
                        "summary_values": error_payload,
                    }
                )
            except Exception as exc:
                self._record_tool_call(
                    server_name="prediction-scaling-mcp",
                    tool_name="get_prediction_error_metrics",
                    request_payload=error_request,
                    response_payload=None,
                    call_status="FAILED",
                    job_id=job_id,
                    last_error=exc.__class__.__name__,
                )
                items.append(
                    {
                        "source_type": "PREDICTION_ERROR",
                        "metric_name": "prediction_error_metrics",
                        "summary_values": {
                            "prediction_run_id": prediction_run_id,
                            "status": "FAILED",
                            "error": exc.__class__.__name__,
                        },
                    }
                )
        return items

    def _persist_report_children(
        self,
        *,
        report: OpsReportResult,
        period: ReportPeriod,
        incidents: list[IncludedIncident],
        rca_reports: list[IncludedRcaReport],
        metric_inputs: list[dict[str, Any]],
        request: OpsReportCreateRequest,
    ) -> None:
        for incident in incidents:
            self._repository.add_report_incident(
                report_id=report.report_id,
                incident_id=incident.incident_id,
                summary=incident.summary,
            )
        for rca_report in rca_reports:
            self._repository.add_report_rca_ref(
                report_id=report.report_id,
                rca_report_id=rca_report.rca_report_id,
                incident_id=rca_report.incident_id,
                included_reason=(
                    f"{request.report_type} report period "
                    f"{period.display_start} - {period.display_end}"
                ),
            )
        for metric_input in metric_inputs:
            self._repository.add_metric_summary(
                report_id=report.report_id,
                source_type=metric_input["source_type"],
                namespace=request.namespace,
                service_name=request.service_name,
                metric_name=metric_input["metric_name"],
                period_start=period.period_start,
                period_end=period.period_end,
                summary_values=metric_input["summary_values"],
            )

    def _record_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | list[Any] | None,
        call_status: str,
        job_id: str | None,
        last_error: str | None = None,
    ) -> None:
        self._repository.record_mcp_tool_call(
            server_name=server_name,
            tool_name=tool_name,
            request_payload=request_payload,
            response_payload=response_payload,
            call_status=call_status,
            job_id=job_id,
            last_error=last_error,
        )


def resolve_report_period(
    report_date: date,
    report_type: str,
    timezone: str,
) -> ReportPeriod:
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise OpsReportValidationError("timezone is invalid.") from exc
    start_date = report_date
    if report_type == "WEEKLY":
        start_date = report_date - timedelta(days=report_date.weekday())
    start = datetime.combine(start_date, time.min, tzinfo=tzinfo)
    end = start + (timedelta(days=7) if report_type == "WEEKLY" else timedelta(days=1))
    return ReportPeriod(
        period_start=start.replace(tzinfo=None),
        period_end=end.replace(tzinfo=None),
        display_start=start.isoformat(),
        display_end=end.isoformat(),
    )


def normalize_optional_report_type(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in {"DAILY", "WEEKLY"}:
        raise OpsReportValidationError("report type is invalid.")
    return normalized


def normalize_optional_report_status(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in {"DRAFT", "COMPLETED", "SENT", "FAILED"}:
        raise OpsReportValidationError("report status is invalid.")
    return normalized


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def build_report_title(request: OpsReportCreateRequest, period: ReportPeriod) -> str:
    label = "Daily" if request.report_type == "DAILY" else "Weekly"
    return f"{label} operations report - {period.display_start[:10]}"


def build_report_metrics(
    *,
    request: OpsReportCreateRequest,
    period: ReportPeriod,
    incidents: list[IncludedIncident],
    rca_reports: list[IncludedRcaReport],
    metric_inputs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "report_type": request.report_type,
        "namespace": request.namespace,
        "service_name": request.service_name,
        "period_start": period.display_start,
        "period_end": period.display_end,
        "incident_count": len(incidents),
        "rca_report_count": len(rca_reports),
        "metric_summary_count": len(metric_inputs),
        "critical_incident_count": len(
            [incident for incident in incidents if incident.severity == "CRITICAL"]
        ),
    }


def build_report_sections(
    *,
    incidents: list[IncludedIncident],
    rca_reports: list[IncludedRcaReport],
    metric_inputs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "title": "Incidents",
            "summary": f"{len(incidents)} incidents included.",
            "items": [incident.model_dump(mode="json") for incident in incidents[:10]],
        },
        {
            "title": "RCA",
            "summary": f"{len(rca_reports)} RCA reports included.",
            "items": [rca.model_dump(mode="json") for rca in rca_reports[:10]],
        },
        {
            "title": "Prediction and scaling",
            "summary": f"{len(metric_inputs)} metric summaries included.",
            "items": metric_inputs[:10],
        },
    ]


def build_report_email_html(detail: OpsReportDetailResult) -> str:
    report = detail.report
    incident_rows = "".join(
        "<tr>"
        f"<td>{html.escape(incident.severity)}</td>"
        f"<td>{html.escape(incident.alert_name or '')}</td>"
        f"<td>{html.escape(incident.summary or '')}</td>"
        "</tr>"
        for incident in detail.included_incidents
    )
    rca_rows = "".join(
        "<tr>"
        f"<td>{html.escape(rca.status)}</td>"
        f"<td>{html.escape(rca.summary or '')}</td>"
        f"<td>{html.escape(rca.probable_root_cause or '')}</td>"
        "</tr>"
        for rca in detail.included_rca_reports
    )
    return (
        "<html><body>"
        f"<h1>{html.escape(report.title)}</h1>"
        f"<p>{html.escape(report.summary or '')}</p>"
        "<h2>Incidents</h2>"
        "<table><thead><tr><th>Severity</th><th>Alert</th><th>Summary</th></tr></thead>"
        f"<tbody>{incident_rows}</tbody></table>"
        "<h2>RCA</h2>"
        "<table><thead><tr><th>Status</th><th>Summary</th><th>Root cause</th></tr></thead>"
        f"<tbody>{rca_rows}</tbody></table>"
        "</body></html>"
    )
