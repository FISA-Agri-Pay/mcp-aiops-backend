from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, get_args
from uuid import uuid4

from aiops_platform.agent.orchestrator import AgentOrchestrator
from aiops_platform.agent.schemas import AgentToolExecutionResult
from aiops_platform.llmops.schemas import LlmRunResult
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.registry import list_mcp_tools
from aiops_platform.mcp.schemas import McpToolCallStatus, McpToolPermission
from aiops_platform.orchestration.repository import (
    OrchestrationRepository,
    SqlOrchestrationRepository,
)
from aiops_platform.orchestration.schemas import (
    ChatAskResult,
    ChatMessageResult,
    ChatMessagesResult,
    ChatSessionListResult,
    ChatSessionResult,
    ChatStatus,
    ChatType,
    JobActionPreviewResult,
    JobListResult,
    JobResult,
    JobStatus,
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
logger = logging.getLogger(__name__)


class OrchestrationService:
    def __init__(
        self,
        *,
        agent_orchestrator: AgentOrchestrator | None = None,
        repository: OrchestrationRepository | None = None,
        llmops_service: LlmOpsService | None = None,
    ) -> None:
        self._agent_orchestrator = agent_orchestrator or AgentOrchestrator()
        self._repository = repository or SqlOrchestrationRepository()
        self._llmops_service = llmops_service or LlmOpsService()

    def create_chat_session(
        self,
        *,
        chat_type: ChatType,
        user_id: str,
        title: str | None = None,
    ) -> ChatSessionResult:
        return self._repository.create_chat_session(
            chat_type=chat_type,
            user_id=user_id,
            title=title,
        )

    def get_chat_session(self, session_id: str, *, chat_type: ChatType) -> ChatSessionResult:
        session = self._repository.get_chat_session(session_id, chat_type=chat_type)
        if session is None:
            raise OrchestrationNotFoundError("chat session was not found.")
        return session

    def list_chat_sessions(
        self,
        *,
        chat_type: ChatType,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> ChatSessionListResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_chat_status(status)
        normalized_user_id = normalize_optional_text(user_id)
        return ChatSessionListResult(
            status=normalized_status,
            user_id=normalized_user_id,
            limit=clamped_limit,
            items=self._repository.list_chat_sessions(
                chat_type=chat_type,
                user_id=normalized_user_id,
                status=normalized_status,
                limit=clamped_limit,
            ),
        )

    def list_chat_messages(self, session_id: str, *, chat_type: ChatType) -> ChatMessagesResult:
        self.get_chat_session(session_id, chat_type=chat_type)
        return self._repository.list_chat_messages(session_id)

    def close_chat_session(self, session_id: str, *, chat_type: ChatType) -> ChatSessionResult:
        self.get_chat_session(session_id, chat_type=chat_type)
        closed_session = self._repository.close_chat_session(session_id)
        if closed_session is None:
            raise OrchestrationNotFoundError("chat session was not found.")
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
            user_id=user_id,
            job_type="farmer_chat",
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
            title=build_session_title(message),
        )
        return self._answer_chat(
            session=session,
            message=message,
            user_id=user_id,
            job_type="admin_copilot",
        )

    def list_jobs(
        self,
        *,
        status: str | None = None,
        job_type: str | None = None,
        limit: int = 20,
    ) -> JobListResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_job_status(status)
        normalized_job_type = normalize_optional_lower(job_type)
        return JobListResult(
            status=normalized_status,
            job_type=normalized_job_type,
            limit=clamped_limit,
            items=self._repository.list_jobs(
                status=normalized_status,
                job_type=normalized_job_type,
                limit=clamped_limit,
            ),
        )

    def get_job(self, job_id: str) -> JobResult:
        job = self._repository.get_job(job_id)
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
        return McpToolCallListResult(
            server_name=normalized_server,
            tool_name=normalized_tool,
            permission=permission,
            status=status,
            limit=clamped_limit,
            items=self._repository.list_tool_calls(
                server_name=normalized_server,
                tool_name=normalized_tool,
                permission=permission,
                status=status,
                limit=clamped_limit,
            ),
        )

    def get_tool_call(self, tool_call_id: str) -> McpToolCallResult:
        tool_call = self._repository.get_tool_call(tool_call_id)
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
        user_id: str,
        job_type: str,
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
            status="RUNNING",
        )
        try:
            agent_run = self._agent_orchestrator.run(
                chat_type=session.chat_type,
                message=message,
                user_id=user_id,
            )
            planned_tool_results = [
                self._build_planned_tool(
                    server_name=tool_result.server_name,
                    tool_name=tool_result.tool_name,
                )
                for tool_result in agent_run.tool_results
            ]
            tool_results = [
                self._persist_agent_tool_result(
                    tool_result=tool_result,
                    job_id=job.job_id,
                    session_id=session.session_id,
                )
                for tool_result in agent_run.tool_results
            ]
            llm_run = self._record_llm_run(
                chat_type=session.chat_type,
                message=message,
                user_id=user_id,
                tool_results=tool_results,
                job_id=job.job_id,
                session_id=session.session_id,
            )
            self._attach_llm_run_to_tool_calls(
                job_id=job.job_id,
                session_id=session.session_id,
                llm_run_id=llm_run.llm_run_id,
            )
            self._create_agent_snapshot(
                chat_type=session.chat_type,
                job_id=job.job_id,
                session_id=session.session_id,
                llm_run=llm_run,
                tool_results=tool_results,
            )
            self._create_approval_requests(
                user_id=user_id,
                tool_results=tool_results,
            )
            job = self._finish_job(job.job_id, tool_results)
            assistant_content = resolve_assistant_content(
                llm_run.masked_output,
                agent_run.answer,
            )
            ui_cards = build_chat_ui_cards(session.chat_type, message, tool_results)
            ui_actions = build_chat_ui_actions(ui_cards)
        except Exception as exc:
            logger.exception("Agent orchestration failed for job %s.", job.job_id)
            planned_tool_results = []
            tool_results = []
            llm_run = None
            job = self._finish_job(
                job.job_id,
                tool_results,
                error_message=f"Agent execution failed: {exc.__class__.__name__}",
            )
            assistant_content = "Agent execution failed before MCP tool results were finalized."
            ui_cards = []
            ui_actions = []
        assistant_message = self._append_message(
            session_id=session.session_id,
            role="ASSISTANT",
            content=assistant_content,
            mcp_tool_call_ids=[
                tool_result.tool_call_id
                for tool_result in tool_results
                if tool_result.tool_call_id is not None
            ],
            ui_cards=ui_cards,
            ui_actions=ui_actions,
        )
        self._touch_session(session.session_id)
        updated_session = self.get_chat_session(session.session_id, chat_type=session.chat_type)
        return ChatAskResult(
            session=updated_session,
            user_message=user_message,
            assistant_message=assistant_message,
            job=job,
            llm_run=llm_run,
            planned_tools=planned_tool_results,
            tool_results=tool_results,
            ui_cards=ui_cards,
            ui_actions=ui_actions,
        )

    def _append_message(
        self,
        *,
        session_id: str,
        role: MessageRole,
        content: str,
        mcp_tool_call_ids: list[str] | None = None,
        ui_cards: list[dict[str, Any]] | None = None,
        ui_actions: list[dict[str, Any]] | None = None,
    ) -> ChatMessageResult:
        return self._repository.append_message(
            session_id=session_id,
            role=role,
            content=content,
            mcp_tool_call_ids=mcp_tool_call_ids or [],
            ui_cards=ui_cards or [],
            ui_actions=ui_actions or [],
        )

    def _record_llm_run(
        self,
        *,
        chat_type: ChatType,
        message: str,
        user_id: str,
        tool_results: list[AgentToolExecutionResult],
        job_id: str,
        session_id: str,
    ) -> LlmRunResult:
        return self._llmops_service.run_agent_completion(
            chat_type=chat_type,
            message=message,
            user_id=user_id,
            tool_results=tool_results,
            job_id=job_id,
            session_id=session_id,
        )

    def _attach_llm_run_to_tool_calls(
        self,
        *,
        job_id: str,
        session_id: str,
        llm_run_id: str,
    ) -> None:
        try:
            self._repository.attach_llm_run_to_tool_calls(
                job_id=job_id,
                session_id=session_id,
                llm_run_id=llm_run_id,
            )
        except Exception:
            logger.exception(
                "Failed to link MCP tool calls to LLM run "
                "for job_id=%s session_id=%s llm_run_id=%s.",
                job_id,
                session_id,
                llm_run_id,
            )

    def _create_approval_requests(
        self,
        *,
        user_id: str,
        tool_results: list[AgentToolExecutionResult],
    ) -> None:
        for tool_result in tool_results:
            if not tool_result.requires_approval:
                continue
            try:
                self._llmops_service.create_approval_for_tool_result(
                    tool_result=tool_result,
                    requester_id=user_id,
                )
            except Exception:
                logger.exception(
                    "Failed to create approval request for %s.",
                    tool_result.tool_name,
                )

    def _create_agent_snapshot(
        self,
        *,
        chat_type: ChatType,
        job_id: str,
        session_id: str,
        llm_run: LlmRunResult,
        tool_results: list[AgentToolExecutionResult],
    ) -> None:
        try:
            self._llmops_service.create_agent_snapshot(
                snapshot_type=chat_type,
                job_id=job_id,
                session_id=session_id,
                llm_run_id=llm_run.llm_run_id,
                payload={
                    "llm_run_id": llm_run.llm_run_id,
                    "tool_call_ids": [
                        tool_result.tool_call_id
                        for tool_result in tool_results
                        if tool_result.tool_call_id is not None
                    ],
                },
            )
        except Exception:
            logger.exception("Failed to create agent snapshot for job %s.", job_id)

    def _create_job(
        self,
        *,
        job_type: str,
        entity_type: str,
        entity_id: str,
        status: JobStatus = "QUEUED",
    ) -> JobResult:
        return self._repository.create_job(
            job_type=job_type,
            status=status,
            entity_type=entity_type,
            entity_id=entity_id,
        )

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

    def _persist_agent_tool_result(
        self,
        *,
        tool_result: AgentToolExecutionResult,
        job_id: str,
        session_id: str,
    ) -> AgentToolExecutionResult:
        tool_call = self._record_tool_call(
            server_name=tool_result.server_name,
            tool_name=tool_result.tool_name,
            request_payload=tool_result.request_payload,
            response_payload=tool_result.response_payload,
            call_status=McpToolCallStatus(tool_result.call_status),
            job_id=job_id,
            session_id=session_id,
            last_error=tool_result.error_message,
        )
        return tool_result.model_copy(
            update={
                "tool_call_id": tool_call.tool_call_id,
                "masked_request_payload": tool_call.masked_request_payload,
                "masked_response_payload": tool_call.masked_response_payload,
            }
        )

    def _finish_job(
        self,
        job_id: str,
        tool_results: list[AgentToolExecutionResult],
        error_message: str | None = None,
    ) -> JobResult:
        job = self.get_job(job_id)
        has_failed_tool = any(
            McpToolCallStatus(result.call_status) == McpToolCallStatus.FAILED
            for result in tool_results
        )
        resolved_error_message = error_message
        if resolved_error_message is None and has_failed_tool:
            resolved_error_message = "One or more MCP tool executions failed."
        finished_job = self._repository.finish_job(
            job_id=job.job_id,
            status="FAILED" if has_failed_tool or error_message else "SUCCEEDED",
            error_message=resolved_error_message,
        )
        if finished_job is None:
            raise OrchestrationNotFoundError("job was not found.")
        return finished_job

    def _record_tool_call(
        self,
        *,
        server_name: str,
        tool_name: str,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any] | list[Any] | None,
        call_status: McpToolCallStatus,
        job_id: str,
        session_id: str,
        last_error: str | None = None,
    ) -> McpToolCallResult:
        tool = resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        return self._repository.record_tool_call(
            server_name=tool.server_name,
            tool_name=tool.tool_name,
            tool_permission=McpToolPermission(tool.tool_permission),
            call_status=call_status,
            request_payload=request_payload,
            response_payload=response_payload,
            latency_ms=0,
            job_id=job_id,
            session_id=session_id,
            last_error=last_error,
        )

    def _touch_session(self, session_id: str) -> None:
        self._repository.touch_chat_session(session_id)


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


