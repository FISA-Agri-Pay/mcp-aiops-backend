from typing import Literal

from pydantic import BaseModel, Field

from aiops_platform.agent.schemas import AgentToolPlan


AlertmanagerSrePlanStatus = Literal["PLANNED", "SKIPPED"]


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
    summary: str | None = None
    description: str | None = None


class AlertmanagerSrePlanResult(BaseModel):
    trigger_type: Literal["ALERTMANAGER"] = "ALERTMANAGER"
    dry_run: bool = True
    status: AlertmanagerSrePlanStatus
    receiver: str | None = None
    actor: str = "alertmanager"
    incident_key: str | None = None
    intent: str | None = None
    capability: str | None = None
    analysis_message: str | None = None
    alert: AlertmanagerSreAlertContext | None = None
    planned_tools: list[AgentToolPlan] = Field(default_factory=list)
    skipped_reason: str | None = None
