from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)


def test_read_tool_policy_is_allowed_without_confirmation() -> None:
    policy = resolve_tool_policy(McpToolPermission.READ)

    assert policy.confirmation_policy == McpConfirmationPolicy.NONE
    assert policy.execution_policy == McpExecutionPolicy.ALLOWED
    assert policy.call_status == McpToolCallStatus.SUCCESS


def test_destructive_tool_policy_is_blocked() -> None:
    policy = resolve_tool_policy(McpToolPermission.DESTRUCTIVE)

    assert policy.confirmation_policy == McpConfirmationPolicy.BLOCKED
    assert policy.execution_policy == McpExecutionPolicy.BLOCKED
    assert policy.call_status == McpToolCallStatus.BLOCKED

