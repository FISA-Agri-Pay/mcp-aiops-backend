from __future__ import annotations

from typing import Any, get_args
from uuid import UUID

from aiops_platform.agent.schemas import AgentToolExecutionResult
from aiops_platform.core.config import settings
from aiops_platform.llmops.client import LlmClient, LlmCompletionRequest, create_llm_client
from aiops_platform.llmops.repository import LlmOpsRepository, SqlLlmOpsRepository
from aiops_platform.llmops.schemas import (
    AgentSnapshotListResult,
    AgentSnapshotResult,
    ApprovalRequestListResult,
    ApprovalRequestResult,
    ApprovalStatus,
    LlmRunListResult,
    LlmRunResult,
    LlmRunStatus,
    NotificationOutboxListResult,
    NotificationOutboxResult,
    NotificationStatus,
    PromptScope,
    PromptVersionListResult,
    PromptVersionResult,
)
from aiops_platform.llmops.validation import validate_output_payload
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpToolCallStatus,
    McpToolPermission,
)
from aiops_platform.orchestration.schemas import ChatType


class LlmOpsNotFoundError(LookupError):
    pass


class LlmOpsValidationError(ValueError):
    pass


MAX_LIST_LIMIT = 100
DEFAULT_PROMPTS = {
    "farmer_bnpl": (
        "farmer_bnpl_chat",
        "Summarize Farmer BNPL tool results and return safe checkout guidance.",
    ),
    "admin_copilot": (
        "admin_copilot",
        "Summarize admin risk, infra, and prediction evidence with safe actions.",
    ),
    "rca": (
        "rca",
        "Create an RCA summary from observability evidence.",
    ),
    "ops_report": (
        "ops_report",
        "Create an operations report from pre-aggregated metrics.",
    ),
}
OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["answer"],
}


