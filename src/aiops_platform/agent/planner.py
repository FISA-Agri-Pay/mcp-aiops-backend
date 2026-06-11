from __future__ import annotations

import re
from typing import Any, Literal, Protocol, get_args

from aiops_platform.agent.schemas import AgentPlanResult, AgentToolPlan
from aiops_platform.core.config import settings
from aiops_platform.llmops.client import (
    LlmClient,
    LlmCompletionRequest,
    create_llm_client,
)
from aiops_platform.mcp.registry import list_mcp_tools
from aiops_platform.mcp.schemas import McpToolPermission
from aiops_platform.orchestration.schemas import ChatType


class AgentPlanner(Protocol):
    provider_name: str

    def plan(self, *, chat_type: ChatType, message: str, user_id: str) -> AgentPlanResult:
        pass


class RuleBasedAgentPlanner:
    provider_name = "rule_based"

    def plan(self, *, chat_type: ChatType, message: str, user_id: str) -> AgentPlanResult:
        normalized_message = message.lower()
        if chat_type == "farmer_bnpl":
            intent = classify_farmer_bnpl_intent(normalized_message)
            capability = classify_farmer_bnpl_capability(normalized_message)
            tool_plans = plan_farmer_bnpl_tools(
                message=normalized_message,
                user_id=user_id,
            )
        else:
            intent = classify_admin_copilot_intent(normalized_message)
            capability = classify_admin_copilot_capability(normalized_message)
            tool_plans = plan_admin_copilot_tools(
                message=normalized_message,
                capability=capability,
            )
        return AgentPlanResult(
            provider_name="rule_based",
            chat_type=chat_type,
            tool_plans=deduplicate_tool_plans(tool_plans),
            intent=intent,
            capability=capability,
            direct_answer=build_direct_answer(chat_type=chat_type, intent=intent),
        )


class LlmAgentPlanner:
    provider_name = "llm"

    def __init__(
        self,
        *,
        llm_client: LlmClient | None = None,
        fallback_planner: AgentPlanner | None = None,
    ) -> None:
        self._llm_client = llm_client or create_llm_client(settings)
        self._fallback_planner = fallback_planner or RuleBasedAgentPlanner()

    def plan(self, *, chat_type: ChatType, message: str, user_id: str) -> AgentPlanResult:
        fallback = self._fallback_planner.plan(
            chat_type=chat_type,
            message=message,
            user_id=user_id,
        )
        try:
            response = self._llm_client.complete(
                LlmCompletionRequest(
                    chat_type=chat_type,
                    prompt_key=f"{chat_type}_tool_planner",
                    prompt_template=build_llm_planner_prompt(),
                    input_payload={
                        "chat_type": chat_type,
                        "message": message,
                        "user_id": user_id,
                        "available_tools": available_tools_for_prompt(chat_type),
                        "available_capabilities": available_capabilities_for_prompt(chat_type),
                    },
                    output_schema={
                        "type": "object",
                        "required": ["intent", "capability", "requires_tools", "tool_plans"],
                    },
                )
            )
            return build_validated_llm_plan(
                chat_type=chat_type,
                message=message,
                user_id=user_id,
                payload=response.output_payload,
                fallback=fallback,
            )
        except Exception as exc:
            return fallback.model_copy(
                update={
                    "provider_name": "llm_with_rule_fallback",
                    "planner_error": format_planner_error(exc),
                }
            )