def normalize_optional_job_status(value: str | None) -> JobStatus | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if normalized not in get_args(JobStatus):
        raise OrchestrationValidationError("job status is invalid.")
    return normalized


def normalize_optional_chat_status(value: str | None) -> ChatStatus | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if not normalized:
        return None
    if normalized not in get_args(ChatStatus):
        raise OrchestrationValidationError("chat session status is invalid.")
    return normalized


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def build_session_title(message: str) -> str:
    normalized = " ".join(message.split())
    if len(normalized) <= 80:
        return normalized
    return f"{normalized[:77]}..."


def build_chat_ui_cards(
    chat_type: ChatType,
    message: str,
    tool_results: list[AgentToolExecutionResult],
) -> list[dict[str, Any]]:
    if chat_type != "farmer_bnpl":
        return []

    normalized_message = message.lower()
    wants_credit = message_has_any(
        normalized_message,
        ("외상", "잔액", "한도", "결제", "구매", "limit", "credit", "bnpl", "checkout", "buy"),
    )
    wants_repayment = message_has_any(
        normalized_message,
        ("상환", "연체", "이자", "납부", "repayment", "overdue", "interest", "pay"),
    )
    wants_delivery = message_has_any(
        normalized_message,
        ("배송", "주문", "delivery", "order"),
    )
    wants_recommendation = message_has_any(
        normalized_message,
        (
            "비료",
            "추천",
            "농자재",
            "센서",
            "스마트팜",
            "fertilizer",
            "recommend",
            "sensor",
            "product",
        ),
    )

    cards: list[dict[str, Any]] = []
    for result in tool_results:
        if McpToolCallStatus(result.call_status) != McpToolCallStatus.SUCCESS:
            continue
        payload = result.response_payload if isinstance(result.response_payload, dict) else {}
        if result.tool_name == "get_user_credit_limit" and (
            wants_credit or wants_recommendation
        ):
            cards.append(build_credit_summary_card(payload))
        elif wants_repayment and result.tool_name in {
            "get_repayment_schedule",
            "get_interest_due",
            "get_overdue_status",
        }:
            repayment_card = build_repayment_summary_card(tool_results)
            if repayment_card and not has_card_type(cards, "repayment-summary"):
                cards.append(repayment_card)
        elif result.tool_name == "get_latest_order_delivery_status" and wants_delivery:
            cards.append(build_delivery_status_card(payload))
        elif wants_recommendation and result.tool_name in {
            "search_lowest_price_fertilizer",
            "search_products",
        }:
            recommendation_card = build_recommendation_card(payload)
            if recommendation_card is not None:
                cards.append(recommendation_card)
        elif result.tool_name == "prepare_bnpl_checkout_payload" and (
            wants_credit or wants_recommendation
        ):
            checkout_card = build_checkout_confirmation_card(payload)
            if checkout_card is not None:
                cards.append(checkout_card)
    return [card for card in cards if card]


