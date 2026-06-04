from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
    McpToolPolicy,
)


def resolve_tool_policy(permission: McpToolPermission) -> McpToolPolicy:
    policies = {
        McpToolPermission.READ: McpToolPolicy(
            tool_permission=permission,
            confirmation_policy=McpConfirmationPolicy.NONE,
            execution_policy=McpExecutionPolicy.ALLOWED,
            call_status=McpToolCallStatus.SUCCESS,
        ),
        McpToolPermission.WRITE: McpToolPolicy(
            tool_permission=permission,
            confirmation_policy=McpConfirmationPolicy.USER_CONFIRMATION,
            execution_policy=McpExecutionPolicy.BLOCKED_UNTIL_CONFIRMED,
            call_status=McpToolCallStatus.APPROVAL_REQUIRED,
        ),
        McpToolPermission.USER_CONFIRMED_WRITE: McpToolPolicy(
            tool_permission=permission,
            confirmation_policy=McpConfirmationPolicy.USER_CONFIRMATION,
            execution_policy=McpExecutionPolicy.BLOCKED_UNTIL_CONFIRMED,
            call_status=McpToolCallStatus.APPROVAL_REQUIRED,
        ),
        McpToolPermission.OPS_WRITE: McpToolPolicy(
            tool_permission=permission,
            confirmation_policy=McpConfirmationPolicy.ADMIN_APPROVAL,
            execution_policy=McpExecutionPolicy.BLOCKED_UNTIL_APPROVED,
            call_status=McpToolCallStatus.APPROVAL_REQUIRED,
        ),
        McpToolPermission.DESTRUCTIVE: McpToolPolicy(
            tool_permission=permission,
            confirmation_policy=McpConfirmationPolicy.BLOCKED,
            execution_policy=McpExecutionPolicy.BLOCKED,
            call_status=McpToolCallStatus.BLOCKED,
        ),
    }
    return policies[permission]

