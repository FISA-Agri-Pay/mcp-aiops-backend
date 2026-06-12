from typing import Any, Literal

from pydantic import BaseModel, Field

PromptScope = Literal[
    "farmer_bnpl",
    "admin_copilot",
    "sre_copilot",
    "rca",
    "ops_report",
    "common",
]
LlmRunStatus = Literal["SUCCESS", "FAILED", "VALIDATION_FAILED"]
ApprovalStatus = Literal["PENDING", "APPROVED", "REJECTED", "EXPIRED", "CANCELED"]
NotificationStatus = Literal["PENDING", "SENT", "FAILED", "RETRYING", "CANCELED"]
SnapshotStatus = Literal["COMPLETED", "FAILED"]


class PromptVersionResult(BaseModel):
    prompt_version_id: str
    prompt_key: str
    version: str
    scope: PromptScope
    template: str
    is_active: bool
    created_at: str


class PromptVersionListResult(BaseModel):
    scope: PromptScope | None = None
    limit: int
    items: list[PromptVersionResult]


class LlmRunResult(BaseModel):
    llm_run_id: str
    provider: str
    model: str
    prompt_version_id: str | None = None
    prompt_key: str
    run_status: LlmRunStatus
    job_id: str | None = None
    session_id: str | None = None
    masked_input: dict[str, Any]
    masked_output: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[str] = Field(default_factory=list)
    latency_ms: int = 0
    created_at: str
    last_error: str | None = None


class LlmRunListResult(BaseModel):
    provider: str | None = None
    status: LlmRunStatus | None = None
    limit: int
    items: list[LlmRunResult]


class ApprovalRequestResult(BaseModel):
    approval_request_id: str
    approval_type: str
    target_type: str
    target_id: str | None = None
    requester_id: str | None = None
    approval_status: ApprovalStatus
    reason: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class ApprovalRequestListResult(BaseModel):
    status: ApprovalStatus | None = None
    limit: int
    items: list[ApprovalRequestResult]


class NotificationOutboxResult(BaseModel):
    notification_id: str
    channel: str
    recipient: str | None = None
    notification_status: NotificationStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    related_table: str | None = None
    related_public_id: str | None = None
    idempotency_key: str | None = None
    attempts: int = 0
    created_at: str
    last_error: str | None = None


class NotificationOutboxListResult(BaseModel):
    status: NotificationStatus | None = None
    limit: int
    items: list[NotificationOutboxResult]


class AgentSnapshotResult(BaseModel):
    snapshot_id: str
    snapshot_type: str
    job_id: str | None = None
    session_id: str | None = None
    llm_run_id: str | None = None
    snapshot_status: SnapshotStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class AgentSnapshotListResult(BaseModel):
    snapshot_type: str | None = None
    limit: int
    items: list[AgentSnapshotResult]


class LlmOutputValidationResult(BaseModel):
    is_valid: bool
    errors: list[str] = Field(default_factory=list)