AdminCopilotIntent = Literal[
    "greeting",
    "thanks",
    "help",
    "unsupported",
    "overdue_risk",
    "credit_review",
    "infra_scaling",
    "disaster_risk",
    "snapshot",
    "bnpl_summary",
    "risk_overview",
    "action_priority",
]
AdminCopilotCapability = Literal[
    "smalltalk",
    "help",
    "unsupported",
    "bnpl_portfolio_status",
    "overdue_risk_triage",
    "credit_review_workload",
    "infra_scaling_health",
    "disaster_credit_impact",
    "evidence_snapshot",
    "risk_overview",
    "ops_action_prioritization",
]
FarmerBnplIntent = Literal[
    "greeting",
    "thanks",
    "help",
    "unsupported",
    "credit_limit",
    "repayment",
    "delivery",
    "recommendation",
    "checkout_prepare",
    "checkout_confirm",
    "application",
    "general_bnpl",
]
FarmerBnplCapability = Literal[
    "smalltalk",
    "help",
    "unsupported",
    "credit_limit_status",
    "repayment_guidance",
    "delivery_status",
    "fertilizer_recommendation",
    "checkout_guidance",
    "credit_application_guidance",
    "bnpl_general_guidance",
]
ADMIN_COPILOT_CAPABILITY_VALUES = set(get_args(AdminCopilotCapability))
ADMIN_DIRECT_CAPABILITIES = {"smalltalk", "help", "unsupported"}
FARMER_BNPL_CAPABILITY_VALUES = set(get_args(FarmerBnplCapability))
FARMER_INTENT_TO_CAPABILITY: dict[str, FarmerBnplCapability] = {
    "greeting": "smalltalk",
    "thanks": "smalltalk",
    "help": "help",
    "unsupported": "unsupported",
    "credit_limit": "credit_limit_status",
    "repayment": "repayment_guidance",
    "delivery": "delivery_status",
    "recommendation": "fertilizer_recommendation",
    "checkout_prepare": "checkout_guidance",
    "checkout_confirm": "checkout_guidance",
    "application": "credit_application_guidance",
    "general_bnpl": "bnpl_general_guidance",
}
FARMER_CAPABILITY_TO_INTENT: dict[str, FarmerBnplIntent] = {
    "smalltalk": "greeting",
    "help": "help",
    "unsupported": "unsupported",
    "credit_limit_status": "credit_limit",
    "repayment_guidance": "repayment",
    "delivery_status": "delivery",
    "fertilizer_recommendation": "recommendation",
    "checkout_guidance": "checkout_prepare",
    "credit_application_guidance": "application",
    "bnpl_general_guidance": "general_bnpl",
}
ADMIN_INTENT_TO_CAPABILITY: dict[str, AdminCopilotCapability] = {
    "greeting": "smalltalk",
    "thanks": "smalltalk",
    "help": "help",
    "unsupported": "unsupported",
    "overdue_risk": "overdue_risk_triage",
    "credit_review": "credit_review_workload",
    "infra_scaling": "infra_scaling_health",
    "disaster_risk": "disaster_credit_impact",
    "snapshot": "evidence_snapshot",
    "bnpl_summary": "bnpl_portfolio_status",
    "risk_overview": "risk_overview",
    "action_priority": "ops_action_prioritization",
}
ADMIN_CAPABILITY_TO_INTENT: dict[str, AdminCopilotIntent] = {
    "smalltalk": "greeting",
    "help": "help",
    "unsupported": "unsupported",
    "bnpl_portfolio_status": "bnpl_summary",
    "overdue_risk_triage": "overdue_risk",
    "credit_review_workload": "credit_review",
    "infra_scaling_health": "infra_scaling",
    "disaster_credit_impact": "disaster_risk",
    "evidence_snapshot": "snapshot",
    "risk_overview": "risk_overview",
    "ops_action_prioritization": "action_priority",
}


def plan_farmer_bnpl_tools(*, message: str, user_id: str) -> list[AgentToolPlan]:
    intent = classify_farmer_bnpl_intent(message)
    if intent in {"greeting", "thanks", "help", "unsupported"}:
        return []

    plans: list[AgentToolPlan] = []

    if intent in {
        "credit_limit",
        "checkout_prepare",
        "recommendation",
        "application",
        "general_bnpl",
    }:
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="get_user_credit_limit",
                request_payload={"user_id": user_id},
                reason="Check available BNPL limit for the farmer request.",
            )
        )

    if intent in {"recommendation", "application", "general_bnpl"}:
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="get_farmer_profile",
                request_payload={"user_id": user_id},
                reason="Use farmer profile context for personalized guidance.",
            )
        )

    if intent == "application":
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="get_required_documents",
                request_payload={"user_id": user_id},
                reason="Show required documents for the BNPL application flow.",
            )
        )

    if intent == "repayment":
        plans.extend(
            [
                AgentToolPlan(
                    server_name="farmer-bnpl-mcp",
                    tool_name="get_repayment_schedule",
                    request_payload={"user_id": user_id},
                    reason="Read upcoming repayment schedule.",
                ),
                AgentToolPlan(
                    server_name="farmer-bnpl-mcp",
                    tool_name="get_interest_due",
                    request_payload={"user_id": user_id},
                    reason="Read next interest due amount.",
                ),
                AgentToolPlan(
                    server_name="farmer-bnpl-mcp",
                    tool_name="get_overdue_status",
                    request_payload={"user_id": user_id},
                    reason="Check whether the user has overdue BNPL balance.",
                ),
            ]
        )

    if intent == "delivery":
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="get_latest_order_delivery_status",
                request_payload={"user_id": user_id},
                reason="Read latest order delivery status for the farmer.",
            )
        )

    if intent == "recommendation" and any(
        keyword in message for keyword in ("sensor", "센서", "스마트팜", "smartfarm", "smart farm")
    ):
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="search_products",
                request_payload={"query": "sensor", "limit": 3},
                reason="Find smart farm sensor product candidates.",
            )
        )

    if intent in {"recommendation", "checkout_prepare"}:
        default_cart_items = [
            {
                "product_id": str(settings.farmer_bnpl_default_checkout_product_id),
                "quantity": settings.farmer_bnpl_default_checkout_quantity,
            }
        ]
        plans.extend(
            [
                AgentToolPlan(
                    server_name="farm-advisory-mcp",
                    tool_name="recommend_fertilizer_requirements",
                    request_payload={"crop_type": "rice", "area_hectare": 1.2},
                    reason="Estimate fertilizer requirement from crop and area defaults.",
                ),
                AgentToolPlan(
                    server_name="farmer-bnpl-mcp",
                    tool_name="search_lowest_price_fertilizer",
                    request_payload={"limit": 3},
                    reason="Find low-price fertilizer candidates.",
                ),
                AgentToolPlan(
                    server_name="farmer-bnpl-mcp",
                    tool_name="prepare_bnpl_checkout_payload",
                    request_payload={"user_id": user_id, "items": default_cart_items},
                    reason="Prepare a dry-run BNPL checkout eligibility payload.",
                ),
            ]
        )

    if intent == "checkout_confirm":
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="create_bnpl_checkout",
                request_payload={
                    "user_id": user_id,
                    "checkout_intent_id": "checkout-intent-preview",
                },
                reason="Create checkout requires explicit user confirmation.",
            )
        )

    return plans