class LlmOpsService:
    def __init__(
        self,
        *,
        repository: LlmOpsRepository | None = None,
        llm_client: LlmClient | None = None,
    ) -> None:
        self._repository = repository or SqlLlmOpsRepository()
        self._llm_client = llm_client or create_llm_client(settings)

    def ensure_prompt_version(
        self,
        *,
        scope: PromptScope,
        prompt_key: str | None = None,
        template: str | None = None,
        version: str = "1.0.0",
    ) -> PromptVersionResult:
        resolved_prompt_key, resolved_template = resolve_prompt(scope, prompt_key, template)
        return self._repository.ensure_prompt_version(
            prompt_key=resolved_prompt_key,
            version=version,
            scope=scope,
            template=resolved_template,
        )

    def list_prompt_versions(
        self,
        *,
        scope: PromptScope | None = None,
        limit: int = 20,
    ) -> PromptVersionListResult:
        clamped_limit = clamp_limit(limit)
        return PromptVersionListResult(
            scope=scope,
            limit=clamped_limit,
            items=self._repository.list_prompt_versions(scope=scope, limit=clamped_limit),
        )

    def run_agent_completion(
        self,
        *,
        chat_type: ChatType,
        message: str,
        user_id: str,
        tool_results: list[AgentToolExecutionResult],
        job_id: str | None = None,
        session_id: str | None = None,
    ) -> LlmRunResult:
        scope: PromptScope = "farmer_bnpl" if chat_type == "farmer_bnpl" else "admin_copilot"
        prompt = self.ensure_prompt_version(scope=scope)
        input_payload = {
            "chat_type": chat_type,
            "message": message,
            "user_id": user_id,
            "tool_results": [
                result.model_dump(mode="json", exclude={"masked_request_payload"})
                for result in tool_results
            ],
        }
        request = LlmCompletionRequest(
            chat_type=chat_type,
            prompt_key=prompt.prompt_key,
            prompt_template=prompt.template,
            input_payload=mask_payload(input_payload) or {},
            output_schema=OUTPUT_SCHEMA,
        )
        try:
            response = self._llm_client.complete(request)
            validation = validate_output_payload(response.output_payload, OUTPUT_SCHEMA)
            status: LlmRunStatus = "SUCCESS" if validation.is_valid else "VALIDATION_FAILED"
            last_error = "; ".join(validation.errors) if validation.errors else None
            return self._repository.record_llm_run(
                provider=response.provider,
                model=response.model,
                prompt_key=prompt.prompt_key,
                prompt_version_id=prompt.prompt_version_id,
                status=status,
                masked_input=request.input_payload,
                masked_output=mask_payload(response.output_payload) or {},
                output_schema=OUTPUT_SCHEMA,
                validation_errors=validation.errors,
                job_id=job_id,
                session_id=session_id,
                latency_ms=response.latency_ms,
                last_error=last_error,
            )
        except Exception as exc:
            return self._repository.record_llm_run(
                provider=self._llm_client.provider,
                model=self._llm_client.model,
                prompt_key=prompt.prompt_key,
                prompt_version_id=prompt.prompt_version_id,
                status="FAILED",
                masked_input=request.input_payload,
                masked_output={},
                output_schema=OUTPUT_SCHEMA,
                validation_errors=[],
                job_id=job_id,
                session_id=session_id,
                last_error=exc.__class__.__name__,
            )

    def run_rca_completion(
        self,
        *,
        incident: dict[str, Any],
        alert: dict[str, Any],
        snapshot: dict[str, Any],
        evidence: list[dict[str, Any]],
        job_id: str | None = None,
    ) -> LlmRunResult:
        prompt = self.ensure_prompt_version(
            scope="rca",
            prompt_key="rca.infra.v1",
            template=(
                "Create an infrastructure RCA from Alertmanager, observability, "
                "prediction, and autoscaling evidence. Return a concise answer "
                "with probable root cause, impact, confidence, and recommended actions."
            ),
        )
        input_payload = {
            "incident": incident,
            "alert": alert,
            "snapshot": snapshot,
            "evidence": evidence,
        }
        request = LlmCompletionRequest(
            chat_type="admin_copilot",
            prompt_key=prompt.prompt_key,
            prompt_template=prompt.template,
            input_payload=mask_payload(input_payload) or {},
            output_schema=OUTPUT_SCHEMA,
        )
        try:
            response = self._llm_client.complete(request)
            validation = validate_output_payload(response.output_payload, OUTPUT_SCHEMA)
            status: LlmRunStatus = "SUCCESS" if validation.is_valid else "VALIDATION_FAILED"
            last_error = "; ".join(validation.errors) if validation.errors else None
            return self._repository.record_llm_run(
                provider=response.provider,
                model=response.model,
                prompt_key=prompt.prompt_key,
                prompt_version_id=prompt.prompt_version_id,
                status=status,
                masked_input=request.input_payload,
                masked_output=mask_payload(response.output_payload) or {},
                output_schema=OUTPUT_SCHEMA,
                validation_errors=validation.errors,
                job_id=job_id,
                session_id=None,
                latency_ms=response.latency_ms,
                last_error=last_error,
            )
        except Exception as exc:
            return self._repository.record_llm_run(
                provider=self._llm_client.provider,
                model=self._llm_client.model,
                prompt_key=prompt.prompt_key,
                prompt_version_id=prompt.prompt_version_id,
                status="FAILED",
                masked_input=request.input_payload,
                masked_output={},
                output_schema=OUTPUT_SCHEMA,
                validation_errors=[],
                job_id=job_id,
                session_id=None,
                last_error=exc.__class__.__name__,
            )

    def get_llm_run(self, llm_run_id: str) -> LlmRunResult:
        llm_run = self._repository.get_llm_run(llm_run_id)
        if llm_run is None:
            raise LlmOpsNotFoundError("LLM run was not found.")
        return llm_run

    def list_llm_runs(
        self,
        *,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> LlmRunListResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_llm_status(status)
        normalized_provider = normalize_optional_text(provider)
        return LlmRunListResult(
            provider=normalized_provider,
            status=normalized_status,
            limit=clamped_limit,
            items=self._repository.list_llm_runs(
                provider=normalized_provider,
                status=normalized_status,
                limit=clamped_limit,
            ),
        )

    def create_approval_for_tool_result(
        self,
        *,
        tool_result: AgentToolExecutionResult,
        requester_id: str | None = None,
    ) -> ApprovalRequestResult | None:
        if not tool_result.requires_approval:
            return None
        approval_type = approval_type_for_tool_result(tool_result)
        return self._repository.create_approval_request(
            approval_type=approval_type,
            target_type=f"{tool_result.server_name}.{tool_result.tool_name}",
            target_id=None,
            requester_id=requester_id if is_uuid(requester_id) else None,
            reason=f"{tool_result.tool_name} requires {approval_type}.",
            request_payload=mask_payload(tool_result.request_payload) or {},
        )

    def list_approval_requests(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> ApprovalRequestListResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_approval_status(status)
        return ApprovalRequestListResult(
            status=normalized_status,
            limit=clamped_limit,
            items=self._repository.list_approval_requests(
                status=normalized_status,
                limit=clamped_limit,
            ),
        )

    def create_notification(
        self,
        *,
        channel: str,
        content: str,
        payload: dict[str, Any] | None = None,
        recipient: str | None = None,
        title: str | None = None,
    ) -> NotificationOutboxResult:
        normalized_channel = normalize_notification_channel(channel)
        return self._repository.create_notification(
            channel=normalized_channel,
            content=content,
            payload=mask_payload(payload or {}) or {},
            recipient=recipient,
            title=title,
        )

    def list_notifications(
        self,
        *,
        status: str | None = None,
        limit: int = 20,
    ) -> NotificationOutboxListResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_notification_status(status)
        return NotificationOutboxListResult(
            status=normalized_status,
            limit=clamped_limit,
            items=self._repository.list_notifications(
                status=normalized_status,
                limit=clamped_limit,
            ),
        )

    def create_agent_snapshot(
        self,
        *,
        snapshot_type: str,
        job_id: str | None,
        session_id: str | None,
        llm_run_id: str | None,
        payload: dict[str, Any],
    ) -> AgentSnapshotResult:
        return self._repository.create_agent_snapshot(
            snapshot_type=snapshot_type,
            job_id=job_id,
            session_id=session_id,
            llm_run_id=llm_run_id,
            payload=mask_payload(payload) or {},
        )

    def list_agent_snapshots(
        self,
        *,
        snapshot_type: str | None = None,
        limit: int = 20,
    ) -> AgentSnapshotListResult:
        clamped_limit = clamp_limit(limit)
        normalized_snapshot_type = normalize_optional_text(snapshot_type)
        return AgentSnapshotListResult(
            snapshot_type=normalized_snapshot_type,
            limit=clamped_limit,
            items=self._repository.list_agent_snapshots(
                snapshot_type=normalized_snapshot_type,
                limit=clamped_limit,
            ),
        )


def resolve_prompt(
    scope: PromptScope,
    prompt_key: str | None,
    template: str | None,
) -> tuple[str, str]:
    default_key, default_template = DEFAULT_PROMPTS.get(scope, DEFAULT_PROMPTS["rca"])
    return prompt_key or default_key, template or default_template


def approval_type_for_tool_result(tool_result: AgentToolExecutionResult) -> str:
    permission = McpToolPermission(tool_result.tool_permission)
    confirmation_policy = McpConfirmationPolicy(tool_result.confirmation_policy)
    if permission == McpToolPermission.OPS_WRITE:
        return "OPS_APPROVAL"
    if confirmation_policy == McpConfirmationPolicy.ADMIN_APPROVAL:
        return "ADMIN_APPROVAL"
    return "USER_CONFIRMATION"


def clamp_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise LlmOpsValidationError("limit must be an integer.")
    return min(max(limit, 1), MAX_LIST_LIMIT)


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def normalize_optional_llm_status(value: str | None) -> LlmRunStatus | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in get_args(LlmRunStatus):
        raise LlmOpsValidationError("LLM run status is invalid.")
    return normalized


def normalize_optional_approval_status(value: str | None) -> ApprovalStatus | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in get_args(ApprovalStatus):
        raise LlmOpsValidationError("approval status is invalid.")
    return normalized


def normalize_optional_notification_status(value: str | None) -> NotificationStatus | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in get_args(NotificationStatus):
        raise LlmOpsValidationError("notification status is invalid.")
    return normalized


def normalize_notification_channel(value: str) -> str:
    if not isinstance(value, str):
        raise LlmOpsValidationError("notification channel is invalid.")
    normalized = value.strip().upper()
    if normalized in {"SLACK", "EMAIL", "WEBHOOK", "DASHBOARD"}:
        return normalized
    raise LlmOpsValidationError("notification channel is invalid.")


def is_uuid(value: str | None) -> bool:
    try:
        UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def has_failed_tool(tool_results: list[AgentToolExecutionResult]) -> bool:
    return any(
        McpToolCallStatus(result.call_status) == McpToolCallStatus.FAILED
        for result in tool_results
    )
