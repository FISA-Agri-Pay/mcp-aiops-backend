from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)

ChatType = Literal["farmer_bnpl", "admin_copilot"]
ChatStatus = Literal["OPEN", "CLOSED"]
MessageRole = Literal["USER", "ASSISTANT", "SYSTEM"]
JobStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED"]


class ChatSessionCreateRequest(BaseModel):
    user_id: str = Field(default="anonymous", min_length=1, max_length=120)
    title: str | None = Field(default=None, max_length=120)


class ChatAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=120)
    user_id: str = Field(default="anonymous", min_length=1, max_length=120)

    @field_validator("session_id")
    @classmethod
    def normalize_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ChatSessionResult(BaseModel):
    session_id: str
    chat_type: ChatType
    user_id: str
    title: str | None = None
    status: ChatStatus
    created_at: str
    updated_at: str


class ChatMessageResult(BaseModel):
    message_id: str
    session_id: str
    role: MessageRole
    content: str
    created_at: str
    mcp_tool_call_ids: list[str] = Field(default_factory=list)


class PlannedToolResult(BaseModel):
    server_name: str
    tool_name: str
    tool_permission: McpToolPermission
    confirmation_policy: McpConfirmationPolicy
    execution_policy: McpExecutionPolicy


class ChatAskResult(BaseModel):
    session: ChatSessionResult
    user_message: ChatMessageResult
    assistant_message: ChatMessageResult
    job: "JobResult"
    planned_tools: list[PlannedToolResult]


class JobResult(BaseModel):
    job_id: str
    job_type: str
    status: JobStatus
    entity_type: str
    entity_id: str
    created_at: str
    updated_at: str
    error_message: str | None = None


class JobListResult(BaseModel):
    status: JobStatus | None = None
    job_type: str | None = None
    limit: int
    items: list[JobResult]


class JobActionPreviewResult(BaseModel):
    job_id: str
    action: Literal["retry", "cancel"]
    current_status: JobStatus
    will_execute: bool = False
    message: str


class McpToolCallResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    tool_call_id: str
    server_name: str
    tool_name: str
    tool_permission: McpToolPermission
    confirmation_policy: McpConfirmationPolicy
    call_status: McpToolCallStatus
    execution_policy: McpExecutionPolicy
    masked_request_payload: dict[str, Any] | None = None
    masked_response_payload: dict[str, Any] | list[Any] | None = None
    latency_ms: int
    job_id: str | None = None
    session_id: str | None = None
    created_at: str
    last_error: str | None = None


class McpToolCallListResult(BaseModel):
    server_name: str | None = None
    tool_name: str | None = None
    permission: McpToolPermission | None = None
    status: McpToolCallStatus | None = None
    limit: int
    items: list[McpToolCallResult]


class ChatMessagesResult(BaseModel):
    session_id: str
    items: list[ChatMessageResult]
