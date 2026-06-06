from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aiops_platform.orchestration.schemas import JobResult

AlertStatus = Literal["FIRING", "RESOLVED"]
IncidentStatus = Literal["FIRING", "INVESTIGATING", "ANALYZED", "RESOLVED", "CLOSED"]
IncidentSeverity = Literal["INFO", "WARNING", "CRITICAL"]


class AlertmanagerAlert(BaseModel):
    status: str = Field(default="firing")
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    generatorURL: str | None = None
    fingerprint: str | None = None


class AlertmanagerWebhookRequest(BaseModel):
    receiver: str | None = None
    status: str = Field(default="firing")
    alerts: list[AlertmanagerAlert] = Field(min_length=1)
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    version: str | None = None
    groupKey: str | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"firing", "resolved"}:
            return normalized
        raise ValueError("status must be firing or resolved.")


class IncidentResult(BaseModel):
    incident_id: str
    dedup_key: str
    source_type: str
    status: IncidentStatus
    severity: IncidentSeverity
    alert_name: str | None = None
    namespace: str | None = None
    workload: str | None = None
    service_name: str | None = None
    summary: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    created_at: str
    updated_at: str


class IncidentAlertResult(BaseModel):
    incident_alert_id: str
    incident_id: str
    fingerprint: str
    status: AlertStatus
    starts_at: str | None = None
    ends_at: str | None = None
    received_at: str


class SnapshotItemResult(BaseModel):
    snapshot_item_id: str
    source_type: str
    tool_name: str | None = None
    summary: str | None = None
    last_error: str | None = None


class ObservabilitySnapshotResult(BaseModel):
    snapshot_id: str
    incident_id: str
    snapshot_type: str
    time_start: str
    time_end: str
    status: Literal["COLLECTING", "COMPLETED", "FAILED"]
    summary: str | None = None
    items: list[SnapshotItemResult] = Field(default_factory=list)
    created_at: str


class RcaReportResult(BaseModel):
    rca_report_id: str
    incident_id: str
    llm_run_id: str | None = None
    snapshot_id: str | None = None
    status: Literal["DRAFT", "COMPLETED", "FAILED", "SUPERSEDED"]
    summary: str | None = None
    probable_root_cause: str | None = None
    impact: str | None = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = None
    prompt_version: str | None = None
    created_at: str


class AlertWebhookResult(BaseModel):
    incident: IncidentResult
    alert: IncidentAlertResult
    job: JobResult | None = None
    snapshot: ObservabilitySnapshotResult | None = None
    rca_report: RcaReportResult | None = None
    notification_id: str | None = None
    duplicate: bool = False
    message: str