def classify_farmer_bnpl_intent(message: str) -> FarmerBnplIntent:
    normalized = " ".join(message.lower().split())
    compact = normalized.replace(" ", "")
    if not normalized:
        return "help"

    farmer_keywords = (
        "bnpl",
        "외상",
        "한도",
        "잔액",
        "상환",
        "이자",
        "연체",
        "배송",
        "주문",
        "비료",
        "농자재",
        "센서",
        "스마트팜",
        "결제",
        "구매",
        "checkout",
        "서류",
        "신청",
        "심사",
        "credit",
        "limit",
        "repayment",
        "interest",
        "overdue",
        "delivery",
        "order",
        "fertilizer",
        "product",
        "recommend",
    )
    greeting_keywords = ("안녕", "안녕하세요", "하이", "hello", "hi", "hey")
    if compact in greeting_keywords or (
        any(compact.startswith(keyword) for keyword in greeting_keywords)
        and not any(keyword in normalized for keyword in farmer_keywords)
    ):
        return "greeting"

    thanks_keywords = ("고마워", "감사", "thanks", "thank you", "thx")
    if any(keyword in normalized for keyword in thanks_keywords) and not any(
        keyword in normalized for keyword in farmer_keywords
    ):
        return "thanks"

    help_keywords = ("도움말", "사용법", "뭐 할 수", "무엇을 할 수", "기능", "help")
    if any(keyword in normalized for keyword in help_keywords):
        return "help"

    if any(keyword in normalized for keyword in ("confirm checkout", "checkout 생성", "구매 확정")):
        return "checkout_confirm"
    if any(
        keyword in normalized
        for keyword in ("repayment", "상환", "interest", "이자", "overdue", "연체", "납부")
    ):
        return "repayment"
    if any(keyword in normalized for keyword in ("delivery", "배송", "주문", "order")):
        return "delivery"
    if any(keyword in normalized for keyword in ("document", "서류", "신청", "심사")):
        return "application"
    if any(
        keyword in normalized
        for keyword in (
            "fertilizer",
            "비료",
            "product",
            "농자재",
            "센서",
            "스마트팜",
            "smartfarm",
            "smart farm",
            "추천",
            "recommend",
        )
    ):
        return "recommendation"
    if any(keyword in normalized for keyword in ("checkout", "결제", "구매", "cart", "장바구니")):
        return "checkout_prepare"
    if any(keyword in normalized for keyword in ("한도", "잔액", "limit", "credit", "외상 가능")):
        return "credit_limit"
    if any(keyword in normalized for keyword in ("bnpl", "외상", "외상결제")):
        return "general_bnpl"
    return "unsupported"


