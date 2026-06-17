from typing import Literal

from pydantic import BaseModel, Field

from aiops_platform.agent.schemas import AgentToolExecutionResult, AgentToolPlan

AlertmanagerSrePlanStatus = Literal["PLANNED", "COLLECTED", "ANALYZED", "SKIPPED"]
AlertmanagerSreNotificationStatus = Literal["SENT", "FAILED", "SKIPPED"]
AlertmanagerSreTriggerType = Literal["ALERTMANAGER", "MANUAL_INSPECTION"]
AlertmanagerSreInspectionType = Literal[
    "current_state",
    "routing",
    "kubernetes_pod",
    "postgresql",
    "sqs_publish",
    "sqs_consume",
    "application",
]


class AlertmanagerIncidentWindow(BaseModel):
    anchor_time: str
    start: str
    end: str
    lookback_seconds: int


class AlertmanagerSreAlertContext(BaseModel):
    alert_name: str
    status: str
    severity: str | None = None
    cluster: str | None = None
    namespace: str | None = None
    service_name: str | None = None
    workload: str | None = None
    pod: str | None = None
    fingerprint: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None
    summary: str | None = None
    description: str | None = None


class AlertmanagerSreNotificationResult(BaseModel):
    channel: Literal["EMAIL", "SLACK"]
    recipient: str | None = None
    status: AlertmanagerSreNotificationStatus
    notification_id: str | None = None
    error_message: str | None = None


class AlertmanagerSreInspectionRequest(BaseModel):
    inspection_type: AlertmanagerSreInspectionType = "current_state"
    cluster: str = Field(default="onprem", min_length=1, max_length=120)
    namespace: str = Field(default="kkpp", min_length=1, max_length=120)
    service: str | None = Field(default=None, max_length=120)
    workload: str | None = Field(default=None, max_length=120)
    pod: str | None = Field(default=None, max_length=180)
    severity: Literal["info", "warning", "critical"] = "info"
    alert_name: str | None = Field(default=None, max_length=120)
    summary: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=1000)
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class AlertmanagerSrePlanResult(BaseModel):
    trigger_type: AlertmanagerSreTriggerType = "ALERTMANAGER"
    dry_run: bool = True
    status: AlertmanagerSrePlanStatus
    receiver: str | None = None
    actor: str = "alertmanager"
    incident_key: str | None = None
    intent: str | None = None
    capability: str | None = None
    analysis_message: str | None = None
    alert: AlertmanagerSreAlertContext | None = None
    incident_window: AlertmanagerIncidentWindow | None = None
    planned_tools: list[AgentToolPlan] = Field(default_factory=list)
    executed_tools: list[AgentToolExecutionResult] = Field(default_factory=list)
    context_bundle: dict | None = None
    rca_snapshot: dict | None = None
    rca_analysis: dict | None = None
    notification_results: list[AlertmanagerSreNotificationResult] = Field(
        default_factory=list
    )
    skipped_reason: str | None = None
