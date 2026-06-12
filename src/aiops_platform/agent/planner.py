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
            capability = None
            tool_plans = plan_farmer_bnpl_tools(
                message=normalized_message,
                user_id=user_id,
            )
        elif chat_type == "sre_copilot":
            intent = classify_sre_copilot_intent(normalized_message)
            capability = classify_sre_copilot_capability(normalized_message)
            tool_plans = plan_sre_copilot_tools(
                message=normalized_message,
                capability=capability,
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
SreCopilotIntent = Literal[
    "greeting",
    "thanks",
    "help",
    "unsupported",
    "checkout_500",
    "sqs_publish_failure",
    "sqs_consume_failure",
    "pin_verification_missing",
    "routing_failure",
    "pod_crashloop",
    "db_hikaricp_issue",
    "general_incident",
]
SreCopilotCapability = Literal[
    "smalltalk",
    "help",
    "unsupported",
    "checkout_500_analysis",
    "sqs_publish_failure_analysis",
    "sqs_consume_failure_analysis",
    "pin_verification_missing_analysis",
    "edge_routing_analysis",
    "pod_crashloop_analysis",
    "db_connection_analysis",
    "general_incident_analysis",
]
ADMIN_COPILOT_CAPABILITY_VALUES = set(get_args(AdminCopilotCapability))
ADMIN_DIRECT_CAPABILITIES = {"smalltalk", "help", "unsupported"}
SRE_COPILOT_CAPABILITY_VALUES = set(get_args(SreCopilotCapability))
SRE_DIRECT_CAPABILITIES = {"smalltalk", "help", "unsupported"}
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
SRE_INTENT_TO_CAPABILITY: dict[str, SreCopilotCapability] = {
    "greeting": "smalltalk",
    "thanks": "smalltalk",
    "help": "help",
    "unsupported": "unsupported",
    "checkout_500": "checkout_500_analysis",
    "sqs_publish_failure": "sqs_publish_failure_analysis",
    "sqs_consume_failure": "sqs_consume_failure_analysis",
    "pin_verification_missing": "pin_verification_missing_analysis",
    "routing_failure": "edge_routing_analysis",
    "pod_crashloop": "pod_crashloop_analysis",
    "db_hikaricp_issue": "db_connection_analysis",
    "general_incident": "general_incident_analysis",
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
SRE_CAPABILITY_TO_INTENT: dict[str, SreCopilotIntent] = {
    "smalltalk": "greeting",
    "help": "help",
    "unsupported": "unsupported",
    "checkout_500_analysis": "checkout_500",
    "sqs_publish_failure_analysis": "sqs_publish_failure",
    "sqs_consume_failure_analysis": "sqs_consume_failure",
    "pin_verification_missing_analysis": "pin_verification_missing",
    "edge_routing_analysis": "routing_failure",
    "pod_crashloop_analysis": "pod_crashloop",
    "db_connection_analysis": "db_hikaricp_issue",
    "general_incident_analysis": "general_incident",
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


def plan_sre_copilot_tools(
    *,
    message: str,
    capability: SreCopilotCapability | None = None,
) -> list[AgentToolPlan]:
    resolved_capability = capability or classify_sre_copilot_capability(message)
    if resolved_capability in SRE_DIRECT_CAPABILITIES:
        return []

    intent = sre_intent_for_capability(capability=resolved_capability)
    context = build_sre_incident_context(message=message, intent=intent)
    namespace_payload = {"namespace": context["namespace"]}
    deployment_payload = {
        "namespace": context["namespace"],
        "deployment_name": context["deployment_name"],
    }

    topology_payload = {
        "service": context["topology_service"],
        "environment": "all",
        "masking_level": "secrets_only",
    }

    plans = [
        build_sre_tool_plan(
            "get_topology_snapshot",
            {"environment": "all", "detail": "summary", "masking_level": "secrets_only"},
            "Read known on-prem/AWS topology context before live checks.",
        ),
        build_sre_tool_plan(
            "search_topology_knowledge",
            {
                "query": f'{intent} {context["topology_service"]}',
                "environment": "all",
                "limit": 5,
                "masking_level": "secrets_only",
            },
            "Search topology knowledge for incident-specific routing and risk context.",
        ),
        build_sre_tool_plan(
            "get_service_routing_path",
            topology_payload,
            "Read the known traffic path for the suspected service.",
        ),
        build_sre_tool_plan(
            "get_service_dependency_map",
            topology_payload,
            "Read known upstream/downstream dependencies for the suspected service.",
        ),
        build_sre_tool_plan(
            "get_alertmanager_alerts",
            {"active_only": True, "limit": 20},
            "Read active alerts before correlating logs, metrics, and traces.",
        ),
        build_sre_tool_plan(
            "query_multi_cluster_prometheus",
            {"query": context["prometheus_query"]},
            "Read metric evidence for the suspected incident path.",
        ),
        build_sre_tool_plan(
            "query_multi_cluster_loki",
            {"query": context["loki_query"], "limit": 100},
            "Read recent application and platform logs for the suspected service.",
        ),
        build_sre_tool_plan(
            "get_k8s_pods",
            namespace_payload,
            "Inspect pod readiness, restart count, and node placement.",
        ),
        build_sre_tool_plan(
            "get_k8s_events",
            namespace_payload,
            "Inspect Kubernetes warning and scheduling events.",
        ),
        build_sre_tool_plan(
            "get_k8s_deployments",
            namespace_payload,
            "Inspect deployment desired/current/available state.",
        ),
        build_sre_tool_plan(
            "get_k8s_hpa",
            namespace_payload,
            "Inspect autoscaling status and resource pressure evidence.",
        ),
        build_sre_tool_plan(
            "get_rollout_status",
            deployment_payload,
            "Check whether the target deployment rollout is healthy.",
        ),
        build_sre_tool_plan(
            "get_current_image_tags",
            deployment_payload,
            "Compare currently running image tags against recent deployment evidence.",
        ),
        build_sre_tool_plan(
            "get_recent_deployments",
            {"namespace": context["namespace"], "limit": 10},
            "Check whether a recent deployment correlates with the incident window.",
        ),
        build_sre_tool_plan(
            "get_argocd_application_status",
            {"application_name": context["deployment_name"]},
            "Read GitOps sync and health status for the target application.",
        ),
        build_sre_tool_plan(
            "get_service_trace_summary",
            {"service_name": context["service_name"], "limit": 50},
            "Read trace latency and error summary for the target service.",
        ),
        build_sre_tool_plan(
            "search_traces",
            {
                "service_name": context["service_name"],
                "operation_name": context["operation_name"],
                "limit": 20,
            },
            "Find recent traces that can connect symptoms to downstream spans.",
        ),
    ]

    pod_name = extract_sre_pod_name(message)
    if pod_name is not None:
        plans.append(
            build_sre_tool_plan(
                "get_pod_logs",
                {
                    "namespace": context["namespace"],
                    "pod_name": pod_name,
                    "tail_lines": 200,
                },
                "Read logs for the pod explicitly named by the monitoring operator.",
            )
        )

    if intent in {
        "sqs_publish_failure",
        "sqs_consume_failure",
        "pin_verification_missing",
    }:
        plans.extend(
            [
                build_sre_tool_plan(
                    "get_sqs_queue_attributes",
                    {"queue_name": context["queue_name"]},
                    "Read SQS queue depth and visibility timeout attributes.",
                ),
                build_sre_tool_plan(
                    "get_sqs_dlq_attributes",
                    {"queue_name": context["dlq_name"]},
                    "Read DLQ depth to confirm message failure accumulation.",
                ),
            ]
        )

    if intent in {"routing_failure", "checkout_500", "general_incident"}:
        routing_plans = []
        alb_payload = build_sre_alb_target_health_payload(context)
        if alb_payload:
            routing_plans.append(
                build_sre_tool_plan(
                    "get_alb_target_health",
                    alb_payload,
                    "Read ALB target health for the inferred edge path.",
                )
            )
        routing_plans.extend(
            [
                build_sre_tool_plan(
                    "get_cloudfront_origin_mapping",
                    {},
                    "Read CloudFront origin mapping for edge to ALB routing.",
                ),
                build_sre_tool_plan(
                    "get_cloudfront_distribution_status",
                    {},
                    "Read CloudFront distribution status and deployment state.",
                ),
            ]
        )
        plans.extend(routing_plans)

    plans.extend(
        [
            build_sre_tool_plan(
                "search_incidents",
                {"query": intent, "limit": 5},
                "Search similar incidents for historical context.",
            ),
            build_sre_tool_plan(
                "search_rca_history",
                {"query": intent, "limit": 5},
                "Search previous RCA summaries before suggesting actions.",
            ),
            build_sre_tool_plan(
                "create_rca_snapshot",
                {
                    "incident_key": intent,
                    "namespace": context["namespace"],
                    "prometheus_query": context["prometheus_query"],
                    "loki_query": context["loki_query"],
                    "loki_limit": 100,
                },
                "Create a read-only RCA evidence snapshot for later analysis.",
            ),
        ]
    )
    return plans


def build_sre_tool_plan(tool_name: str, request_payload: dict[str, Any], reason: str) -> AgentToolPlan:
    return AgentToolPlan(
        server_name="infraops-mcp",
        tool_name=tool_name,
        request_payload=request_payload,
        reason=reason,
    )


def build_sre_alb_target_health_payload(context: dict[str, str | None]) -> dict[str, Any]:
    load_balancer_name = context.get("load_balancer_name")
    if load_balancer_name is None:
        return {}
    return {"load_balancer_name": load_balancer_name}


def build_sre_incident_context(*, message: str, intent: SreCopilotIntent) -> dict[str, str | None]:
    service_name = infer_sre_service_name(message, intent=intent)
    namespace = infer_sre_namespace(service_name)
    deployment_name = infer_sre_deployment_name(message, default=service_name)
    queue_name, dlq_name = infer_sre_queue_names(intent)
    edge_target = infer_sre_edge_target(message, intent=intent, service_name=service_name)
    return {
        "service_name": service_name,
        "namespace": namespace,
        "deployment_name": deployment_name,
        "queue_name": queue_name,
        "dlq_name": dlq_name,
        "edge_target": edge_target,
        "load_balancer_name": infer_sre_load_balancer_name(
            message,
            intent=intent,
            service_name=service_name,
            edge_target=edge_target,
        ),
        "operation_name": infer_sre_operation_name(intent),
        "topology_service": infer_sre_topology_service(intent, service_name=service_name),
        "prometheus_query": build_sre_prometheus_query(intent, service_name=service_name),
        "loki_query": build_sre_loki_query(intent, namespace=namespace, service_name=service_name),
    }


def infer_sre_service_name(message: str, *, intent: SreCopilotIntent) -> str:
    explicit_services = (
        "service-catalog",
        "service-payment",
        "service-auth",
        "service-core",
        "service-admin",
        "mcp-aiops-backend",
    )
    for service_name in explicit_services:
        if service_name in message:
            return service_name
    if intent in {"sqs_consume_failure"}:
        return "service-payment"
    if intent in {"checkout_500", "sqs_publish_failure", "pin_verification_missing"}:
        return "service-catalog"
    if "payment" in message or "결제" in message:
        return "service-payment"
    if "auth" in message or "인증" in message:
        return "service-auth"
    return "service-catalog"


def infer_sre_edge_target(
    message: str,
    *,
    intent: SreCopilotIntent,
    service_name: str,
) -> str:
    onprem_services = {"service-auth", "service-payment", "service-core", "service-admin"}
    if service_name in onprem_services or any(
        keyword in message
        for keyword in ("on-prem", "onprem", "온프렘", "metallb", "metal lb")
    ):
        return "onprem"
    if intent == "checkout_500" or any(
        keyword in message for keyword in ("eks", "service-catalog", "catalog")
    ):
        return "aws_eks"
    return "unknown"


def infer_sre_load_balancer_name(
    message: str,
    *,
    intent: SreCopilotIntent,
    service_name: str,
    edge_target: str,
) -> str | None:
    explicit_match = re.search(
        r"\b(?:load_balancer_name|load-balancer-name|alb_name|alb-name|lb_name|lb-name)"
        r"[=: ]+([a-z0-9][a-z0-9.-]{0,252})\b",
        message,
    )
    if explicit_match is not None:
        return explicit_match.group(1)
    if edge_target == "aws_eks" and (
        intent == "checkout_500"
        or service_name == "service-catalog"
        or any(keyword in message for keyword in ("eks", "service-catalog", "catalog"))
    ):
        return "kkpp-catalog-api"
    return None


def infer_sre_namespace(service_name: str) -> str:
    if service_name == "service-catalog":
        return "service-catalog"
    return "default"


def infer_sre_deployment_name(message: str, *, default: str) -> str:
    match = re.search(r"\bdeployment[/: ]+([a-z0-9][a-z0-9.-]{0,252})\b", message)
    if match is not None:
        return match.group(1)
    return default


def infer_sre_queue_names(intent: SreCopilotIntent) -> tuple[str, str]:
    if intent == "pin_verification_missing":
        return "payment-pin-verified.fifo", "payment-pin-verified-dlq.fifo"
    return "credit-payment-requested.fifo", "credit-payment-requested-dlq.fifo"


def infer_sre_operation_name(intent: SreCopilotIntent) -> str | None:
    return {
        "checkout_500": "POST /checkout",
        "sqs_publish_failure": "SQS Publish",
        "sqs_consume_failure": "SQS Consume",
        "pin_verification_missing": "PIN Verified Event",
    }.get(intent)


def infer_sre_topology_service(intent: SreCopilotIntent, *, service_name: str) -> str:
    if intent == "checkout_500":
        return "checkout"
    if intent in {"sqs_publish_failure", "sqs_consume_failure"}:
        return "payment"
    if intent == "pin_verification_missing":
        return "pin"
    if intent == "routing_failure":
        return service_name
    return service_name


def build_sre_prometheus_query(intent: SreCopilotIntent, *, service_name: str) -> str:
    if intent == "checkout_500":
        return (
            'sum(rate(http_server_requests_seconds_count{application="'
            f'{service_name}",status=~"5..",uri=~".*checkout.*"}}[5m]))'
        )
    if intent == "sqs_publish_failure":
        return 'sum(rate(application_sqs_publish_errors_total{service="' + service_name + '"}[5m]))'
    if intent == "sqs_consume_failure":
        return 'sum(rate(application_sqs_consume_errors_total{service="' + service_name + '"}[5m]))'
    if intent == "pin_verification_missing":
        return 'sum(rate(pin_verification_events_total{service="' + service_name + '"}[5m]))'
    if intent == "routing_failure":
        return "sum(rate(aws_applicationelb_httpcode_target_5_xx_count_sum[5m]))"
    if intent == "pod_crashloop":
        return 'sum by (pod) (increase(kube_pod_container_status_restarts_total{pod=~".+"}[15m]))'
    if intent == "db_hikaricp_issue":
        return 'max by (pool) (hikaricp_connections_active{application="' + service_name + '"})'
    return "up"


def build_sre_loki_query(intent: SreCopilotIntent, *, namespace: str, service_name: str) -> str:
    base_query = f'{{namespace="{namespace}"}}'
    if intent == "checkout_500":
        return f'{base_query} |= "checkout" |~ "500|Exception|ERROR"'
    if intent == "sqs_publish_failure":
        return f'{base_query} |~ "SQS|publish|sendMessage|ERROR|Exception"'
    if intent == "sqs_consume_failure":
        return f'{base_query} |~ "SQS|consume|listener|DLQ|ERROR|Exception"'
    if intent == "pin_verification_missing":
        return f'{base_query} |~ "PIN|pin|verified|verification|event|ERROR|Exception"'
    if intent == "routing_failure":
        return f'{base_query} |~ "ingress|ALB|CloudFront|origin|route|5..|target"'
    if intent == "pod_crashloop":
        return f'{base_query} |~ "CrashLoopBackOff|OOMKilled|Exception|ERROR|panic"'
    if intent == "db_hikaricp_issue":
        return f'{base_query} |~ "HikariPool|JDBC|connection|timeout|postgres|SQLException"'
    return f'{base_query} |~ "{service_name}|ERROR|Exception|WARN"'


def extract_sre_pod_name(message: str) -> str | None:
    explicit = re.search(r"\bpod[/: ]+([a-z0-9][a-z0-9.-]{0,252})\b", message)
    if explicit is not None:
        return explicit.group(1)
    generated = re.search(r"\b([a-z0-9][a-z0-9-]+-[a-f0-9]{8,10}-[a-z0-9]{5})\b", message)
    return generated.group(1) if generated is not None else None


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


def classify_sre_copilot_intent(message: str) -> SreCopilotIntent:
    normalized = " ".join(message.lower().split())
    compact = normalized.replace(" ", "")
    if not normalized:
        return "help"

    sre_keywords = (
        "장애",
        "incident",
        "alert",
        "500",
        "error",
        "로그",
        "log",
        "metric",
        "메트릭",
        "trace",
        "트레이스",
        "pod",
        "파드",
        "crashloop",
        "crashloopbackoff",
        "sqs",
        "queue",
        "dlq",
        "alb",
        "cloudfront",
        "route",
        "routing",
        "라우팅",
        "hikari",
        "db",
        "database",
        "checkout",
        "pin",
        "eks",
        "kubernetes",
    )
    greeting_keywords = ("안녕", "안녕하세요", "하이", "hello", "hi", "hey")
    if compact in greeting_keywords or (
        any(compact.startswith(keyword) for keyword in greeting_keywords)
        and not any(keyword in normalized for keyword in sre_keywords)
    ):
        return "greeting"

    thanks_keywords = ("고마워", "감사", "thanks", "thank you", "thx")
    if any(keyword in normalized for keyword in thanks_keywords) and not any(
        keyword in normalized for keyword in sre_keywords
    ):
        return "thanks"

    help_keywords = ("도움말", "사용법", "뭐 할 수", "무엇을 할 수", "기능", "help")
    if any(keyword in normalized for keyword in help_keywords):
        return "help"

    write_keywords = (
        "delete pod",
        "pod delete",
        "rollout restart",
        "scale deployment",
        "kubectl exec",
        "삭제",
        "재시작",
        "스케일",
        "exec",
    )
    if any(keyword in normalized for keyword in write_keywords):
        return "unsupported"

    if any(keyword in normalized for keyword in ("cloudfront", "alb", "origin", "라우팅", "routing", "route")):
        return "routing_failure"
    if any(keyword in normalized for keyword in ("crashloop", "crashloopbackoff", "oomkilled")):
        return "pod_crashloop"
    if any(keyword in normalized for keyword in ("hikari", "hikaricp", "db", "database", "postgres", "connection pool")):
        return "db_hikaricp_issue"

    has_sqs = "sqs" in normalized or "queue" in normalized or "dlq" in normalized
    if has_sqs and any(keyword in normalized for keyword in ("발행", "publish", "send", "producer")):
        return "sqs_publish_failure"
    if has_sqs and any(keyword in normalized for keyword in ("소비", "consume", "consumer", "listener", "lag", "dlq")):
        return "sqs_consume_failure"
    if any(keyword in normalized for keyword in ("pin", "핀")) and any(
        keyword in normalized for keyword in ("검증", "verified", "verification", "미반영", "event", "이벤트")
    ):
        return "pin_verification_missing"
    if "checkout" in normalized and any(keyword in normalized for keyword in ("500", "error", "오류", "장애")):
        return "checkout_500"
    if any(keyword in normalized for keyword in ("pod", "파드")) and any(
        keyword in normalized for keyword in ("restart", "재시작", "error", "오류", "장애")
    ):
        return "pod_crashloop"
    if any(keyword in normalized for keyword in sre_keywords):
        return "general_incident"
    return "unsupported"


def classify_admin_copilot_capability(message: str) -> AdminCopilotCapability:
    intent = classify_admin_copilot_intent(message)
    return ADMIN_INTENT_TO_CAPABILITY[intent]


def classify_sre_copilot_capability(message: str) -> SreCopilotCapability:
    intent = classify_sre_copilot_intent(message)
    return SRE_INTENT_TO_CAPABILITY[intent]


def normalize_admin_capability(value: object) -> AdminCopilotCapability | None:
    normalized = normalize_optional_string(value)
    if normalized is None:
        return None
    normalized = normalized.lower().replace("-", "_")
    if normalized in ADMIN_COPILOT_CAPABILITY_VALUES:
        return normalized  # type: ignore[return-value]
    return None


def normalize_sre_capability(value: object) -> SreCopilotCapability | None:
    normalized = normalize_optional_string(value)
    if normalized is None:
        return None
    normalized = normalized.lower().replace("-", "_")
    if normalized in SRE_COPILOT_CAPABILITY_VALUES:
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


def sre_intent_for_capability(
    *,
    capability: SreCopilotCapability,
    fallback_intent: str | None = None,
) -> SreCopilotIntent:
    if capability == "smalltalk" and fallback_intent in {"greeting", "thanks"}:
        return fallback_intent  # type: ignore[return-value]
    return SRE_CAPABILITY_TO_INTENT[capability]


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
        "For greeting, thanks, help, or unsupported requests, set requires_tools=false, "
        "tool_plans=[], and provide a Korean direct_answer. "
        "For supported data requests, set requires_tools=true and provide the minimal tool_plans. "
        "Each tool plan must include server_name, tool_name, request_payload, and reason. "
        "Keep request_payload minimal; backend will fill safe defaults such as user_id. "
        "If requested analysis is unsupported by available_tools, do not choose adjacent tools. "
        "For sre_copilot, use only READ InfraOps tools and never plan kubectl exec, pod delete, "
        "rollout restart, scaling, or other mutating actions. Choose the scenario capability "
        "that best matches the incident symptom."
    )


def available_capabilities_for_prompt(chat_type: ChatType) -> list[dict[str, str]]:
    if chat_type == "sre_copilot":
        return [
            {
                "capability": "smalltalk",
                "description": "Greeting or thanks that does not require incident data.",
            },
            {
                "capability": "help",
                "description": "Explain what SRE Copilot can analyze.",
            },
            {
                "capability": "unsupported",
                "description": "Mutating operations or unsupported analysis requests.",
            },
            {
                "capability": "checkout_500_analysis",
                "description": "Analyze checkout 500 errors using logs, metrics, traces, K8s, AWS, and GitOps.",
            },
            {
                "capability": "sqs_publish_failure_analysis",
                "description": "Analyze SQS publish failures and queue attributes.",
            },
            {
                "capability": "sqs_consume_failure_analysis",
                "description": "Analyze SQS consumer, listener, lag, and DLQ failure symptoms.",
            },
            {
                "capability": "pin_verification_missing_analysis",
                "description": "Analyze missing PIN verification event propagation.",
            },
            {
                "capability": "edge_routing_analysis",
                "description": "Analyze CloudFront to ALB to EKS routing failures.",
            },
            {
                "capability": "pod_crashloop_analysis",
                "description": "Analyze pod CrashLoopBackOff, restarts, and Kubernetes events.",
            },
            {
                "capability": "db_connection_analysis",
                "description": "Analyze DB, PostgreSQL, JDBC, and HikariCP connection issues.",
            },
            {
                "capability": "general_incident_analysis",
                "description": "General read-only SRE incident triage using available observability evidence.",
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
    if chat_type == "sre_copilot":
        return {
            ("infraops-mcp", tool_name)
            for tool_name in (
                "query_prometheus",
                "query_loki",
                "query_multi_cluster_prometheus",
                "query_multi_cluster_loki",
                "search_traces",
                "get_trace_by_id",
                "get_service_trace_summary",
                "get_trace_error_spans",
                "get_k8s_pods",
                "get_k8s_events",
                "get_k8s_deployments",
                "get_k8s_hpa",
                "get_pod_logs",
                "get_rollout_status",
                "get_alertmanager_alerts",
                "get_sqs_queue_attributes",
                "get_sqs_dlq_attributes",
                "get_alb_target_health",
                "get_cloudfront_origin_mapping",
                "get_cloudfront_distribution_status",
                "get_argocd_application_status",
                "get_current_image_tags",
                "get_recent_deployments",
                "get_topology_snapshot",
                "search_topology_knowledge",
                "get_service_routing_path",
                "get_service_dependency_map",
                "create_rca_snapshot",
                "search_incidents",
                "search_rca_history",
            )
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

    if chat_type == "sre_copilot":
        llm_capability = normalize_sre_capability(payload.get("capability"))
        if llm_capability is not None and llm_capability not in SRE_DIRECT_CAPABILITIES:
            plans = deduplicate_tool_plans(
                plan_sre_copilot_tools(
                    message=message.lower(),
                    capability=llm_capability,
                )
            )
            if plans:
                return AgentPlanResult(
                    provider_name="llm",
                    chat_type=chat_type,
                    intent=sre_intent_for_capability(
                        capability=llm_capability,
                        fallback_intent=intent,
                    ),
                    capability=llm_capability,
                    tool_plans=plans,
                )
        if llm_capability is not None:
            capability = llm_capability
            intent = sre_intent_for_capability(
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
        chat_type in {"admin_copilot", "sre_copilot"}
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
    if server_name == "infraops-mcp":
        normalized = normalize_infraops_tool_payload(
            tool_name=tool_name,
            message=message,
            payload=normalized,
        )
    return normalized


def normalize_infraops_tool_payload(
    *,
    tool_name: str,
    message: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(payload)
    intent = classify_sre_copilot_intent(message)
    context = build_sre_incident_context(message=message.lower(), intent=intent)

    if tool_name == "get_topology_snapshot":
        normalized["environment"] = (
            normalize_topology_environment(normalized.get("environment")) or "all"
        )
        normalized["detail"] = normalize_topology_detail(normalized.get("detail")) or "summary"
        normalized["masking_level"] = (
            normalize_topology_masking_level(normalized.get("masking_level"))
            or "secrets_only"
        )
    if tool_name == "search_topology_knowledge":
        normalized["query"] = (
            normalize_optional_string(normalized.get("query"))
            or f'{intent} {context["topology_service"]}'
        )
        normalized["environment"] = (
            normalize_topology_environment(normalized.get("environment")) or "all"
        )
        normalized["limit"] = clamp_int(normalized.get("limit"), default=5)
        normalized["masking_level"] = (
            normalize_topology_masking_level(normalized.get("masking_level"))
            or "secrets_only"
        )
    if tool_name in {"get_service_routing_path", "get_service_dependency_map"}:
        normalized["service"] = (
            normalize_optional_string(normalized.get("service"))
            or str(context["topology_service"])
        )
        normalized["environment"] = (
            normalize_topology_environment(normalized.get("environment")) or "all"
        )
        normalized["masking_level"] = (
            normalize_topology_masking_level(normalized.get("masking_level"))
            or "secrets_only"
        )
    if tool_name in {"query_prometheus", "query_multi_cluster_prometheus"}:
        normalized["query"] = (
            normalize_optional_string(normalized.get("query"))
            or str(context["prometheus_query"])
        )
    if tool_name in {"query_loki", "query_multi_cluster_loki"}:
        normalized["query"] = (
            normalize_optional_string(normalized.get("query"))
            or str(context["loki_query"])
        )
        normalized["limit"] = clamp_int(normalized.get("limit"), default=100)
    if tool_name == "get_alertmanager_alerts":
        normalized["active_only"] = parse_bool(normalized.get("active_only", True))
        normalized["limit"] = clamp_int(normalized.get("limit"), default=20)
    if tool_name in {
        "get_k8s_pods",
        "get_k8s_events",
        "get_k8s_deployments",
        "get_k8s_hpa",
        "get_current_image_tags",
        "get_recent_deployments",
        "create_rca_snapshot",
    }:
        normalized["namespace"] = (
            normalize_optional_string(normalized.get("namespace"))
            or str(context["namespace"])
        )
    if tool_name in {"get_rollout_status", "get_current_image_tags"}:
        normalized["deployment_name"] = (
            normalize_optional_string(normalized.get("deployment_name"))
            or str(context["deployment_name"])
        )
    if tool_name == "get_recent_deployments":
        normalized["limit"] = clamp_int(normalized.get("limit"), default=10)
    if tool_name in {"search_traces", "get_service_trace_summary"}:
        normalized["service_name"] = (
            normalize_optional_string(normalized.get("service_name"))
            or str(context["service_name"])
        )
        normalized["limit"] = clamp_int(normalized.get("limit"), default=50)
    if tool_name == "search_traces":
        operation_name = normalize_optional_string(normalized.get("operation_name"))
        if operation_name is None and context["operation_name"] is not None:
            normalized["operation_name"] = context["operation_name"]
    if tool_name == "get_argocd_application_status":
        normalized["application_name"] = (
            normalize_optional_string(normalized.get("application_name"))
            or str(context["deployment_name"])
        )
    if tool_name in {"get_sqs_queue_attributes", "get_sqs_dlq_attributes"}:
        default_queue = (
            context["dlq_name"] if tool_name == "get_sqs_dlq_attributes" else context["queue_name"]
        )
        if normalize_optional_string(normalized.get("queue_url")) is None:
            normalized["queue_name"] = (
                normalize_optional_string(normalized.get("queue_name"))
                or str(default_queue)
            )
    if tool_name == "get_alb_target_health":
        for key in (
            "target_group_arn",
            "target_group_name",
            "load_balancer_name",
            "region",
        ):
            value = normalize_optional_string(normalized.get(key))
            if value is None:
                normalized.pop(key, None)
            else:
                normalized[key] = value
        if not any(
            normalized.get(key)
            for key in ("target_group_arn", "target_group_name", "load_balancer_name")
        ) and context["load_balancer_name"] is not None:
            normalized["load_balancer_name"] = context["load_balancer_name"]
    if tool_name == "get_pod_logs":
        pod_name = normalize_optional_string(normalized.get("pod_name")) or extract_sre_pod_name(message)
        if pod_name is not None:
            normalized["pod_name"] = pod_name
        normalized["namespace"] = (
            normalize_optional_string(normalized.get("namespace"))
            or str(context["namespace"])
        )
        normalized["tail_lines"] = clamp_int(normalized.get("tail_lines"), default=200)
    if tool_name in {"search_incidents", "search_rca_history"}:
        normalized["query"] = normalize_optional_string(normalized.get("query")) or intent
        normalized["limit"] = clamp_int(normalized.get("limit"), default=5)
    if tool_name == "create_rca_snapshot":
        normalized["incident_key"] = normalize_optional_string(normalized.get("incident_key")) or intent
        normalized["prometheus_query"] = (
            normalize_optional_string(normalized.get("prometheus_query"))
            or str(context["prometheus_query"])
        )
        normalized["loki_query"] = (
            normalize_optional_string(normalized.get("loki_query"))
            or str(context["loki_query"])
        )
        normalized["loki_limit"] = clamp_int(normalized.get("loki_limit"), default=100)
        if not isinstance(normalized.get("context_bundle"), dict):
            normalized.pop("context_bundle", None)
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
    if chat_type == "sre_copilot":
        return {
            "greeting": (
                "안녕하세요. 로그, 메트릭, 트레이스, Kubernetes, AWS, GitOps 근거로 "
                "장애 원인 분석을 도와드릴 수 있습니다."
            ),
            "thanks": "필요하면 장애 증상과 대상 서비스를 알려주세요. READ 기반으로 분석하겠습니다.",
            "help": (
                "checkout 500, SQS 발행/소비 실패, PIN 이벤트 미반영, "
                "CloudFront-ALB-EKS 라우팅 실패, CrashLoopBackOff, DB/HikariCP 문제를 분석할 수 있습니다."
            ),
            "unsupported": (
                "현재 SRE Copilot은 READ 기반 관측/분석만 지원합니다. "
                "재시작, 삭제, scale, kubectl exec 같은 변경 작업은 실행하지 않습니다."
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


def normalize_topology_environment(value: object) -> str | None:
    normalized = normalize_optional_string(value)
    if normalized in {"onprem", "aws_eks", "all"}:
        return normalized
    if normalized in {"aws", "eks", "aws-eks"}:
        return "aws_eks"
    if normalized in {"on-prem", "on_prem"}:
        return "onprem"
    return None


def normalize_topology_detail(value: object) -> str | None:
    normalized = normalize_optional_string(value)
    if normalized in {"summary", "full"}:
        return normalized
    return None


def normalize_topology_masking_level(value: object) -> str | None:
    normalized = normalize_optional_string(value)
    if normalized in {"secrets_only", "infrastructure"}:
        return normalized
    return None


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