def plan_admin_copilot_tools(
    *,
    message: str,
    capability: AdminCopilotCapability | None = None,
) -> list[AgentToolPlan]:
    resolved_capability = capability or classify_admin_copilot_capability(message)
    if resolved_capability in ADMIN_DIRECT_CAPABILITIES:
        return []

    review_limit = extract_requested_limit(message, default=10)
    plans: list[AgentToolPlan] = []

    if resolved_capability in {
        "bnpl_portfolio_status",
        "risk_overview",
        "ops_action_prioritization",
    }:
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="get_bnpl_summary",
                request_payload={},
                reason="Summarize portfolio-level BNPL exposure.",
            )
        )

    if resolved_capability in {
        "credit_review_workload",
        "risk_overview",
        "ops_action_prioritization",
    }:
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="get_credit_review_queue",
                request_payload={"limit": review_limit},
                reason="Read pending credit review workload.",
            )
        )

    if resolved_capability in {
        "infra_scaling_health",
        "risk_overview",
        "ops_action_prioritization",
    }:
        plans.extend(
            [
                AgentToolPlan(
                    server_name="infraops-mcp",
                    tool_name="query_multi_cluster_prometheus",
                    request_payload={"query": "up"},
                    reason="Attach safe multi-cluster observability context.",
                ),
                AgentToolPlan(
                    server_name="prediction-scaling-mcp",
                    tool_name="get_scaling_summary",
                    request_payload={},
                    reason="Summarize prediction-aware scaling evidence.",
                ),
            ]
        )

    if resolved_capability in {
        "overdue_risk_triage",
        "risk_overview",
        "ops_action_prioritization",
    }:
        plans.extend(
            [
                AgentToolPlan(
                    server_name="admin-riskops-mcp",
                    tool_name="get_overdue_summary",
                    request_payload={},
                    reason="Summarize overdue BNPL exposure.",
                ),
                AgentToolPlan(
                    server_name="admin-riskops-mcp",
                    tool_name="search_overdue_users",
                    request_payload={"min_days_overdue": 1, "limit": 10},
                    reason="List overdue users for admin triage.",
                ),
            ]
        )

    user_keywords = ("user", "users", "customer", "고객", "사용자", "농가")
    if resolved_capability in {"overdue_risk_triage", "bnpl_portfolio_status"} and any(
        keyword in message for keyword in user_keywords
    ):
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="search_bnpl_users",
                request_payload={"limit": 10},
                reason="List BNPL users for admin triage.",
            )
        )

    if resolved_capability == "disaster_credit_impact":
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="simulate_disaster_credit_risk",
                request_payload={
                    "region": "gangwon",
                    "disaster_type": "flood",
                    "affected_crop": None,
                },
                reason="Preview disaster-driven BNPL credit risk.",
            )
        )

    if resolved_capability == "evidence_snapshot":
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="create_risk_analysis_snapshot",
                request_payload={"target_type": "PORTFOLIO", "target_id": "portfolio"},
                reason="Create a read-only RiskOps evidence snapshot.",
            )
        )

    return plans


def classify_admin_copilot_intent(message: str) -> AdminCopilotIntent:
    normalized = " ".join(message.lower().split())
    compact = normalized.replace(" ", "")
    if not normalized:
        return "help"

    admin_keywords = (
        "bnpl",
        "risk",
        "위험",
        "리스크",
        "심사",
        "연체",
        "스케일",
        "scaling",
        "infra",
        "인프라",
        "운영",
        "고객",
        "사용자",
        "농가",
        "한도",
        "재해",
        "snapshot",
        "스냅샷",
        "근거",
        "action",
        "액션",
        "조치",
        "우선순위",
        "우선 순위",
        "priority",
    )
    greeting_keywords = ("안녕", "안녕하세요", "하이", "hello", "hi", "hey")
    if compact in greeting_keywords or (
        any(compact.startswith(keyword) for keyword in greeting_keywords)
        and not any(keyword in normalized for keyword in admin_keywords)
    ):
        return "greeting"

    thanks_keywords = ("고마워", "감사", "thanks", "thank you", "thx")
    if any(keyword in normalized for keyword in thanks_keywords) and not any(
        keyword in normalized for keyword in admin_keywords
    ):
        return "thanks"

    help_keywords = ("도움말", "사용법", "뭐 할 수", "무엇을 할 수", "기능", "help")
    if any(keyword in normalized for keyword in help_keywords):
        return "help"

    unsupported_keywords = (
        "이상 주문",
        "주문 이상",
        "주문 분석",
        "anomaly order",
        "order anomaly",
        "fraud order",
        "부정 주문",
    )
    if any(keyword in normalized for keyword in unsupported_keywords):
        return "unsupported"

    if any(
        keyword in normalized
        for keyword in (
            "action",
            "액션",
            "조치",
            "해야 할 일",
            "할 일",
            "우선순위",
            "우선 순위",
            "priority",
            "recommendation",
            "권장",
        )
    ):
        return "action_priority"

    has_risk_keyword = any(keyword in normalized for keyword in ("risk", "위험", "리스크"))
    has_scaling_keyword = any(
        keyword in normalized
        for keyword in ("scaling", "스케일", "인프라", "infra", "운영", "status", "상태")
    )
    if has_risk_keyword and has_scaling_keyword:
        return "risk_overview"

    if any(keyword in normalized for keyword in ("overdue", "연체", "미납")):
        return "overdue_risk"
    if any(keyword in normalized for keyword in ("review", "심사", "신용", "승인", "대기")):
        return "credit_review"
    if any(
        keyword in normalized
        for keyword in (
            "scaling",
            "스케일",
            "인프라",
            "infra",
            "cluster",
            "클러스터",
            "pod",
            "파드",
            "부하",
            "장애",
            "prometheus",
        )
    ):
        return "infra_scaling"
    if any(keyword in normalized for keyword in ("disaster", "재해", "홍수", "가뭄", "폭염")):
        return "disaster_risk"
    if any(keyword in normalized for keyword in ("snapshot", "스냅샷", "근거")):
        return "snapshot"
    if any(
        keyword in normalized
        for keyword in ("bnpl", "이용 현황", "사용 현황", "활성", "한도", "포트폴리오")
    ):
        return "bnpl_summary"
    if any(keyword in normalized for keyword in ("risk", "위험", "리스크", "현황", "요약")):
        return "risk_overview"
    return "unsupported"


