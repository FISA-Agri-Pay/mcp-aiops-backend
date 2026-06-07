from __future__ import annotations

import re
from typing import Protocol

from aiops_platform.agent.schemas import AgentPlanResult, AgentToolPlan
from aiops_platform.core.config import settings
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
            tool_plans = plan_farmer_bnpl_tools(
                message=normalized_message,
                user_id=user_id,
            )
        else:
            tool_plans = plan_admin_copilot_tools(message=normalized_message)
        return AgentPlanResult(
            provider_name="rule_based",
            chat_type=chat_type,
            tool_plans=deduplicate_tool_plans(tool_plans),
        )


def plan_farmer_bnpl_tools(*, message: str, user_id: str) -> list[AgentToolPlan]:
    plans = [
        AgentToolPlan(
            server_name="farmer-bnpl-mcp",
            tool_name="get_user_credit_limit",
            request_payload={"user_id": user_id},
            reason="Check available BNPL limit before recommending purchase actions.",
        ),
        AgentToolPlan(
            server_name="farmer-bnpl-mcp",
            tool_name="get_farmer_profile",
            request_payload={"user_id": user_id},
            reason="Use farmer profile context for personalized guidance.",
        ),
    ]

    if any(keyword in message for keyword in ("document", "서류", "신청", "심사")):
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="get_required_documents",
                request_payload={"user_id": user_id},
                reason="Show required documents for the BNPL application flow.",
            )
        )

    repayment_keywords = ("repayment", "상환", "interest", "이자", "overdue", "연체")
    if any(keyword in message for keyword in repayment_keywords):
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

    delivery_keywords = ("delivery", "배송", "주문", "order")
    if any(keyword in message for keyword in delivery_keywords):
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="get_latest_order_delivery_status",
                request_payload={"user_id": user_id},
                reason="Read latest order delivery status for the farmer.",
            )
        )

    sensor_keywords = ("sensor", "센서", "스마트팜", "smartfarm", "smart farm")
    if any(keyword in message for keyword in sensor_keywords):
        plans.append(
            AgentToolPlan(
                server_name="farmer-bnpl-mcp",
                tool_name="search_products",
                request_payload={"query": "sensor", "limit": 3},
                reason="Find smart farm sensor product candidates.",
            )
        )

    purchase_keywords = (
        "fertilizer",
        "비료",
        "product",
        "농자재",
        "checkout",
        "결제",
        "한도",
    )
    if any(keyword in message for keyword in purchase_keywords):
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

    if any(keyword in message for keyword in ("confirm checkout", "checkout 생성", "구매 확정")):
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


def plan_admin_copilot_tools(*, message: str) -> list[AgentToolPlan]:
    review_limit = extract_requested_limit(message, default=10)
    plans = [
        AgentToolPlan(
            server_name="admin-riskops-mcp",
            tool_name="get_bnpl_summary",
            request_payload={},
            reason="Summarize portfolio-level BNPL exposure.",
        ),
        AgentToolPlan(
            server_name="admin-riskops-mcp",
            tool_name="get_credit_review_queue",
            request_payload={"limit": review_limit},
            reason="Read pending credit review workload.",
        ),
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

    if any(keyword in message for keyword in ("overdue", "연체")):
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
    if any(keyword in message for keyword in user_keywords):
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="search_bnpl_users",
                request_payload={"limit": 10},
                reason="List BNPL users for admin triage.",
            )
        )

    if any(keyword in message for keyword in ("disaster", "재해", "홍수", "가뭄", "폭염")):
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

    if any(keyword in message for keyword in ("snapshot", "스냅샷", "근거")):
        plans.append(
            AgentToolPlan(
                server_name="admin-riskops-mcp",
                tool_name="create_risk_analysis_snapshot",
                request_payload={"target_type": "PORTFOLIO", "target_id": "portfolio"},
                reason="Create a read-only RiskOps evidence snapshot.",
            )
        )

    return plans


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
