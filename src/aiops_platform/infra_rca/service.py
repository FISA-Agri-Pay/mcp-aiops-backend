from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from aiops_platform.core.config import settings
from aiops_platform.infra_rca.repository import InfraRcaRepository, SqlInfraRcaRepository
from aiops_platform.infra_rca.schemas import (
    AlertmanagerAlert,
    AlertmanagerWebhookRequest,
    AlertWebhookResult,
    IncidentResult,
    ObservabilitySnapshotResult,
    RcaReportResult,
)
from aiops_platform.infraops.service import InfraOpsService
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.orchestration.repository import (
    OrchestrationRepository,
    SqlOrchestrationRepository,
)
from aiops_platform.prediction_scaling.service import (
    PredictionScalingService,
    PredictionScalingValidationError,
)


class InfraRcaValidationError(ValueError):
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

        job = self._orchestration_repository.create_job(
            job_type="rca",
            entity_type="incidents",
            entity_id=incident.incident_id,
            status="RUNNING",
        )
        try:
            snapshot = self._create_rca_snapshot(
                incident=incident,
                alert=incident_alert.model_dump(mode="json"),
                labels=labels,
                starts_at=starts_at or datetime.now(UTC).replace(tzinfo=None),
                job_id=job.job_id,
            )
            evidence = build_evidence(snapshot)
            llm_run = self._llmops_service.run_rca_completion(
                incident=incident.model_dump(mode="json"),
                alert=incident_alert.model_dump(mode="json"),
                snapshot=snapshot.model_dump(mode="json"),
                evidence=evidence,
                job_id=job.job_id,
            )
            rca_report = self._create_rca_report(
                incident=incident,
                snapshot=snapshot,
                llm_run_id=llm_run.llm_run_id,
                llm_output=llm_run.masked_output,
                evidence=evidence,
            )
            self._repository.update_incident_status(incident.incident_id, status="ANALYZED")
            finished_job = self._orchestration_repository.finish_job(
                job_id=job.job_id,
                status="SUCCEEDED",
            )
            notification = self._llmops_service.create_notification(
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
            return AlertWebhookResult(
                incident=incident,
                alert=incident_alert,
                job=finished_job or job,
                snapshot=snapshot,
                rca_report=rca_report,
                notification_id=notification.notification_id,
                duplicate=duplicate,
                message="Alertmanager webhook was recorded and RCA was generated.",
            )
        except Exception as exc:
            failed_job = self._orchestration_repository.finish_job(
                job_id=job.job_id,
                status="FAILED",
                error_message=f"RCA generation failed: {exc.__class__.__name__}",
            )
            return AlertWebhookResult(
                incident=incident,
                alert=incident_alert,
                job=failed_job or job,
                duplicate=duplicate,
                message="Alertmanager webhook was recorded, but RCA generation failed.",
            )

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
            except (PredictionScalingValidationError, RuntimeError) as exc:
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
        partial = any(item.last_error for item in snapshot.items)
        return self._repository.create_rca_report(
            incident_id=incident.incident_id,
            llm_run_id=llm_run_id,
            snapshot_id=snapshot.snapshot_id,
            status="COMPLETED",
            summary=answer,
            probable_root_cause=answer,
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
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def resolve_fingerprint(alert: AlertmanagerAlert, labels: dict[str, str]) -> str:
    if alert.fingerprint:
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
    service = labels.get("service") or labels.get("app") or labels.get("workload")
    if service:
        return f'up{{service="{service}"}}'
    return "up"


def build_loki_query(labels: dict[str, str]) -> str:
    service = labels.get("service") or labels.get("app") or labels.get("workload")
    if service:
        return f'{{service="{service}"}}'
    return '{job=~".+"}'


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