def build_chat_ui_actions(ui_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        card["action"]
        for card in ui_cards
        if isinstance(card.get("action"), dict)
    ]


def build_credit_summary_card(payload: dict[str, Any]) -> dict[str, Any]:
    total_limit = int(payload.get("total_limit") or 0)
    used_amount = int(payload.get("used_amount") or 0)
    remaining = int(payload.get("available_limit") or max(total_limit - used_amount, 0))
    return {
        "type": "credit-summary",
        "limit": total_limit,
        "used": used_amount,
        "remaining": remaining,
        "currency": payload.get("currency") or "KRW",
        "action": {"label": "상환하러 가기", "route": "/wallet"},
    }


def build_repayment_summary_card(
    tool_results: list[AgentToolExecutionResult],
) -> dict[str, Any] | None:
    schedule_payload = find_tool_payload(tool_results, "get_repayment_schedule")
    interest_payload = find_tool_payload(tool_results, "get_interest_due")
    overdue_payload = find_tool_payload(tool_results, "get_overdue_status")
    if not schedule_payload and not interest_payload and not overdue_payload:
        return None

    schedule = schedule_payload.get("schedule") if schedule_payload else []
    upcoming = next(
        (
            item
            for item in schedule
            if isinstance(item, dict) and item.get("status") != "PAID"
        ),
        {},
    )
    return {
        "type": "repayment-summary",
        "next_due_date": upcoming.get("due_date") or interest_payload.get("due_date"),
        "principal_due": int(upcoming.get("principal_due") or 0),
        "interest_due": int(
            interest_payload.get("interest_due") or upcoming.get("interest_due") or 0
        ),
        "is_overdue": bool(overdue_payload.get("is_overdue", False)),
        "overdue_amount": int(overdue_payload.get("overdue_amount") or 0),
        "days_overdue": int(overdue_payload.get("days_overdue") or 0),
        "currency": (
            schedule_payload.get("currency")
            or interest_payload.get("currency")
            or overdue_payload.get("currency")
            or "KRW"
        ),
        "action": {"label": "상환하러 가기", "route": "/wallet"},
    }


