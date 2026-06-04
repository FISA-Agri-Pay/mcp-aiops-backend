from __future__ import annotations

from collections.abc import Mapping
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpToolAuditCreate,
    McpToolCallStatus,
    McpToolExecutionContext,
    McpToolPermission,
)
from aiops_platform.models.mcp import McpServer, McpTool, McpToolCall


class McpRegistryLookupError(ValueError):
    """Raised when the database registry does not contain a requested MCP tool."""


class McpToolAuditRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_tool_public_ids(self, server_name: str, tool_name: str) -> tuple[UUID, UUID]:
        statement = (
            select(McpServer.public_id, McpTool.public_id)
            .join(McpTool, McpTool.mcp_server_public_id == McpServer.public_id)
            .where(McpServer.server_name == server_name, McpTool.tool_name == tool_name)
        )
        row = self._session.execute(statement).one_or_none()
        if row is None:
            raise McpRegistryLookupError(
                f"MCP tool is not registered in DB: {server_name}/{tool_name}"
            )
        return row[0], row[1]

    def create_tool_call(self, record: McpToolAuditCreate) -> McpToolCall:
        tool_call = McpToolCall(**record.model_dump(mode="python"))
        self._session.add(tool_call)
        self._session.commit()
        self._session.refresh(tool_call)
        return tool_call


class McpToolAuditService:
    def __init__(self, repository: McpToolAuditRepository) -> None:
        self._repository = repository

    def record_tool_call(
        self,
        context: McpToolExecutionContext,
        permission: McpToolPermission,
        response_payload: Mapping[str, Any] | list[Any] | None,
        call_status: McpToolCallStatus,
        latency_ms: int,
        last_error: str | None = None,
    ) -> McpToolCall:
        server_public_id, tool_public_id = self._repository.get_tool_public_ids(
            context.server_name,
            context.tool_name,
        )
        policy = resolve_tool_policy(permission)
        normalized_response_payload = normalize_response_payload(response_payload)
        record = McpToolAuditCreate(
            mcp_server_public_id=server_public_id,
            mcp_tool_public_id=tool_public_id,
            tool_name=context.tool_name,
            tool_permission=permission,
            confirmation_policy=McpConfirmationPolicy(policy.confirmation_policy),
            request_payload=context.request_payload if context.allow_store_unmasked else None,
            masked_request_payload=mask_payload(context.request_payload),
            masked_response_payload=mask_payload(normalized_response_payload),
            call_status=call_status,
            latency_ms=latency_ms,
            last_error=last_error,
            job_run_public_id=context.job_run_public_id,
            llm_run_public_id=context.llm_run_public_id,
            session_public_id=context.session_public_id,
            user_public_id=context.user_public_id,
        )
        return self._repository.create_tool_call(record)


def elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def normalize_response_payload(
    response_payload: Mapping[str, Any] | list[Any] | None,
) -> Mapping[str, Any] | None:
    if isinstance(response_payload, list):
        return {"items": response_payload}
    return response_payload