def classify_admin_copilot_capability(message: str) -> AdminCopilotCapability:
    intent = classify_admin_copilot_intent(message)
    return ADMIN_INTENT_TO_CAPABILITY[intent]


def classify_farmer_bnpl_capability(message: str) -> FarmerBnplCapability:
    intent = classify_farmer_bnpl_intent(message)
    return FARMER_INTENT_TO_CAPABILITY[intent]


def normalize_farmer_capability(value: object) -> FarmerBnplCapability | None:
    normalized = normalize_optional_string(value)
    if normalized is None:
        return None
    normalized = normalized.lower().replace("-", "_")
    if normalized in FARMER_BNPL_CAPABILITY_VALUES:
        return normalized  # type: ignore[return-value]
    return None


def farmer_intent_for_capability(
    *,
    capability: FarmerBnplCapability,
    fallback_intent: str | None = None,
) -> FarmerBnplIntent:
    if capability == "smalltalk" and fallback_intent in {"greeting", "thanks"}:
        return fallback_intent  # type: ignore[return-value]
    return FARMER_CAPABILITY_TO_INTENT[capability]


def normalize_admin_capability(value: object) -> AdminCopilotCapability | None:
    normalized = normalize_optional_string(value)
    if normalized is None:
        return None
    normalized = normalized.lower().replace("-", "_")
    if normalized in ADMIN_COPILOT_CAPABILITY_VALUES:
        return normalized  # type: ignore[return-value]
    return None


def admin_intent_for_capability(
    *,
    capability: AdminCopilotCapability,
    fallback_intent: str | None = None,
) -> AdminCopilotIntent:
    if capability == "smalltalk" and fallback_intent in {"greeting", "thanks"}:
        return fallback_intent  # type: ignore[return-value]
    return ADMIN_CAPABILITY_TO_INTENT[capability]


def build_llm_planner_prompt() -> str:
    return (
        "You are a tool-planning layer for a Korean AIOps BNPL chatbot. "
        "Return only JSON. Decide whether the user needs MCP tools or a direct chat answer. "
        "Use only tools listed in available_tools and capabilities listed in "
        "available_capabilities. "
        "Do not invent tools or capabilities. "
        "For admin_copilot, choose one capability first. Admin requests for action priority, "
        "next actions, recommendations, or operational triage are ops_action_prioritization. "
        "The backend maps admin capabilities to approved MCP tool bundles, so admin data requests "
        "may set tool_plans=[] as long as capability is correct and requires_tools=true. "
        "For farmer_bnpl, choose the capability that matches the user's main need. "
        "Fertilizer or product recommendation requests are fertilizer_recommendation, "
        "and credit limit questions are credit_limit_status. "
        "For greeting, thanks, help, or unsupported requests, set requires_tools=false, "
        "tool_plans=[], and provide a Korean direct_answer. "
        "For supported data requests, set requires_tools=true and provide the minimal tool_plans. "
        "Each tool plan must include server_name, tool_name, request_payload, and reason. "
        "Keep request_payload minimal; backend will fill safe defaults such as user_id. "
        "If requested analysis is unsupported by available_tools, do not choose adjacent tools."
    )


