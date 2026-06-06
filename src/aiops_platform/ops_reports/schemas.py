from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from aiops_platform.llmops.schemas import LlmRunResult
from aiops_platform.orchestration.schemas import JobResult

OpsReportType = Literal["DAILY", "WEEKLY"]
OpsReportStatus = Literal["DRAFT", "COMPLETED", "SENT", "FAILED"]
ReportMetricSource = Literal[
    "ONPREM_PROMETHEUS",
    "AWS_PROMETHEUS",
    "ONPREM_LOKI",
    "AWS_LOKI",
    "ONPREM_ELASTICSEARCH",
    "AWS_ELASTICSEARCH",
    "DATABASE",
    "PREDICTION",
    "PREDICTION_ERROR",
    "KEDA",
    "HPA",
    "SCALING",
]


class OpsReportCreateRequest(BaseModel):
    report_type: OpsReportType
    report_date: date
    timezone: str = Field(default="Asia/Seoul", min_length=1, max_length=50)
    namespace: str | None = Field(default=None, max_length=100)
    service_name: str | None = Field(default=None, max_length=150)
    include_rca: bool = True
    include_prediction_scaling: bool = True

    @field_validator("timezone", "namespace", "service_name")
    @classmethod
    def normalize_text(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            if info.field_name == "timezone":
                raise ValueError("timezone is required.")
            return None
        normalized = value.strip()
        if info.field_name == "timezone" and not normalized:
            raise ValueError("timezone is required.")
        return normalized or None


class OpsReportEmailRequest(BaseModel):
    recipients: list[str] = Field(min_length=1, max_length=20)
    subject: str | None = Field(default=None, max_length=255)
    format: Literal["HTML"] = "HTML"

    @field_validator("recipients")
    @classmethod
    def normalize_recipients(cls, value: list[str]) -> list[str]:
        recipients = [recipient.strip() for recipient in value if recipient.strip()]
        if not recipients:
            raise ValueError("at least one recipient is required.")
        return recipients


class OpsReportResult(BaseModel):
    report_id: str
    report_type: OpsReportType
    period_start: str
    period_end: str
    timezone: str
    title: str
    summary: str | None = None
    sections: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    llm_run_id: str | None = None
    report_status: OpsReportStatus
    created_at: str


class ReportIncidentResult(BaseModel):
    report_incident_id: str
    report_id: str
    incident_id: str
    summary: str | None = None
    created_at: str


class OpsReportRcaRefResult(BaseModel):
    report_rca_ref_id: str
    report_id: str
    rca_report_id: str
    incident_id: str
    included_reason: str | None = None
    created_at: str


class ReportMetricSummaryResult(BaseModel):
    metric_summary_id: str
    report_id: str | None = None
    source_type: ReportMetricSource
    namespace: str | None = None
    service_name: str | None = None
    metric_name: str
    period_start: str
    period_end: str
    summary_values: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class IncludedIncident(BaseModel):
    incident_id: str
    status: str
    severity: str
    alert_name: str | None = None
    namespace: str | None = None
    workload: str | None = None
    service_name: str | None = None
    summary: str | None = None
    starts_at: str | None = None
    created_at: str


class IncludedRcaReport(BaseModel):
    rca_report_id: str
    incident_id: str
    status: str
    summary: str | None = None
    probable_root_cause: str | None = None
    confidence: float | None = None
    created_at: str


class OpsReportDetailResult(BaseModel):
    report: OpsReportResult
    included_incidents: list[IncludedIncident] = Field(default_factory=list)
    included_rca_reports: list[IncludedRcaReport] = Field(default_factory=list)
    metric_summaries: list[ReportMetricSummaryResult] = Field(default_factory=list)
    rca_refs: list[OpsReportRcaRefResult] = Field(default_factory=list)


class OpsReportGenerationResult(OpsReportDetailResult):
    job: JobResult
    llm_run: LlmRunResult | None = None


class OpsReportListResult(BaseModel):
    report_type: OpsReportType | None = None
    status: OpsReportStatus | None = None
    limit: int
    items: list[OpsReportResult]


class OpsReportEmailResult(BaseModel):
    report_id: str
    channel: Literal["EMAIL"] = "EMAIL"
    notification_ids: list[str]
    status: Literal["PENDING", "SENT", "FAILED"] = "PENDING"
