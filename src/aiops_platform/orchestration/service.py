from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.registry import list_mcp_tools
from aiops_platform.mcp.schemas import McpExecutionPolicy, McpToolCallStatus, McpToolPermission
from aiops_platform.orchestration.schemas import (
    ChatAskResult,
    ChatMessageResult,
    ChatMessagesResult,
    ChatSessionResult,
    ChatType,
    JobActionPreviewResult,
    JobListResult,
    JobResult,
    McpToolCallListResult,
    McpToolCallResult,
    MessageRole,
    PlannedToolResult,
)


class OrchestrationNotFoundError(LookupError):
    pass


class OrchestrationValidationError(ValueError):
    pass


MAX_LIST_LIMIT = 100


class OrchestrationService:
    def __init__(self) -> None:
        self._sessions: dict[str, ChatSessionResult] = {}
        self._messages: dict[str, list[ChatMessageResult]] = {}
        self._jobs: dict[str, JobResult] = {}
        self._tool_calls: dict[str, McpToolCallResult] = {}

    def create_chat_session(
        self,
        *,
        chat_type: ChatType,
        user_id: str,
        title: str | None = None,
    ) -> ChatSessionResult:
        now = current_timestamp()
        session = ChatSessionResult(
            session_id=build_public_id("chat-session"),
            chat_type=chat_type,
            user_id=user_id,
            title=title,
            status="OPEN",
            created_at=now,
            updated_at=now,
        )
        self._sessions[session.session_id] = session
        self._messages[session.session_id] = []
        return session

    def get_chat_session(self, session_id: str, *, chat_type: ChatType) -> ChatSessionResult:
        session = self._sessions.get(session_id)
        if session is None or session.chat_type != chat_type:
            raise OrchestrationNotFoundError("chat session was not found.")
        return session

    def list_chat_messages(self, session_id: str, *, chat_type: ChatType) -> ChatMessagesResult:
        self.get_chat_session(session_id, chat_type=chat_type)
        return ChatMessagesResult(
            session_id=session_id,
            items=list(self._messages.get(session_id, [])),
        )

    def close_chat_session(self, session_id: str, *, chat_type: ChatType) -> ChatSessionResult:
        session = self.get_chat_session(session_id, chat_type=chat_type)
        closed_session = session.model_copy(
            update={"status": "CLOSED", "updated_at": current_timestamp()}
        )
        self._sessions[session_id] = closed_session
        return closed_session

    def ask_farmer_chat(
        self,
        *,
        message: str,
        user_id: str,
        session_id: str | None = None,
    ) -> ChatAskResult:
        session = self._resolve_or_create_session(
            session_id=session_id,
            chat_type="farmer_bnpl",
            user_id=user_id,
            title="Farmer BNPL chat",
        )
        return self._answer_chat(
            session=session,
            message=message,
            job_type="farmer_chat",
            planned_tools=[
                ("farmer-bnpl-mcp", "get_user_credit_limit"),
                ("farmer-bnpl-mcp", "get_farmer_profile"),
                ("farm-advisory-mcp", "recommend_fertilizer_requirements"),
                ("farmer-bnpl-mcp", "search_lowest_price_fertilizer"),
                ("farmer-bnpl-mcp", "prepare_bnpl_checkout_payload"),
            ],
            answer=(
                "MCP orchestration preview created. The client can execute the planned "
                "Farmer BNPL and farm advisory tools before showing a checkout confirmation UI."
            ),
        )

    def ask_admin_copilot(
        self,
        *,
        message: str,
        user_id: str,
        session_id: str | None = None,
    ) -> ChatAskResult:
        session = self._resolve_or_create_session(
            session_id=session_id,
            chat_type="admin_copilot",
            user_id=user_id,
            title="Admin Copilot chat",
        )
        return self._answer_chat(
            session=session,
            message=message,
            job_type="admin_copilot",
            planned_tools=[
                ("admin-riskops-mcp", "get_credit_review_queue"),
                ("admin-riskops-mcp", "get_bnpl_summary"),
                ("infraops-mcp", "query_multi_cluster_prometheus"),
                ("prediction-scaling-mcp", "get_scaling_summary"),
            ],
            answer=(
                "MCP orchestration preview created. The client can execute the planned "
                "RiskOps, InfraOps, and prediction-scaling tools for the copilot answer."
            ),
        )

    def list_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 20,
    ) -> JobListResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_upper(status)
        normalized_job_type = normalize_optional_lower(job_type)
        jobs = [
            job
            for job in self._jobs.values()
            if (normalized_status is None or job.status == normalized_status)
            and (normalized_job_type is None or job.job_type == normalized_job_type)
        ]
        jobs.sort(key=lambda job: job.created_at, reverse=True)
        return JobListResult(
            status=normalized_status,
            job_type=normalized_job_type,
            limit=clamped_limit,
            items=jobs[:clamped_limit],
        )

    def get_job(self, job_id: str) -> JobResult:
        job = self._jobs.get(job_id)
        if job is None:
            raise OrchestrationNotFoundError("job was not found.")
        return job

    def preview_retry_job(self, job_id: str) -> JobActionPreviewResult:
        job = self.get_job(job_id)
        return JobActionPreviewResult(
            job_id=job.job_id,
            action="retry",
            current_status=job.status,
            message="Retry execution is not connected yet; this is a dry-run preview.",
        )

    def preview_cancel_job(self, job_id: str) -> JobActionPreviewResult:
        job = self.get_job(job_id)
        return JobActionPreviewResult(
            job_id=job.job_id,
            action="cancel",
            current_status=job.status,
            message="Cancel execution is not connected yet; this is a dry-run preview.",
        )

    def list_tool_calls(
        self,
        *,
        server_name: str | None = None,
        tool_name: str | None = None,
        permission: McpToolPermission | None = None,
        status: McpToolCallStatus | None = None,
        limit: int = 20,
    ) -> McpToolCallListResult:
        clamped_limit = clamp_limit(limit)
        normalized_server = normalize_optional_lower(server_name)
        normalized_tool = normalize_optional_lower(tool_name)
        calls = [
            call
            for call in self._tool_calls.values()
            if (normalized_server is None or call.server_name == normalized_server)
            and (normalized_tool is None or call.tool_name == normalized_tool)
            and (permission is None or call.tool_permission == permission)
            and (status is None or call.call_status == status)
        ]
        calls.sort(key=lambda call: call.created_at, reverse=True)
        return McpToolCallListResult(
            server_name=normalized_server,
            tool_name=normalized_tool,
            permission=permission,
            status=status,
            limit=clamped_limit,
            items=calls[:clamped_limit],
        )

    def get_tool_call(self, tool_call_id: str) -> McpToolCallResult:
        tool_call = self._tool_calls.get(tool_call_id)
        if tool_call is None:
            raise OrchestrationNotFoundError("MCP tool call was not found.")
        return tool_call

    def _resolve_or_create_session(
        self,
        *,
        session_id: str | None,
        chat_type: ChatType,
        user_id: str,
        title: str,
    ) -> ChatSessionResult:
        if session_id is None:
            return self.create_chat_session(chat_type=chat_type, user_id=user_id, title=title)
        session = self.get_chat_session(session_id, chat_type=chat_type)
        if session.status != "OPEN":
            raise OrchestrationValidationError("chat session is closed.")
        return session

    def _answer_chat(
        self,
        *,
        session: ChatSessionResult,
        message: str,
        job_type: str,
        planned_tools: list[tuple[str, str]],
        answer: str,
    ) -> ChatAskResult:
        user_message = self._append_message(
            session_id=session.session_id,
            role="USER",
            content=message,
        )
        job = self._create_job(
            job_type=job_type,
            entity_type="chat_session",
            entity_id=session.session_id,
        )
        planned_tool_results = [
            self._build_planned_tool(server_name=server_name, tool_name=tool_name)
            for server_name, tool_name in planned_tools
        ]
        tool_calls = [
            self._record_tool_call(
                server_name=tool.server_name,
                tool_name=tool.tool_name,
                request_payload={
                    "session_id": session.session_id,
                    "message": message,
                    "access_token": "example-token",
                },
                response_payload={
                    "dry_run": True,
                    "planned_by": "api_orchestration_skeleton",
                },
                call_status=(
                    McpToolCallStatus.SUCCESS
                    if tool.execution_policy == McpExecutionPolicy.ALLOWED
                    else McpToolCallStatus.APPROVAL_REQUIRED
                ),
                job_id=job.job_id,
                session_id=session.session_id,
            )
            for tool in planned_tool_results
        ]
        assistant_message = self._append_message(
            session_id=session.session_id,
            role="ASSISTANT",
            content=answer,
            mcp_tool_call_ids=[tool_call.tool_call_id for tool_call in tool_calls],
        )
        self._touch_session(session.session_id)
        return ChatAskResult(
            session=self._sessions[session.session_id],
            user_message=user_message,
            assistant_message=assistant_message,
            job=job,
            planned_tools=planned_tool_results,
        )

    def _append_message(
        self,
        *,
        session_id: str,
        role: MessageRole,
        content: str,
        mcp_tool_call_ids: list[str] | None = None,
    ) -> ChatMessageResult:
        message = ChatMessageResult(
            message_id=build_public_id("chat-message"),
            session_id=session_id,
            role=role,
            content=content,
            created_at=current_timestamp(),
            mcp_tool_call_ids=mcp_tool_call_ids or [],
        )
        self._messages.setdefault(session_id, []).append(message)
        return message

    def _create_job(self, *, job_type: str, entity_type: str, entity_id: str) -> JobResult:
        now = current_timestamp()
        job = JobResult(
            job_id=build_public_id("job"),
            job_type=job_type,
            status="QUEUED",
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=now,
            updated_at=now,
        )
        self._jobs[job.job_id] = job
        return job

    def _build_planned_tool(self, *, server_name: str, tool_name: str) -> PlannedToolResult:
        tool = resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        policy = resolve_tool_policy(McpToolPermission(tool.tool_permission))
        return PlannedToolResult(
            server_name=tool.server_name,
            tool_name=tool.tool_name,
            tool_permission=tool.tool_permission,
            confirmation_policy=policy.confirmation_policy,
            execution_policy=policy.execution_policy,
        )

    def _record_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
        call_status: McpToolCallStatus,
        job_id: str,
        session_id: str,
    ) -> McpToolCallResult:
        tool = resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        policy = resolve_tool_policy(McpToolPermission(tool.tool_permission))
        tool_call = McpToolCallResult(
            tool_call_id=build_public_id("tool-call"),
            server_name=tool.server_name,
            tool_name=tool.tool_name,
            tool_permission=tool.tool_permission,
            confirmation_policy=policy.confirmation_policy,
            call_status=call_status,
            execution_policy=policy.execution_policy,
            masked_request_payload=mask_payload(request_payload),
            masked_response_payload=mask_payload(response_payload),
            latency_ms=0,
            job_id=job_id,
            session_id=session_id,
            created_at=current_timestamp(),
        )
        self._tool_calls[tool_call.tool_call_id] = tool_call
        return tool_call

    def _touch_session(self, session_id: str) -> None:
        session = self._sessions[session_id]
        self._sessions[session_id] = session.model_copy(
            update={"updated_at": current_timestamp()}
        )


def resolve_registered_tool(*, server_name: str, tool_name: str):
    for tool in list_mcp_tools(server_name=server_name):
        if tool.tool_name == tool_name:
            return tool
    raise OrchestrationValidationError("MCP tool is not registered.")


def clamp_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise OrchestrationValidationError("limit must be an integer.")
    return min(max(limit, 1), MAX_LIST_LIMIT)


def normalize_optional_lower(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def normalize_optional_upper(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


def current_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def build_public_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"