def available_capabilities_for_prompt(chat_type: ChatType) -> list[dict[str, str]]:
    if chat_type == "farmer_bnpl":
        return [
            {
                "capability": "smalltalk",
                "description": "Greeting or thanks that does not require account data.",
            },
            {
                "capability": "help",
                "description": "Explain what the farmer chatbot can answer.",
            },
            {
                "capability": "unsupported",
                "description": "The user request has no supported farmer-facing data source.",
            },
            {
                "capability": "credit_limit_status",
                "description": (
                    "Current BNPL credit limit, used amount, available limit, and status."
                ),
            },
            {
                "capability": "repayment_guidance",
                "description": (
                    "Repayment schedule, interest due, overdue status, and payment guidance."
                ),
            },
            {
                "capability": "delivery_status",
                "description": "Latest order and delivery status.",
            },
            {
                "capability": "fertilizer_recommendation",
                "description": (
                    "Fertilizer or farming material recommendation using profile, "
                    "advisory, product, and BNPL eligibility evidence."
                ),
            },
            {
                "capability": "checkout_guidance",
                "description": "Prepare or confirm BNPL checkout with user confirmation policy.",
            },
            {
                "capability": "credit_application_guidance",
                "description": "Credit application, required documents, and review guidance.",
            },
            {
                "capability": "bnpl_general_guidance",
                "description": "General farmer-facing BNPL usage guidance.",
            },
        ]
    if chat_type != "admin_copilot":
        return []
    return [
        {
            "capability": "smalltalk",
            "description": "Greeting or thanks that does not require operational data.",
        },
        {
            "capability": "help",
            "description": "Explain what the Admin Copilot can answer.",
        },
        {
            "capability": "unsupported",
            "description": "The requested analysis has no supported MCP data source.",
        },
        {
            "capability": "bnpl_portfolio_status",
            "description": "BNPL usage, active users, limits, exposure, and portfolio status.",
        },
        {
            "capability": "overdue_risk_triage",
            "description": "Overdue users, overdue amount, delinquency status, and risk triage.",
        },
        {
            "capability": "credit_review_workload",
            "description": (
                "Pending credit review queue, approval workload, and review bottlenecks."
            ),
        },
        {
            "capability": "infra_scaling_health",
            "description": "Cluster observability, scaling summary, pods, load, and infra health.",
        },
        {
            "capability": "disaster_credit_impact",
            "description": "Weather or disaster impact simulation for BNPL credit risk.",
        },
        {
            "capability": "evidence_snapshot",
            "description": "Create a read-only RiskOps evidence snapshot.",
        },
        {
            "capability": "risk_overview",
            "description": (
                "Cross-domain risk summary combining BNPL, overdue, review, and infra evidence."
            ),
        },
        {
            "capability": "ops_action_prioritization",
            "description": (
                "Rank admin next actions using BNPL, overdue, credit review, and scaling evidence."
            ),
        },
    ]


def available_tools_for_prompt(chat_type: ChatType) -> list[dict[str, str]]:
    allowed = allowed_tool_keys(chat_type)
    tools = []
    for tool in list_mcp_tools():
        key = (tool.server_name, tool.tool_name)
        if key not in allowed:
            continue
        tools.append(
            {
                "server_name": tool.server_name,
                "tool_name": tool.tool_name,
                "permission": str(tool.tool_permission),
            }
        )
    return tools


def allowed_tool_keys(chat_type: ChatType) -> set[tuple[str, str]]:
    if chat_type == "farmer_bnpl":
        return {
            ("farmer-bnpl-mcp", "get_required_documents"),
            ("farmer-bnpl-mcp", "get_user_credit_limit"),
            ("farmer-bnpl-mcp", "get_farmer_profile"),
            ("farmer-bnpl-mcp", "get_repayment_schedule"),
            ("farmer-bnpl-mcp", "get_interest_due"),
            ("farmer-bnpl-mcp", "get_overdue_status"),
            ("farmer-bnpl-mcp", "get_latest_order_delivery_status"),
            ("farmer-bnpl-mcp", "search_products"),
            ("farmer-bnpl-mcp", "search_lowest_price_fertilizer"),
            ("farmer-bnpl-mcp", "prepare_bnpl_checkout_payload"),
            ("farmer-bnpl-mcp", "create_bnpl_checkout"),
            ("farm-advisory-mcp", "recommend_fertilizer_requirements"),
        }
    return {
        ("admin-riskops-mcp", "get_credit_review_queue"),
        ("admin-riskops-mcp", "get_credit_review_detail"),
        ("admin-riskops-mcp", "summarize_credit_risk"),
        ("admin-riskops-mcp", "get_bnpl_summary"),
        ("admin-riskops-mcp", "search_bnpl_users"),
        ("admin-riskops-mcp", "get_overdue_summary"),
        ("admin-riskops-mcp", "search_overdue_users"),
        ("admin-riskops-mcp", "get_bss_score_history"),
        ("admin-riskops-mcp", "simulate_disaster_credit_risk"),
        ("admin-riskops-mcp", "create_risk_analysis_snapshot"),
        ("infraops-mcp", "query_multi_cluster_prometheus"),
        ("prediction-scaling-mcp", "get_scaling_summary"),
    }


