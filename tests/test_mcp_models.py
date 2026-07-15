from sqlalchemy import CheckConstraint

from aiops_platform.models.mcp import McpServer, McpTool, McpToolCall


def _check_constraint_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_mcp_server_status_has_db_check_constraint() -> None:
    assert "ck_ai_mcp_servers_server_status" in _check_constraint_names(McpServer)


def test_mcp_tool_enums_have_db_check_constraints() -> None:
    constraint_names = _check_constraint_names(McpTool)

    assert "ck_ai_mcp_tools_tool_permission" in constraint_names
    assert "ck_ai_mcp_tools_tool_status" in constraint_names


def test_mcp_tool_call_enums_have_db_check_constraints() -> None:
    constraint_names = _check_constraint_names(McpToolCall)

    assert "ck_ai_mcp_tool_calls_tool_permission" in constraint_names
    assert "ck_ai_mcp_tool_calls_confirmation_policy" in constraint_names
    assert "ck_ai_mcp_tool_calls_call_status" in constraint_names


def test_updated_at_columns_refresh_on_orm_update() -> None:
    assert McpServer.__table__.c.updated_at.onupdate is not None
    assert McpTool.__table__.c.updated_at.onupdate is not None
