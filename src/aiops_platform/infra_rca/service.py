from __future__ import annotations

import hashlib
import html
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from aiops_platform.core.config import settings
from aiops_platform.infra_rca.repository import (
    InfraRcaRepository,
    ScheduledRcaJobRecord,
    SqlInfraRcaRepository,
)
from aiops_platform.infra_rca.schemas import (
    AlertmanagerAlert,
    AlertmanagerWebhookRequest,
    AlertWebhookResult,
    DueRcaJobResult,
    DueRcaJobRunResult,
    IncidentResult,
    ObservabilitySnapshotResult,
    RcaReportEmailRequest,
    RcaReportEmailResult,
    RcaReportResult,
)
from aiops_platform.infraops.service import InfraOpsService
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.ops_reports.email_delivery import EmailSender, SmtpEmailSender
from aiops_platform.orchestration.repository import (
    OrchestrationRepository,
    SqlOrchestrationRepository,
)
from aiops_platform.orchestration.schemas import JobResult
from aiops_platform.prediction_scaling.service import (
    PredictionScalingService,
)


class InfraRcaValidationError(ValueError):
    pass


class InfraRcaNotFoundError(LookupError):
    pass


logger = logging.getLogger(__name__)


class InfraRcaService:
    def __init__(
        self,
        *,
        repository: InfraRcaRepository | None = None,
        orchestration_repository: OrchestrationRepository | None = None,
        llmops_service: LlmOpsService | None = None,
        infraops_service: InfraOpsService | None = None,
        prediction_scaling_service: PredictionScalingService | None = None,
        email_sender: EmailSender | None = None,
        email_recipients: list[str] | None = None,
    ) -> None:
        self._repository = repository or SqlInfraRcaRepository()
        self._orchestration_repository = (
            orchestration_repository or SqlOrchestrationRepository()
        )
        self._llmops_service = llmops_service or LlmOpsService()
        self._infraops_service = infraops_service or InfraOpsService.from_settings()
        self._prediction_scaling_service = (
            prediction_scaling_service or PredictionScalingService()
        )
        self._email_sender = email_sender or SmtpEmailSender()
        self._email_recipients = email_recipients

    def handle_alertmanager_webhook(
        self,
        request: AlertmanagerWebhookRequest,
    ) -> AlertWebhookResult:
        alert = select_primary_alert(request)
        labels = {**request.commonLabels, **alert.labels}
        annotations = {**request.commonAnnotations, **alert.annotations}
        status = normalize_alert_status(alert.status or request.status)
        starts_at = parse_alert_timestamp(alert.startsAt)
        ends_at = parse_alert_timestamp(alert.endsAt)
        fingerprint = resolve_fingerprint(alert, labels)
        dedup_key = resolve_dedup_key(fingerprint, labels)
        incident = self._repository.upsert_incident(
            dedup_key=dedup_key,
            status="RESOLVED" if status == "RESOLVED" else "FIRING",
            severity=resolve_severity(labels),
            alert_name=labels.get("alertname"),
            namespace=labels.get("namespace"),
            workload=labels.get("workload") or labels.get("deployment") or labels.get("pod"),
            service_name=labels.get("service") or labels.get("app"),
            summary=resolve_alert_summary(labels, annotations),
            labels=labels,
            annotations=annotations,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        incident_alert, duplicate = self._repository.upsert_incident_alert(
            incident_id=incident.incident_id,
            fingerprint=fingerprint,
            status=status,
            event_payload=request.model_dump(mode="json"),
            labels=labels,
            annotations=annotations,
            starts_at=starts_at,
            ends_at=ends_at,
        )
        if status == "RESOLVED":
            return AlertWebhookResult(
                incident=incident,
                alert=incident_alert,
                duplicate=duplicate,
                message="Resolved alert was recorded; RCA generation was skipped.",
            )
        if duplicate:
            return AlertWebhookResult(
                incident=incident,
                alert=incident_alert,
                duplicate=True,
                message="Duplicate firing alert was recorded; RCA generation was skipped.",
            )

        preliminary_notification_ids, _ = self._send_rca_notifications(
            stage="preliminary",
            incident=incident,
            rca_report=None,
            subject=build_preliminary_subject(incident),
            html_body=build_preliminary_email_html(
                incident=incident,
                starts_at=starts_at,
            ),
        )
        job = self._orchestration_repository.create_job(
            job_type="rca",
            entity_type="incidents",
            entity_id=incident.incident_id,
            status="QUEUED",
            scheduled_at=resolve_rca_run_after(starts_at).isoformat(sep=" "),
            job_context={
                "incident": incident.model_dump(mode="json"),
                "alert": incident_alert.model_dump(mode="json"),
                "labels": labels,
                "alert_starts_at": (
                    starts_at or datetime.now(UTC).replace(tzinfo=None)
                ).isoformat(sep=" "),
                "window_start": resolve_rca_window_start(starts_at).isoformat(sep=" "),
                "window_end": resolve_rca_run_after(starts_at).isoformat(sep=" "),
            },
        )
        return AlertWebhookResult(
            incident=incident,
            alert=incident_alert,
            job=job,
            preliminary_notification_ids=preliminary_notification_ids,
            duplicate=duplicate,
            message=(
                "Alertmanager webhook was recorded and RCA generation was "
                "scheduled after the evidence window closes."
            ),
        )

    def run_due_rca_jobs(
        self,
        *,
        due_at: datetime | None = None,
        limit: int = 10,
    ) -> DueRcaJobRunResult:
        clamped_limit = min(max(limit, 1), 50)
        due_at = due_at or datetime.now(UTC).replace(tzinfo=None)
        jobs = self._repository.list_due_rca_jobs(
            due_at=due_at,
            limit=clamped_limit,
        )
        items = []
        for job in jobs:
            if not self._repository.mark_rca_job_running(job.job_id):
                continue
            items.append(self._run_scheduled_rca_job(job))
        return DueRcaJobRunResult(processed_count=len(items), items=items)

    def _run_scheduled_rca_job(self, job: ScheduledRcaJobRecord) -> DueRcaJobResult:
        incident = IncidentResult.model_validate(job.context["incident"])
        alert = dict(job.context.get("alert") or {})
        labels = dict(job.context.get("labels") or {})
        starts_at = parse_stored_datetime(
            job.context.get("alert_starts_at"),
            fallback=datetime.now(UTC).replace(tzinfo=None),
        )
        try:
            snapshot = self._create_rca_snapshot(
                incident=incident,
                alert=alert,
                labels=labels,
                starts_at=starts_at,
                job_id=job.job_id,
            )
            evidence = build_evidence(snapshot)
            llm_run = self._llmops_service.run_rca_completion(
                incident=incident.model_dump(mode="json"),
                alert=alert,
                snapshot=snapshot.model_dump(mode="json"),
                evidence=evidence,
                job_id=job.job_id,
            )
            if llm_run.run_status != "SUCCESS":
                failed_incident = self._repository.update_incident_status(
                    incident.incident_id,
                    status="INVESTIGATING",
                )
                failed_job = self._orchestration_repository.finish_job(
                    job_id=job.job_id,
                    status="FAILED",
                    error_message=f"RCA LLM run failed: {llm_run.run_status}",
                )
                self._llmops_service.create_notification(
                    channel="dashboard",
                    title="RCA generation failed",
                    content=f"RCA LLM run finished with {llm_run.run_status}.",
                    payload={
                        "incident_id": incident.incident_id,
                        "snapshot_id": snapshot.snapshot_id,
                        "llm_run_id": llm_run.llm_run_id,
                        "run_status": llm_run.run_status,
                        "last_error": llm_run.last_error,
                        "validation_errors": llm_run.validation_errors,
                    },
                    recipient="infra-admin",
                )
                return DueRcaJobResult(
                    incident=failed_incident or incident,
                    job=failed_job or build_running_job(job),
                    snapshot=snapshot,
                    message="Due RCA job ran, but LLM generation failed.",
                )
            rca_report = self._create_rca_report(
                incident=incident,
                snapshot=snapshot,
                llm_run_id=llm_run.llm_run_id,
                llm_output=llm_run.masked_output,
                evidence=evidence,
            )
            analyzed_incident = self._repository.update_incident_status(
                incident.incident_id,
                status="ANALYZED",
            )
            finished_job = self._orchestration_repository.finish_job(
                job_id=job.job_id,
                status="SUCCEEDED",
            )
            self._llmops_service.create_notification(
                channel="dashboard",
                title="RCA report is ready",
                content=rca_report.summary or "RCA report is ready for review.",
                payload={
                    "incident_id": incident.incident_id,
                    "rca_report_id": rca_report.rca_report_id,
                    "snapshot_id": snapshot.snapshot_id,
                },
                recipient="infra-admin",
            )
            final_notification_ids, _ = self._send_rca_notifications(
                stage="final",
                incident=analyzed_incident or incident,
                rca_report=rca_report,
                subject=build_final_subject(rca_report, analyzed_incident or incident),
                html_body=build_final_email_html(rca_report),
            )
            return DueRcaJobResult(
                incident=analyzed_incident or incident,
                job=finished_job or build_running_job(job),
                snapshot=snapshot,
                rca_report=rca_report,
                final_notification_ids=final_notification_ids,
                message="Due RCA job generated the final RCA report.",
            )
        except Exception as exc:
            failed_job = self._orchestration_repository.finish_job(
                job_id=job.job_id,
                status="FAILED",
                error_message=f"RCA generation failed: {exc.__class__.__name__}",
            )
            return DueRcaJobResult(
                incident=incident,
                job=failed_job or build_running_job(job),
                message="Due RCA job failed.",
            )

    def send_rca_report_email(
        self,
        rca_report_id: str,
        request: RcaReportEmailRequest,
    ) -> RcaReportEmailResult:
        rca_report = self._repository.get_rca_report(rca_report_id)
        if rca_report is None:
            raise InfraRcaNotFoundError("RCA report was not found.")
        subject = request.subject or build_final_subject(rca_report, None)
        html_body = build_final_email_html(rca_report)
        notification_ids, delivery_statuses = self._send_rca_notifications(
            stage="final",
            incident=None,
            rca_report=rca_report,
            subject=subject,
            html_body=html_body,
            recipients=request.recipients,
        )
        status = (
            "SENT"
            if delivery_statuses and all(status == "SENT" for status in delivery_statuses)
            else "FAILED"
        )
        return RcaReportEmailResult(
            rca_report_id=rca_report_id,
            notification_ids=notification_ids,
            status=status,
        )

    def _send_rca_notifications(
        self,
        *,
        stage: str,
        incident: IncidentResult | None,
        rca_report: RcaReportResult | None,
        subject: str,
        html_body: str,
        recipients: list[str] | None = None,
    ) -> tuple[list[str], list[str]]:
        target_recipients = recipients or self._resolve_email_recipients()
        notification_ids = []
        delivery_statuses = []
        for recipient in target_recipients:
            related_table = "rca_reports" if rca_report is not None else "incidents"
            if rca_report is None and incident is None:
                logger.warning("RCA notification skipped because target entity is missing.")
                delivery_statuses.append("FAILED")
                continue
            related_public_id = (
                rca_report.rca_report_id if rca_report is not None else incident.incident_id
            )
            idempotency_key = f"rca:{related_public_id}:{stage}:{recipient}"
            try:
                notification = self._llmops_service.create_notification(
                    channel="email",
                    title=subject,
                    content=html_body,
                    payload={
                        "notification_stage": stage,
                        "incident_id": incident.incident_id if incident is not None else None,
                        "rca_report_id": (
                            rca_report.rca_report_id if rca_report is not None else None
                        ),
                        "subject": subject,
                        "html_body": html_body,
                    },
                    recipient=recipient,
                    related_table=related_table,
                    related_public_id=related_public_id,
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:
                logger.warning(
                    "RCA %s notification creation failed for %s: %s",
                    stage,
                    recipient,
                    exc,
                    exc_info=True,
                )
                delivery_statuses.append("FAILED")
                continue
            notification_ids.append(notification.notification_id)
            if notification.notification_status == "SENT":
                delivery_statuses.append("SENT")
                continue
            try:
                self._email_sender.send_html(
                    recipient=recipient,
                    subject=subject,
                    html_body=html_body,
                )
                self._safe_update_notification_status(
                    notification.notification_id,
                    status="SENT",
                    last_error=None,
                )
                delivery_statuses.append("SENT")
            except Exception as exc:
                logger.warning(
                    "RCA %s email delivery failed for %s: %s",
                    stage,
                    recipient,
                    exc,
                    exc_info=True,
                )
                self._safe_update_notification_status(
                    notification.notification_id,
                    status="FAILED",
                    last_error=f"{exc.__class__.__name__}: {exc}",
                )
                delivery_statuses.append("FAILED")
        return notification_ids, delivery_statuses

    def _safe_update_notification_status(
        self,
        notification_id: str,
        *,
        status: str,
        last_error: str | None,
    ) -> None:
        try:
            self._llmops_service.update_notification_status(
                notification_id,
                status=status,
                last_error=last_error,
            )
        except Exception:
            logger.exception("Failed to update RCA notification status.")

    def _resolve_email_recipients(self) -> list[str]:
        if self._email_recipients is not None:
            return self._email_recipients
        configured = (
            settings.rca_email_recipients.strip()
            or settings.ops_report_email_recipients.strip()
        )
        return parse_recipients(configured)

    def _create_rca_snapshot(
        self,
        *,
        incident: IncidentResult,
        alert: dict[str, Any],
        labels: dict[str, str],
        starts_at: datetime,
        job_id: str,
    ) -> ObservabilitySnapshotResult:
        time_start = starts_at - timedelta(minutes=settings.rca_default_before_minutes)
        time_end = starts_at + timedelta(minutes=settings.rca_default_after_minutes)
        snapshot = self._repository.create_observability_snapshot(
            incident_id=incident.incident_id,
            job_id=job_id,
            time_start=time_start,
            time_end=time_end,
            summary=f"RCA evidence window for {incident.alert_name or incident.dedup_key}.",
        )
        items = []
        infra_snapshot = self._capture_infra_snapshot(incident, labels, job_id=job_id)
        for source in infra_snapshot.get("sources", []):
            source_type = map_snapshot_source(source.get("source"))
            masked = mask_payload(source.get("data")) if source.get("data") is not None else None
            items.append(
                self._repository.add_snapshot_item(
                    snapshot_id=snapshot.snapshot_id,
                    source_type=source_type,
                    tool_name="create_rca_snapshot",
                    query_text=None,
                    query_params={
                        "time_start": time_start.isoformat(),
                        "time_end": time_end.isoformat(),
                        "alert": alert,
                    },
                    raw_data=source if source.get("status") == "SUCCESS" else None,
                    masked_data=masked,
                    summary=build_source_summary(source),
                    last_error=source.get("error"),
                )
            )
        prediction_items = self._capture_prediction_scaling_items(
            snapshot_id=snapshot.snapshot_id,
            namespace=incident.namespace,
            workload=incident.workload,
            time_start=time_start,
            time_end=time_end,
            job_id=job_id,
        )
        items.extend(prediction_items)
        status = "FAILED" if not items else "COMPLETED"
        completed = self._repository.complete_observability_snapshot(
            snapshot.snapshot_id,
            status=status,
            summary=f"Collected {len(items)} RCA snapshot evidence items.",
        )
        return (completed or snapshot).model_copy(update={"items": items})

    def _capture_infra_snapshot(
        self,
        incident: IncidentResult,
        labels: dict[str, str],
        job_id: str,
    ) -> dict[str, Any]:
        request_payload = {
            "incident_key": incident.dedup_key,
            "namespace": incident.namespace,
            "prometheus_query": build_prometheus_query(labels),
            "loki_query": build_loki_query(labels),
        }
        try:
            result = self._infraops_service.create_rca_snapshot(**request_payload)
            response_payload = result.model_dump(mode="json")
            self._record_tool_call(
                server_name="infraops-mcp",
                tool_name="create_rca_snapshot",
                request_payload=request_payload,
                response_payload=response_payload,
                call_status="SUCCESS",
                job_id=job_id,
            )
            return response_payload
        except Exception as exc:
            self._record_tool_call(
                server_name="infraops-mcp",
                tool_name="create_rca_snapshot",
                request_payload=request_payload,
                response_payload=None,
                call_status="FAILED",
                job_id=job_id,
                last_error=exc.__class__.__name__,
            )
            return {
                "partial": True,
                "sources": [
                    {
                        "source": "infraops",
                        "status": "FAILED",
                        "error": f"create_rca_snapshot failed: {exc.__class__.__name__}",
                    }
                ],
            }

    def _capture_prediction_scaling_items(
        self,
        *,
        snapshot_id: str,
        namespace: str | None,
        workload: str | None,
        time_start: datetime,
        time_end: datetime,
        job_id: str,
    ):
        items = []
        summary_request = {"namespace": namespace, "workload": workload}
        try:
            scaling_summary = self._prediction_scaling_service.get_scaling_summary(
                **summary_request
            )
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_scaling_summary",
                request_payload=summary_request,
                response_payload=scaling_summary.model_dump(mode="json"),
                call_status="SUCCESS",
                job_id=job_id,
            )
            items.append(
                self._repository.add_snapshot_item(
                    snapshot_id=snapshot_id,
                    source_type="KEDA",
                    tool_name="get_scaling_summary",
                    query_text=None,
                    query_params={
                        "namespace": namespace,
                        "workload": workload,
                        "time_start": time_start.isoformat(),
                        "time_end": time_end.isoformat(),
                    },
                    raw_data=None,
                    masked_data=scaling_summary.model_dump(mode="json"),
                    summary=scaling_summary.recommendation,
                )
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
                self._repository.add_snapshot_item(
                    snapshot_id=snapshot_id,
                    source_type="KEDA",
                    tool_name="get_scaling_summary",
                    query_text=None,
                    query_params={
                        "namespace": namespace,
                        "workload": workload,
                        "time_start": time_start.isoformat(),
                        "time_end": time_end.isoformat(),
                    },
                    raw_data=None,
                    masked_data=None,
                    summary="Scaling summary evidence unavailable.",
                    last_error=f"get_scaling_summary failed: {exc.__class__.__name__}",
                )
            )
        events_request = {"namespace": namespace, "workload": workload, "limit": 20}
        try:
            scaling_events = self._prediction_scaling_service.get_scaling_events(
                **events_request
            )
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_scaling_events",
                request_payload=events_request,
                response_payload=scaling_events.model_dump(mode="json"),
                call_status="SUCCESS",
                job_id=job_id,
            )
            items.append(
                self._repository.add_snapshot_item(
                    snapshot_id=snapshot_id,
                    source_type="KEDA",
                    tool_name="get_scaling_events",
                    query_text=None,
                    query_params={"namespace": namespace, "workload": workload, "limit": 20},
                    raw_data=None,
                    masked_data=scaling_events.model_dump(mode="json"),
                    summary=f"Collected {len(scaling_events.items)} scaling events.",
                )
            )
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
                self._repository.add_snapshot_item(
                    snapshot_id=snapshot_id,
                    source_type="KEDA",
                    tool_name="get_scaling_events",
                    query_text=None,
                    query_params={"namespace": namespace, "workload": workload, "limit": 20},
                    raw_data=None,
                    masked_data=None,
                    summary="Scaling event evidence unavailable.",
                    last_error=f"get_scaling_events failed: {exc.__class__.__name__}",
                )
            )
            return items
        related_run_ids = {
            event.related_prediction_run_id
            for event in scaling_events.items
            if event.related_prediction_run_id is not None
        }
        for prediction_run_id in sorted(related_run_ids):
            try:
                error_metrics = self._prediction_scaling_service.get_prediction_error_metrics(
                    prediction_run_id=prediction_run_id,
                )
            except Exception as exc:
                self._record_tool_call(
                    server_name="prediction-scaling-mcp",
                    tool_name="get_prediction_error_metrics",
                    request_payload={"prediction_run_id": prediction_run_id},
                    response_payload=None,
                    call_status="FAILED",
                    job_id=job_id,
                    last_error=exc.__class__.__name__,
                )
                items.append(
                    self._repository.add_snapshot_item(
                        snapshot_id=snapshot_id,
                        source_type="PREDICTION",
                        tool_name="get_prediction_error_metrics",
                        query_text=None,
                        query_params={"prediction_run_id": prediction_run_id},
                        raw_data=None,
                        masked_data=None,
                        summary="Prediction error evidence unavailable.",
                        last_error=(
                            "get_prediction_error_metrics failed: "
                            f"{exc.__class__.__name__}"
                        ),
                    )
                )
                continue
            self._record_tool_call(
                server_name="prediction-scaling-mcp",
                tool_name="get_prediction_error_metrics",
                request_payload={"prediction_run_id": prediction_run_id},
                response_payload=error_metrics.model_dump(mode="json"),
                call_status="SUCCESS",
                job_id=job_id,
            )
            items.append(
                self._repository.add_snapshot_item(
                    snapshot_id=snapshot_id,
                    source_type="PREDICTION",
                    tool_name="get_prediction_error_metrics",
                    query_text=None,
                    query_params={"prediction_run_id": prediction_run_id},
                    raw_data=None,
                    masked_data=error_metrics.model_dump(mode="json"),
                    summary=(
                        "Prediction error MAPE "
                        f"{error_metrics.mean_absolute_percentage_error}."
                    ),
                )
            )
        return items

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
        try:
            self._repository.record_mcp_tool_call(
                server_name=server_name,
                tool_name=tool_name,
                request_payload=request_payload,
                response_payload=response_payload,
                call_status=call_status,
                job_id=job_id,
                last_error=last_error,
            )
        except Exception:
            logger.exception(
                "Failed to record RCA MCP tool call audit for %s.%s.",
                server_name,
                tool_name,
            )

    def _create_rca_report(
        self,
        *,
        incident: IncidentResult,
        snapshot: ObservabilitySnapshotResult,
        llm_run_id: str | None,
        llm_output: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> RcaReportResult:
        answer = str(llm_output.get("answer") or "RCA evidence was collected.")
        summary = extract_rca_summary(answer)
        probable_root_cause = extract_labeled_section(
            answer,
            "Root Cause",
            fallback=summary,
        )
        partial = any(item.last_error for item in snapshot.items)
        return self._repository.create_rca_report(
            incident_id=incident.incident_id,
            llm_run_id=llm_run_id,
            snapshot_id=snapshot.snapshot_id,
            status="COMPLETED",
            summary=summary,
            probable_root_cause=probable_root_cause,
            impact=build_impact_summary(incident),
            timeline=build_timeline(incident, snapshot),
            evidence=evidence,
            recommended_actions=[
                {
                    "action": "Review collected RCA evidence before changing infrastructure.",
                    "priority": "high" if incident.severity == "CRITICAL" else "medium",
                }
            ],
            confidence=0.55 if partial else 0.75,
            prompt_version="rca.infra.v1",
        )


def extract_rca_summary(answer: str) -> str:
    impact = extract_labeled_section(answer, "Impact", fallback="")
    if impact:
        return impact
    return first_sentence(answer)


def parse_recipients(value: str) -> list[str]:
    return [recipient.strip() for recipient in value.split(",") if recipient.strip()]


def resolve_rca_window_start(starts_at: datetime | None) -> datetime:
    anchor = starts_at or datetime.now(UTC).replace(tzinfo=None)
    return anchor - timedelta(minutes=settings.rca_default_before_minutes)


def resolve_rca_run_after(starts_at: datetime | None) -> datetime:
    anchor = starts_at or datetime.now(UTC).replace(tzinfo=None)
    return anchor + timedelta(minutes=settings.rca_default_after_minutes)


def parse_stored_datetime(value: Any, *, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return parse_alert_timestamp(value) or fallback
    return fallback


def build_running_job(job: ScheduledRcaJobRecord) -> JobResult:
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    return JobResult(
        job_id=job.job_id,
        job_type="rca",
        status="RUNNING",
        entity_type="incidents",
        entity_id=job.incident_id,
        created_at=now,
        updated_at=now,
    )


def build_preliminary_subject(incident: IncidentResult) -> str:
    alert_name = incident.alert_name or "Alertmanager alert"
    return f"[AIOps] RCA analysis started: {alert_name}"


def build_final_subject(
    rca_report: RcaReportResult,
    incident: IncidentResult | None,
) -> str:
    alert_name = incident.alert_name if incident is not None else None
    target = alert_name or rca_report.summary or rca_report.rca_report_id
    return f"[AIOps] Final RCA report: {target}"


def build_preliminary_email_html(
    *,
    incident: IncidentResult,
    starts_at: datetime | None,
) -> str:
    started_at = starts_at.isoformat() if starts_at is not None else incident.starts_at
    rows = [
        ("Incident", incident.incident_id),
        ("Alert", incident.alert_name or ""),
        ("Severity", incident.severity),
        ("Namespace", incident.namespace or ""),
        ("Workload", incident.workload or ""),
        ("Service", incident.service_name or ""),
        ("Started At", started_at or ""),
    ]
    return (
        "<html><body>"
        "<h2>AIOps preliminary RCA notification</h2>"
        "<p>Alertmanager firing alert was received. RCA evidence collection and "
        "LLM analysis have started.</p>"
        f"{render_table(rows)}"
        "</body></html>"
    )


def build_final_email_html(rca_report: RcaReportResult) -> str:
    rows = [
        ("RCA Report", rca_report.rca_report_id),
        ("Incident", rca_report.incident_id),
        ("Status", rca_report.status),
        ("Summary", rca_report.summary or ""),
        ("Probable Root Cause", rca_report.probable_root_cause or ""),
        ("Impact", rca_report.impact or ""),
        ("Confidence", str(rca_report.confidence or "")),
    ]
    actions = "".join(
        f"<li>{html.escape(str(action.get('action') or action))}</li>"
        for action in rca_report.recommended_actions
    )
    evidence = "".join(
        f"<li>{html.escape(str(item.get('source') or item.get('summary') or item))}</li>"
        for item in rca_report.evidence[:10]
    )
    return (
        "<html><body>"
        "<h2>AIOps final RCA report</h2>"
        f"{render_table(rows)}"
        "<h3>Recommended actions</h3>"
        f"<ul>{actions or '<li>No recommended actions were generated.</li>'}</ul>"
        "<h3>Evidence</h3>"
        f"<ul>{evidence or '<li>No evidence items were generated.</li>'}</ul>"
        "</body></html>"
    )


def render_table(rows: list[tuple[str, str]]) -> str:
    rendered_rows = "".join(
        "<tr>"
        f"<th>{html.escape(label)}</th>"
        f"<td>{html.escape(value)}</td>"
        "</tr>"
        for label, value in rows
    )
    return (
        "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">"
        f"<tbody>{rendered_rows}</tbody>"
        "</table>"
    )


def extract_labeled_section(answer: str, label: str, *, fallback: str) -> str:
    marker = f"{label}:"
    start = answer.find(marker)
    if start < 0:
        return fallback
    value_start = start + len(marker)
    following_labels = [
        "Root Cause:",
        "Impact:",
        "Confidence:",
        "Recommended Actions:",
        "Recommended Action:",
    ]
    value_end = len(answer)
    for following_label in following_labels:
        if following_label == marker:
            continue
        index = answer.find(following_label, value_start)
        if index >= 0:
            value_end = min(value_end, index)
    extracted = answer[value_start:value_end].strip()
    return extracted or fallback


def first_sentence(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return "RCA evidence was collected."
    for delimiter in [". ", "\n"]:
        index = normalized.find(delimiter)
        if index > 0:
            return normalized[: index + 1].strip()
    return normalized[:240]


def select_primary_alert(request: AlertmanagerWebhookRequest) -> AlertmanagerAlert:
    firing = [alert for alert in request.alerts if normalize_alert_status(alert.status) == "FIRING"]
    return firing[0] if firing else request.alerts[0]


def normalize_alert_status(value: str) -> str:
    normalized = value.strip().upper()
    if normalized in {"FIRING", "RESOLVED"}:
        return normalized
    raise InfraRcaValidationError("alert status is invalid.")


def parse_alert_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.startswith("0001-01-01"):
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InfraRcaValidationError(
            f"alert timestamp is invalid: {value}"
        ) from exc
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def resolve_fingerprint(alert: AlertmanagerAlert, labels: dict[str, str]) -> str:
    if alert.fingerprint and alert.fingerprint.strip():
        return alert.fingerprint.strip()
    seed = "|".join(
        [
            labels.get("alertname", ""),
            labels.get("namespace", ""),
            labels.get("service", ""),
            labels.get("workload", ""),
        ]
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def resolve_dedup_key(fingerprint: str, labels: dict[str, str]) -> str:
    return ":".join(
        part
        for part in [
            labels.get("alertname"),
            labels.get("namespace"),
            labels.get("service") or labels.get("app") or labels.get("workload"),
            fingerprint,
        ]
        if part
    )[:240]


def resolve_severity(labels: dict[str, str]) -> str:
    severity = (labels.get("severity") or "").strip().lower()
    if severity in {"critical", "crit", "page"}:
        return "CRITICAL"
    if severity in {"warning", "warn"}:
        return "WARNING"
    return "INFO"


def resolve_alert_summary(labels: dict[str, str], annotations: dict[str, str]) -> str:
    return (
        annotations.get("summary")
        or annotations.get("description")
        or labels.get("alertname")
        or "Alertmanager alert"
    )


def build_prometheus_query(labels: dict[str, str]) -> str:
    service = escape_query_label_value(
        labels.get("service") or labels.get("app") or labels.get("workload")
    )
    if service:
        return f'up{{service="{service}"}}'
    return "up"


def build_loki_query(labels: dict[str, str]) -> str:
    service = escape_query_label_value(
        labels.get("service") or labels.get("app") or labels.get("workload")
    )
    if service:
        return f'{{service="{service}"}}'
    return '{job=~".+"}'


def escape_query_label_value(value: str | None) -> str | None:
    if value is None:
        return None
    if not value.strip():
        return None
    return (
        value.replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        .replace('"', '\\"')
    )


def map_snapshot_source(source: str | None) -> str:
    return {
        "prometheus": "PROMETHEUS",
        "loki": "LOKI",
        "elasticsearch": "ELASTICSEARCH",
        "kubernetes": "KUBERNETES",
        "kafka": "DATABASE",
        "batch": "DATABASE",
    }.get((source or "").lower(), "DATABASE")


def build_source_summary(source: dict[str, Any]) -> str:
    status = source.get("status", "UNKNOWN")
    name = source.get("source", "source")
    if status == "SUCCESS":
        return f"{name} evidence collected."
    return f"{name} evidence unavailable."


def build_evidence(snapshot: ObservabilitySnapshotResult) -> list[dict[str, Any]]:
    return [
        {
            "source": item.source_type.lower(),
            "reference_id": item.snapshot_item_id,
            "finding": item.summary or item.last_error or "RCA evidence item.",
        }
        for item in snapshot.items
    ]


def build_timeline(
    incident: IncidentResult,
    snapshot: ObservabilitySnapshotResult,
) -> list[dict[str, Any]]:
    return [
        {
            "time": incident.starts_at or snapshot.time_start,
            "event": f"Alert fired: {incident.alert_name or incident.dedup_key}",
            "source": "alertmanager",
        },
        {
            "time": snapshot.created_at,
            "event": "RCA evidence snapshot collected.",
            "source": "mcp",
        },
    ]


def build_impact_summary(incident: IncidentResult) -> str:
    target = incident.service_name or incident.workload or incident.namespace or "unknown target"
    return f"{incident.severity} alert impact requires review for {target}."