def build_delivery_status_card(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "delivery-status",
        "order_id": payload.get("order_id"),
        "item_name": payload.get("item_name") or "최근 주문",
        "delivery_status": payload.get("delivery_status") or "UNKNOWN",
        "ordered_at": payload.get("ordered_at"),
        "action": {"label": "주문 내역 보기", "route": "/history"},
    }


def build_recommendation_card(payload: dict[str, Any]) -> dict[str, Any] | None:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    product = items[0]
    if not isinstance(product, dict):
        return None
    return {
        "type": "recommendation",
        "product_id": product.get("product_id"),
        "product_name": product.get("name"),
        "price": int(product.get("unit_price") or 0),
        "currency": product.get("currency") or "KRW",
        "reason": "현재 한도와 요청 조건에 맞는 추천 상품입니다.",
        "action": {"label": "상점에서 보기", "route": "/shop"},
    }


def build_checkout_confirmation_card(payload: dict[str, Any]) -> dict[str, Any] | None:
    raw_checkout_intent_id = payload.get("checkout_intent_id")
    checkout_intent_id = (
        raw_checkout_intent_id.strip()
        if isinstance(raw_checkout_intent_id, str)
        else None
    )
    if not payload.get("eligible") or checkout_intent_id is None:
        return None
    return {
        "type": "checkout-confirmation",
        "checkout_intent_id": checkout_intent_id,
        "total_amount": int(payload.get("total_amount") or 0),
        "available_limit": int(payload.get("available_limit") or 0),
        "currency": payload.get("currency") or "KRW",
        "action": {"label": "외상 결제 준비하기", "route": "/cart"},
    }


def message_has_any(message: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in message for keyword in keywords)


def find_tool_payload(
    tool_results: list[AgentToolExecutionResult],
    tool_name: str,
) -> dict[str, Any]:
    for result in tool_results:
        if (
            result.tool_name == tool_name
            and McpToolCallStatus(result.call_status) == McpToolCallStatus.SUCCESS
            and isinstance(result.response_payload, dict)
        ):
            return result.response_payload
    return {}


def has_card_type(cards: list[dict[str, Any]], card_type: str) -> bool:
    return any(card.get("type") == card_type for card in cards)


def resolve_assistant_content(
    masked_output: dict[str, object],
    fallback_answer: str,
) -> str:
    if "answer" in masked_output:
        return str(masked_output["answer"])
    return fallback_answer


def current_timestamp() -> str:
    return datetime.now(UTC).isoformat()


def build_public_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"
