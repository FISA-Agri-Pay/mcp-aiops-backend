from __future__ import annotations

import logging
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
logger = logging.getLogger(__name__)
DEFAULT_PROMPTS = {
    "farmer_bnpl": (
        "farmer_bnpl_chat",
        (
            "콩콩팥팥 서비스 사용자 챗봇으로서 한국어로만 답변한다. "
            "반드시 JSON object를 반환하되, answer 필드는 한국어 자연어 문자열이어야 한다. "
            "answer를 object, array, dict, markdown AST로 반환하지 않는다. "
            "사용자에게 내부 tool 이름, MCP, API 오류, profile retrieving issue 같은 "
            "개발자용 표현을 노출하지 않는다. "
            "이미 UI 카드로 표시될 수 있는 외상 한도 수치는 본문에서 길게 반복하지 말고 "
            "필요한 경우 한 문장으로만 보조 설명한다. "
            "input의 capability가 credit_limit_status이면 총 한도, 사용 금액, 잔여 한도, "
            "상태를 한국어로 짧게 요약한다. "
            "input의 capability가 fertilizer_recommendation이면 비료/농자재 추천을 중심으로 답하고 "
            "외상 한도는 구매 가능 여부 판단에 필요한 만큼만 언급한다. "
            "tool_results에 추천 상품 items가 있으면 상품명, 가격, 한도 내 구매 가능 여부를 "
            "반드시 포함한다. "
            "추천 상품이나 추천 근거가 없으면 "
            "'현재 추천 가능한 상품을 찾지 못했습니다'처럼 말하고, "
            "작물, 재배 면적, 지역, 생육 단계 중 필요한 추가 정보를 물어본다. "
            "tool이 실패해도 '요청이 실패했습니다'라고 끝내지 말고 "
            "현재 확인 가능한 내용과 사용자가 추가로 알려줄 정보를 안내한다. "
            "input의 capability가 repayment_guidance이면 "
            "상환일, 이자, 연체 여부와 다음 행동을 안내한다. "
            "input의 capability가 delivery_status이면 최근 주문의 배송 상태를 안내한다. "
            "input의 capability가 checkout_guidance이면 "
            "사용자가 확정하기 전에는 결제가 완료됐다고 말하지 않는다. "
            "답변은 2~5개의 짧은 문장 또는 '- ' 불릿으로 작성하고, "
            "과장하거나 확인되지 않은 내용을 단정하지 않는다."
        ),
    ),
    "admin_copilot": (
        "admin_copilot",
        (
            "관리자 RiskOps Copilot으로서 MCP Tool 결과만 근거로 한국어 답변을 작성한다. "
            "반드시 JSON object를 반환하되, answer 필드는 한국어 자연어 문자열이어야 한다. "
            "answer를 object, array, dict, markdown AST로 반환하지 않는다. "
            "운영자가 바로 판단할 수 있도록 핵심 요약, 근거 수치, 위험 신호, 원인 후보, "
            "우선순위가 높은 다음 조치를 구분해 작성한다. 단순 수치 나열로 끝내지 말고 "
            "무엇을 봐야 하는지, 지금 조치가 필요한지, 추가 확인이 필요한 데이터를 함께 제시한다. "
            "answer는 프론트가 plain text로 렌더링해도 읽히도록 짧은 섹션과 줄바꿈을 포함한다. "
            "굵게 표시, 표, 긴 단일 문단은 사용하지 않는다. "
            "운영 데이터 기반 답변은 반드시 요약, 주요 지표, 판단, 우선 조치, 데이터 한계 "
            "5개 섹션 제목만 이 순서대로 사용한다. "
            "각 섹션 제목은 한 줄로 쓰고, 섹션 사이는 빈 줄로 구분한다. "
            "각 섹션의 내용은 '- ' 불릿으로 작성하되 섹션당 1~4개로 제한한다. "
            "단, input의 capability가 smalltalk, help, unsupported이면 "
            "섹션 형식을 강제하지 않고 짧게 답한다. "
            "BNPL 심사, 연체 위험, 운영/스케일링 근거를 다룰 때는 "
            "영향 범위와 관리 포인트를 포함한다. "
            "input의 capability가 ops_action_prioritization이면 즉시 확인할 항목, 오늘 우선 조치, "
            "후속 모니터링, 데이터 한계를 나눠서 운영자가 바로 실행할 수 있게 작성한다. "
            "확인되지 않은 내용은 추정으로 단정하지 않는다. "
            "사용자가 오늘, 최근, 이번 주처럼 기간을 물어도 "
            "Tool 결과에 해당 기간 필드가 없으면 그 기간의 데이터라고 단정하지 말고 "
            "'현재 조회 가능한 요약 기준'이라고 명시한다. 지원하지 않는 분석이나 "
            "Tool 결과에 없는 항목은 데이터 없음으로 설명한다."
        ),
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
    "properties": {
        "answer": {"type": "string"},
    },
}
OPS_REPORT_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["answer"],
    "properties": {
        "answer": {"type": "string"},
        "executive_summary": {"type": "string"},
        "risk_level": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "incident_highlights": {"type": "array", "items": {"type": "string"}},
        "rca_highlights": {"type": "array", "items": {"type": "string"}},
        "prediction_scaling_insights": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {"type": "array", "items": {"type": "string"}},
        "data_quality_notes": {"type": "array", "items": {"type": "string"}},
    },
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
        capability: str | None = None,
    ) -> LlmRunResult:
        scope: PromptScope = "farmer_bnpl" if chat_type == "farmer_bnpl" else "admin_copilot"
        prompt = self.ensure_prompt_version(scope=scope)
        input_payload = {
            "chat_type": chat_type,
            "message": message,
            "user_id": user_id,
            "capability": capability,
            "tool_results": [
                serialize_tool_result_for_llm(result, chat_type=chat_type)
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
            last_error = format_llm_exception(exc)
            logger.exception(
                "LLM agent completion failed provider=%s model=%s prompt_key=%s.",
                self._llm_client.provider,
                self._llm_client.model,
                prompt.prompt_key,
            )
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
                last_error=last_error,
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
            last_error = format_llm_exception(exc)
            logger.exception(
                "RCA LLM completion failed provider=%s model=%s prompt_key=%s.",
                self._llm_client.provider,
                self._llm_client.model,
                prompt.prompt_key,
            )
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
                last_error=last_error,
            )

    def run_ops_report_completion(
        self,
        *,
        report_type: str,
        period: dict[str, Any],
        incidents: list[dict[str, Any]],
        rca_reports: list[dict[str, Any]],
        metric_summaries: list[dict[str, Any]],
        job_id: str | None = None,
    ) -> LlmRunResult:
        raw_report_type = "" if report_type is None else str(report_type)
        normalized_report_type = raw_report_type.strip().lower()
        input_payload = {
            "report_type": raw_report_type,
            "period": period,
            "incidents": incidents,
            "rca_reports": rca_reports,
            "metric_summaries": metric_summaries,
        }
        if not normalized_report_type:
            return self._repository.record_llm_run(
                provider=self._llm_client.provider,
                model=self._llm_client.model,
                prompt_key="ops_report.invalid.v1",
                prompt_version_id=None,
                status="FAILED",
                masked_input=mask_payload(input_payload) or {},
                masked_output={},
                output_schema=OPS_REPORT_OUTPUT_SCHEMA,
                validation_errors=["report_type is required."],
                job_id=job_id,
                session_id=None,
                last_error="report_type is required.",
            )
        prompt = self.ensure_prompt_version(
            scope="ops_report",
            prompt_key=f"ops_report.{normalized_report_type}.v1",
            template=(
                "Create a concise operations report from pre-aggregated "
                "incident, RCA, prediction, and autoscaling evidence. "
                "Return JSON with answer, executive_summary, risk_level, "
                "key_findings, incident_highlights, rca_highlights, "
                "prediction_scaling_insights, recommended_actions, and "
                "data_quality_notes. Write every narrative field in Korean. "
                "Keep metric names, alert names, source types, Kubernetes "
                "resource names, and identifiers in their original English form. "
                "Keep answer and executive_summary under 180 Korean characters. "
                "Each list must have at most 3 items, and each item must be under "
                "90 Korean characters."
            ),
        )
        request = LlmCompletionRequest(
            chat_type="admin_copilot",
            prompt_key=prompt.prompt_key,
            prompt_template=prompt.template,
            input_payload=mask_payload(input_payload) or {},
            output_schema=OPS_REPORT_OUTPUT_SCHEMA,
        )
        try:
            response = self._llm_client.complete(request)
            validation = validate_output_payload(
                response.output_payload,
                OPS_REPORT_OUTPUT_SCHEMA,
            )
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
                output_schema=OPS_REPORT_OUTPUT_SCHEMA,
                validation_errors=validation.errors,
                job_id=job_id,
                session_id=None,
                latency_ms=response.latency_ms,
                last_error=last_error,
            )
        except Exception as exc:
            last_error = format_llm_exception(exc)
            logger.exception(
                "Ops report LLM completion failed provider=%s model=%s prompt_key=%s.",
                self._llm_client.provider,
                self._llm_client.model,
                prompt.prompt_key,
            )
            return self._repository.record_llm_run(
                provider=self._llm_client.provider,
                model=self._llm_client.model,
                prompt_key=prompt.prompt_key,
                prompt_version_id=prompt.prompt_version_id,
                status="FAILED",
                masked_input=request.input_payload,
                masked_output={},
                output_schema=OPS_REPORT_OUTPUT_SCHEMA,
                validation_errors=[],
                job_id=job_id,
                session_id=None,
                last_error=last_error,
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
        related_table: str | None = None,
        related_public_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> NotificationOutboxResult:
        normalized_channel = normalize_notification_channel(channel)
        return self._repository.create_notification(
            channel=normalized_channel,
            content=content,
            payload=mask_payload(payload or {}) or {},
            recipient=recipient,
            title=title,
            related_table=related_table,
            related_public_id=related_public_id,
            idempotency_key=idempotency_key,
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

    def update_notification_status(
        self,
        notification_id: str,
        *,
        status: str,
        last_error: str | None = None,
    ) -> NotificationOutboxResult:
        normalized_status = normalize_optional_notification_status(status)
        if normalized_status is None:
            raise LlmOpsValidationError("notification status is invalid.")
        notification = self._repository.update_notification_status(
            notification_id,
            status=normalized_status,
            last_error=last_error,
        )
        if notification is None:
            raise LlmOpsNotFoundError("notification was not found.")
        return notification

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


def format_llm_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        message = exc.__class__.__name__
    formatted = f"{exc.__class__.__name__}: {message}"
    if len(formatted) <= 1000:
        return formatted
    return f"{formatted[:1000]}..."


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


def serialize_tool_result_for_llm(
    result: AgentToolExecutionResult,
    *,
    chat_type: ChatType,
) -> dict[str, Any]:
    payload = result.model_dump(mode="json", exclude={"masked_request_payload"})
    if chat_type != "farmer_bnpl":
        return payload

    call_status = McpToolCallStatus(result.call_status)
    if call_status == McpToolCallStatus.SUCCESS:
        return payload
    if call_status not in {McpToolCallStatus.FAILED, McpToolCallStatus.TIMEOUT}:
        return payload

    payload["error_message"] = (
        "현재 이 정보는 확인하지 못했습니다. 사용자에게 내부 오류 원인을 설명하지 말고 "
        "필요한 추가 정보나 다시 시도 안내만 제공하세요."
    )
    payload["response_payload"] = {}
    payload["masked_response_payload"] = {}
    payload["failure_policy"] = "hide_internal_error_from_user"
    return payload