def build_validated_llm_plan(
    *,
    chat_type: ChatType,
    message: str,
    user_id: str,
    payload: dict[str, Any],
    fallback: AgentPlanResult,
) -> AgentPlanResult:
    intent = normalize_optional_string(payload.get("intent")) or fallback.intent
    capability = normalize_optional_string(payload.get("capability")) or fallback.capability
    direct_answer = normalize_optional_string(payload.get("direct_answer"))
    requires_tools = parse_bool(payload.get("requires_tools"))
    raw_tool_plans = payload.get("tool_plans")

    if chat_type == "admin_copilot":
        llm_capability = normalize_admin_capability(payload.get("capability"))
        if llm_capability is not None and llm_capability not in ADMIN_DIRECT_CAPABILITIES:
            plans = deduplicate_tool_plans(
                plan_admin_copilot_tools(
                    message=message.lower(),
                    capability=llm_capability,
                )
            )
            if plans:
                return AgentPlanResult(
                    provider_name="llm",
                    chat_type=chat_type,
                    intent=admin_intent_for_capability(
                        capability=llm_capability,
                        fallback_intent=intent,
                    ),
                    capability=llm_capability,
                    tool_plans=plans,
                )
        if llm_capability is not None:
            capability = llm_capability
            intent = admin_intent_for_capability(
                capability=llm_capability,
                fallback_intent=intent,
            )
    elif chat_type == "farmer_bnpl":
        llm_capability = normalize_farmer_capability(payload.get("capability"))
        if llm_capability is not None:
            capability = llm_capability
            intent = farmer_intent_for_capability(
                capability=llm_capability,
                fallback_intent=intent,
            )

    if not requires_tools:
        if fallback.tool_plans:
            return fallback.model_copy(
                update={
                    "provider_name": "llm_with_rule_fallback",
                    "planner_error": "LLM planner skipped tools for a supported data request.",
                }
            )
        return AgentPlanResult(
            provider_name="llm",
            chat_type=chat_type,
            intent=intent,
            capability=capability,
            direct_answer=direct_answer
            or build_direct_answer(chat_type=chat_type, intent=str(intent or "")),
            tool_plans=[],
        )

    if not isinstance(raw_tool_plans, list):
        return fallback.model_copy(
            update={
                "provider_name": "llm_with_rule_fallback",
                "planner_error": "LLM planner tool_plans was not a list.",
            }
        )

    plans = []
    for item in raw_tool_plans:
        plan = validate_llm_tool_plan(
            chat_type=chat_type,
            message=message,
            user_id=user_id,
            raw_plan=item,
        )
        if plan is not None:
            plans.append(plan)

    plans = deduplicate_tool_plans(plans)
    if not plans:
        return fallback.model_copy(
            update={
                "provider_name": "llm_with_rule_fallback",
                "planner_error": "LLM planner did not produce valid tool plans.",
            }
        )
    return AgentPlanResult(
        provider_name="llm",
        chat_type=chat_type,
        intent=intent,
        capability=capability,
        tool_plans=plans,
    )


def validate_llm_tool_plan(
    *,
    chat_type: ChatType,
    message: str,
    user_id: str,
    raw_plan: object,
) -> AgentToolPlan | None:
    if not isinstance(raw_plan, dict):
        return None
    server_name = normalize_optional_string(raw_plan.get("server_name"))
    tool_name = normalize_optional_string(raw_plan.get("tool_name"))
    if server_name is None or tool_name is None:
        return None
    key = (server_name, tool_name)
    if key not in allowed_tool_keys(chat_type):
        return None
    tool = find_registered_tool(server_name=server_name, tool_name=tool_name)
    if tool is None:
        return None
    if (
        chat_type == "admin_copilot"
        and McpToolPermission(tool.tool_permission) != McpToolPermission.READ
    ):
        return None
    request_payload = raw_plan.get("request_payload")
    if not isinstance(request_payload, dict):
        request_payload = {}
    reason = (
        normalize_optional_string(raw_plan.get("reason"))
        or "LLM planner selected this MCP tool."
    )
    return AgentToolPlan(
        server_name=server_name,
        tool_name=tool_name,
        request_payload=normalize_tool_payload(
            server_name=server_name,
            tool_name=tool_name,
            message=message,
            user_id=user_id,
            payload=request_payload,
        ),
        reason=reason,
    )


