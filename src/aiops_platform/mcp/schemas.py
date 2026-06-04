from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class McpServerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class McpToolPermission(StrEnum):
    READ = "READ"
    WRITE = "WRITE"
    USER_CONFIRMED_WRITE = "USER_CONFIRMED_WRITE"
    OPS_WRITE = "OPS_WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


class McpToolStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DEPRECATED = "DEPRECATED"


class McpConfirmationPolicy(StrEnum):
    NONE = "NONE"
    USER_CONFIRMATION = "USER_CONFIRMATION"
    ADMIN_APPROVAL = "ADMIN_APPROVAL"
    BLOCKED = "BLOCKED"


class McpToolCallStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    BLOCKED = "BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class McpToolMetadata(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    server_name: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=120)
    display_name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    tool_permission: McpToolPermission
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    tool_status: McpToolStatus = McpToolStatus.ACTIVE


class McpServerMetadata(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    server_name: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    base_url: str | None = None
    server_status: McpServerStatus = McpServerStatus.ACTIVE
    server_metadata: dict = Field(default_factory=dict)
    tools: list[McpToolMetadata] = Field(default_factory=list)


class McpToolCallMetadata(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    server_name: str = Field(min_length=1, max_length=100)
    tool_name: str = Field(min_length=1, max_length=120)
    tool_permission: McpToolPermission
    confirmation_policy: McpConfirmationPolicy = McpConfirmationPolicy.NONE
    request_payload: dict | None = None
    masked_request_payload: dict | None = None
    response_ref: str | None = None
    masked_response_payload: dict | None = None
    call_status: McpToolCallStatus
    latency_ms: int | None = Field(default=None, ge=0)
    last_error: str | None = None

