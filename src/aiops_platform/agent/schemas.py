from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)

AgentProviderName = Literal["rule_based"]
AgentChatType = Literal["farmer_bnpl", "admin_copilot"]


class AgentToolPlan(BaseModel):
    server_name: str
    tool_name: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    reason: str


class AgentPlanResult(BaseModel):
    provider_name: AgentProviderName
    chat_type: AgentChatType
    tool_plans: list[AgentToolPlan]


class AgentToolExecutionResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    server_name: str
    tool_name: str
    tool_permission: McpToolPermission
    confirmation_policy: McpConfirmationPolicy
    execution_policy: McpExecutionPolicy
    call_status: McpToolCallStatus
    will_execute: bool
    requires_approval: bool
    is_blocked: bool
    request_payload: dict[str, Any] = Field(default_factory=dict)
    masked_request_payload: dict[str, Any] | None = None
    response_payload: dict[str, Any] | list[Any] | None = None
    masked_response_payload: dict[str, Any] | list[Any] | None = None
    error_message: str | None = None
    tool_call_id: str | None = None


class AgentRunResult(BaseModel):
    provider_name: AgentProviderName
    answer: str
    tool_results: list[AgentToolExecutionResult]