def normalize_tool_payload(
    *,
    server_name: str,
    tool_name: str,
    message: str,
    user_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(payload)
    if server_name == "farmer-bnpl-mcp" and tool_name in {
        "get_required_documents",
        "get_user_credit_limit",
        "get_farmer_profile",
        "get_repayment_schedule",
        "get_interest_due",
        "get_overdue_status",
        "get_latest_order_delivery_status",
        "prepare_bnpl_checkout_payload",
        "create_bnpl_checkout",
    }:
        normalized["user_id"] = user_id
    if tool_name in {"get_credit_review_queue", "search_bnpl_users"}:
        normalized["limit"] = clamp_int(
            normalized.get("limit"),
            default=extract_requested_limit(message, default=10),
        )
    if tool_name == "search_overdue_users":
        normalized["min_days_overdue"] = clamp_int(normalized.get("min_days_overdue"), default=1)
        normalized["limit"] = clamp_int(normalized.get("limit"), default=10)
    if tool_name == "query_multi_cluster_prometheus":
        normalized["query"] = normalize_optional_string(normalized.get("query")) or "up"
    if tool_name == "simulate_disaster_credit_risk":
        normalized["region"] = normalize_optional_string(normalized.get("region")) or "gangwon"
        normalized["disaster_type"] = (
            normalize_optional_string(normalized.get("disaster_type")) or "flood"
        )
        normalized["affected_crop"] = normalize_optional_string(normalized.get("affected_crop"))
    if tool_name == "create_risk_analysis_snapshot":
        normalized["target_type"] = (
            normalize_optional_string(normalized.get("target_type")) or "PORTFOLIO"
        )
        normalized["target_id"] = (
            normalize_optional_string(normalized.get("target_id")) or "portfolio"
        )
    if tool_name == "search_products":
        normalized["query"] = normalize_optional_string(normalized.get("query")) or "sensor"
        normalized["limit"] = clamp_int(normalized.get("limit"), default=3)
    if tool_name == "search_lowest_price_fertilizer":
        normalized["limit"] = clamp_int(normalized.get("limit"), default=3)
    if tool_name == "recommend_fertilizer_requirements":
        normalized["crop_type"] = normalize_optional_string(normalized.get("crop_type")) or "rice"
        normalized["area_hectare"] = clamp_float(normalized.get("area_hectare"), default=1.2)
    if tool_name == "prepare_bnpl_checkout_payload":
        normalized["items"] = normalize_cart_items(normalized.get("items"))
    if tool_name == "create_bnpl_checkout":
        normalized["checkout_intent_id"] = (
            normalize_optional_string(normalized.get("checkout_intent_id"))
            or "checkout-intent-preview"
        )
    return normalized


def normalize_cart_items(value: object) -> list[dict[str, Any]]:
    if isinstance(value, list) and value:
        items = [item for item in value if isinstance(item, dict)]
        if items:
            return items
    return [
        {
            "product_id": str(settings.farmer_bnpl_default_checkout_product_id),
            "quantity": settings.farmer_bnpl_default_checkout_quantity,
        }
    ]


def find_registered_tool(*, server_name: str, tool_name: str):
    for tool in list_mcp_tools(server_name=server_name):
        if tool.tool_name == tool_name:
            return tool
    return None


def build_direct_answer(*, chat_type: ChatType, intent: str) -> str | None:
    if chat_type == "admin_copilot":
        return {
            "greeting": (
                "안녕하세요. BNPL 현황, 연체 위험 고객, 심사 대기 건, "
                "인프라/스케일링 상태를 도와드릴 수 있습니다."
            ),
            "thanks": "도움이 필요하면 언제든 BNPL 운영 현황이나 리스크 상태를 물어봐 주세요.",
            "help": (
                "BNPL 이용 현황, 연체 위험 고객, 심사 대기 건, "
                "인프라/스케일링 상태를 조회할 수 있습니다."
            ),
            "unsupported": (
                "현재 Admin Copilot에서 해당 분석에 필요한 운영 데이터를 조회할 수 없습니다. "
                "BNPL 현황, 연체 위험 고객, 심사 대기 건, "
                "인프라/스케일링 상태는 확인할 수 있습니다."
            ),
        }.get(intent)
    return {
        "greeting": (
            "안녕하세요. 외상 한도, 상환 일정, 배송 현황, "
            "농자재 추천을 도와드릴 수 있어요."
        ),
        "thanks": "언제든 외상 한도, 상환 일정, 배송 현황이 궁금하면 물어봐 주세요.",
        "help": (
            "외상 한도 확인, 상환/이자 일정, 연체 여부, 배송 현황, "
            "비료와 농자재 추천을 도와드릴 수 있어요."
        ),
        "unsupported": (
            "현재 이 챗봇에서는 외상 한도, 상환 일정, 배송 현황, "
            "농자재 추천과 결제 준비를 도와드릴 수 있어요."
        ),
    }.get(intent)


def normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def clamp_int(value: object, *, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return min(max(value, 1), 100)
    return default


def clamp_float(value: object, *, default: float) -> float:
    if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
        return float(value)
    return default


def format_planner_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    formatted = f"{exc.__class__.__name__}: {message}"
    if len(formatted) <= 500:
        return formatted
    return f"{formatted[:500]}..."


def deduplicate_tool_plans(tool_plans: list[AgentToolPlan]) -> list[AgentToolPlan]:
    seen = set()
    deduplicated = []
    for plan in tool_plans:
        key = (plan.server_name, plan.tool_name)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(plan)
    return deduplicated


def extract_requested_limit(message: str, *, default: int) -> int:
    match = re.search(r"\d+", message)
    if match is None:
        return default
    return min(max(int(match.group()), 1), 100)
