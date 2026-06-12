from aiops_platform.agent.dispatcher import McpToolDispatcher
from aiops_platform.agent.context_bundle import build_incident_context_bundle
from aiops_platform.agent.orchestrator import AgentOrchestrator
from aiops_platform.agent.planner import (
    LlmAgentPlanner,
    RuleBasedAgentPlanner,
    classify_admin_copilot_capability,
    classify_admin_copilot_intent,
    classify_farmer_bnpl_intent,
    classify_sre_copilot_capability,
    classify_sre_copilot_intent,
)
from aiops_platform.agent.schemas import AgentPlanResult, AgentToolExecutionResult, AgentToolPlan
from aiops_platform.llmops.client import LlmCompletionResponse
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)
from aiops_platform.orchestration.service import (
    build_direct_chat_response,
    resolve_assistant_content,
)
from tests.seed_constants import FARMER_1_ID


class FakePlannerLlmClient:
    provider = "fake-planner"
    model = "fake-planner-model"

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def complete(self, request):
        return LlmCompletionResponse(
            provider=self.provider,
            model=self.model,
            content="{}",
            output_payload=self.payload,
        )


class FakeInfraOpsService:
    def query_multi_cluster_prometheus(self, **payload):
        return {"query": payload["query"], "partial": False, "sources": []}

    def query_multi_cluster_loki(self, **payload):
        return {"query": payload["query"], "limit": payload["limit"], "sources": []}

    def get_alertmanager_alerts(self, **payload):
        return {"items": [], "active_only": payload["active_only"]}


class FakeTopologyKnowledgeService:
    def get_topology_snapshot(self, **payload):
        return {"environment": payload["environment"], "snapshots": []}

    def search_topology_knowledge(self, **payload):
        return {"query": payload["query"], "matches": []}

    def get_service_routing_path(self, **payload):
        return {"service": payload["service"], "routing_paths": []}

    def get_service_dependency_map(self, **payload):
        return {"service": payload["service"], "dependencies": []}


class FakeSreRcaPlanner:
    provider_name = "fake"

    def plan(self, *, chat_type, message, user_id):
        return AgentPlanResult(
            provider_name="rule_based",
            chat_type=chat_type,
            intent="checkout_500",
            capability="checkout_500_analysis",
            tool_plans=[
                AgentToolPlan(
                    server_name="infraops-mcp",
                    tool_name="get_topology_snapshot",
                    request_payload={"environment": "all"},
                    reason="Read topology.",
                ),
                AgentToolPlan(
                    server_name="infraops-mcp",
                    tool_name="query_multi_cluster_loki",
                    request_payload={"query": '{namespace="service-catalog"}', "limit": 10},
                    reason="Read logs.",
                ),
                AgentToolPlan(
                    server_name="infraops-mcp",
                    tool_name="create_rca_snapshot",
                    request_payload={"incident_key": "checkout_500"},
                    reason="Create RCA snapshot.",
                ),
            ],
        )


class RecordingDispatcher:
    def __init__(self) -> None:
        self.plans: list[AgentToolPlan] = []

    def execute(self, plan: AgentToolPlan) -> AgentToolExecutionResult:
        self.plans.append(plan)
        return AgentToolExecutionResult(
            server_name=plan.server_name,
            tool_name=plan.tool_name,
            tool_permission=McpToolPermission.READ,
            confirmation_policy=McpConfirmationPolicy.NONE,
            execution_policy=McpExecutionPolicy.ALLOWED,
            call_status=McpToolCallStatus.SUCCESS,
            will_execute=True,
            requires_approval=False,
            is_blocked=False,
            request_payload=plan.request_payload,
            masked_request_payload=plan.request_payload,
            response_payload={"tool_name": plan.tool_name},
            masked_response_payload={"tool_name": plan.tool_name},
        )


def make_sre_tool_result(
    tool_name: str,
    response_payload: dict,
    *,
    status: McpToolCallStatus = McpToolCallStatus.SUCCESS,
) -> AgentToolExecutionResult:
    return AgentToolExecutionResult(
        server_name="infraops-mcp",
        tool_name=tool_name,
        tool_permission=McpToolPermission.READ,
        confirmation_policy=McpConfirmationPolicy.NONE,
        execution_policy=McpExecutionPolicy.ALLOWED,
        call_status=status,
        will_execute=True,
        requires_approval=False,
        is_blocked=False,
        request_payload={},
        masked_request_payload={},
        response_payload=response_payload,
        masked_response_payload=response_payload,
    )


def test_rule_based_planner_selects_farmer_bnpl_purchase_tools() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="farmer_bnpl",
        message="내 한도 안에서 비료를 추천하고 checkout 준비해줘",
        user_id=FARMER_1_ID,
    )

    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_user_credit_limit",
        "get_farmer_profile",
        "recommend_fertilizer_requirements",
        "search_lowest_price_fertilizer",
        "prepare_bnpl_checkout_payload",
    ]


def test_rule_based_planner_skips_farmer_tools_for_greeting() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(chat_type="farmer_bnpl", message="안녕", user_id=FARMER_1_ID)

    assert classify_farmer_bnpl_intent("안녕") == "greeting"
    assert plan.tool_plans == []


def test_rule_based_planner_selects_farmer_credit_limit_tool() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="farmer_bnpl",
        message="내 외상 한도 알려줘",
        user_id=FARMER_1_ID,
    )

    assert [tool.tool_name for tool in plan.tool_plans] == ["get_user_credit_limit"]


def test_rule_based_planner_selects_farmer_repayment_tools() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="farmer_bnpl",
        message="상환 일정이랑 이자 알려줘",
        user_id=FARMER_1_ID,
    )

    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_repayment_schedule",
        "get_interest_due",
        "get_overdue_status",
    ]


def test_llm_planner_builds_validated_tool_plan() -> None:
    planner = LlmAgentPlanner(
        llm_client=FakePlannerLlmClient(
            {
                "intent": "credit_limit",
                "requires_tools": True,
                "tool_plans": [
                    {
                        "server_name": "farmer-bnpl-mcp",
                        "tool_name": "get_user_credit_limit",
                        "request_payload": {},
                        "reason": "Need current user credit limit.",
                    }
                ],
            }
        )
    )

    plan = planner.plan(
        chat_type="farmer_bnpl",
        message="내 외상 한도 알려줘",
        user_id=FARMER_1_ID,
    )

    assert plan.provider_name == "llm"
    assert plan.intent == "credit_limit"
    assert [tool.tool_name for tool in plan.tool_plans] == ["get_user_credit_limit"]
    assert plan.tool_plans[0].request_payload == {"user_id": FARMER_1_ID}


def test_llm_planner_returns_direct_answer_without_tools() -> None:
    planner = LlmAgentPlanner(
        llm_client=FakePlannerLlmClient(
            {
                "intent": "greeting",
                "requires_tools": False,
                "direct_answer": "안녕하세요. 무엇을 도와드릴까요?",
                "tool_plans": [],
            }
        )
    )

    plan = planner.plan(chat_type="admin_copilot", message="안녕", user_id="admin-1")

    assert plan.provider_name == "llm"
    assert plan.tool_plans == []
    assert plan.direct_answer == "안녕하세요. 무엇을 도와드릴까요?"


def test_llm_planner_rejects_unallowed_tool_and_falls_back() -> None:
    planner = LlmAgentPlanner(
        llm_client=FakePlannerLlmClient(
            {
                "intent": "dangerous",
                "requires_tools": True,
                "tool_plans": [
                    {
                        "server_name": "infraops-mcp",
                        "tool_name": "delete_pod",
                        "request_payload": {"name": "anything"},
                        "reason": "Invalid dangerous request.",
                    }
                ],
            }
        )
    )

    plan = planner.plan(
        chat_type="admin_copilot",
        message="연체 위험 고객 현황 알려줘",
        user_id="admin-1",
    )

    assert plan.provider_name == "llm_with_rule_fallback"
    assert "valid tool plans" in str(plan.planner_error)
    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_overdue_summary",
        "search_overdue_users",
        "search_bnpl_users",
    ]


def test_rule_based_planner_skips_admin_tools_for_greeting() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(chat_type="admin_copilot", message="안녕", user_id="admin-1")

    assert classify_admin_copilot_intent("안녕") == "greeting"
    assert classify_admin_copilot_capability("안녕") == "smalltalk"
    assert plan.capability == "smalltalk"
    assert plan.tool_plans == []


def test_rule_based_planner_selects_overdue_tools_for_admin_risk_question() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="admin_copilot",
        message="연체 위험 고객 현황 알려줘",
        user_id="admin-1",
    )

    assert plan.capability == "overdue_risk_triage"
    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_overdue_summary",
        "search_overdue_users",
        "search_bnpl_users",
    ]


def test_rule_based_planner_selects_ops_tools_for_admin_action_priority() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="admin_copilot",
        message="관리자 Action 우선순위 정리해줘",
        user_id="admin-1",
    )

    assert plan.intent == "action_priority"
    assert plan.capability == "ops_action_prioritization"
    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_bnpl_summary",
        "get_credit_review_queue",
        "query_multi_cluster_prometheus",
        "get_scaling_summary",
        "get_overdue_summary",
        "search_overdue_users",
    ]


def test_rule_based_planner_selects_sre_checkout_500_tool_bundle() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="sre_copilot",
        message="checkout 500 장애 분석해줘",
        user_id="sre-1",
    )

    tool_names = [tool.tool_name for tool in plan.tool_plans]
    assert classify_sre_copilot_intent("checkout 500 장애 분석해줘") == "checkout_500"
    assert classify_sre_copilot_capability("checkout 500 장애 분석해줘") == (
        "checkout_500_analysis"
    )
    assert plan.intent == "checkout_500"
    assert plan.capability == "checkout_500_analysis"
    assert tool_names[:4] == [
        "get_topology_snapshot",
        "search_topology_knowledge",
        "get_service_routing_path",
        "get_service_dependency_map",
    ]
    assert tool_names[4:8] == [
        "get_alertmanager_alerts",
        "query_multi_cluster_prometheus",
        "query_multi_cluster_loki",
        "get_k8s_pods",
    ]
    assert "get_service_trace_summary" in tool_names
    assert "get_argocd_application_status" in tool_names
    assert "create_rca_snapshot" in tool_names
    rollout = next(tool for tool in plan.tool_plans if tool.tool_name == "get_rollout_status")
    assert rollout.request_payload == {
        "namespace": "service-catalog",
        "deployment_name": "service-catalog",
    }
    alb = next(tool for tool in plan.tool_plans if tool.tool_name == "get_alb_target_health")
    assert alb.request_payload == {"load_balancer_name": "kkpp-catalog-api"}


def test_rule_based_planner_does_not_reuse_catalog_alb_for_onprem_routing() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="sre_copilot",
        message="service-payment CloudFront ALB on-prem MetalLB 라우팅 실패 분석해줘",
        user_id="sre-1",
    )

    tool_names = [tool.tool_name for tool in plan.tool_plans]
    assert plan.intent == "routing_failure"
    assert "get_cloudfront_origin_mapping" in tool_names
    assert "get_cloudfront_distribution_status" in tool_names
    assert "get_alb_target_health" not in tool_names
    rollout = next(tool for tool in plan.tool_plans if tool.tool_name == "get_rollout_status")
    assert rollout.request_payload == {
        "namespace": "default",
        "deployment_name": "service-payment",
    }


def test_rule_based_planner_uses_explicit_alb_name_for_non_catalog_routing() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="sre_copilot",
        message=(
            "service-payment CloudFront ALB on-prem 라우팅 실패 "
            "lb_name=kkpp-onprem-edge 분석해줘"
        ),
        user_id="sre-1",
    )

    alb = next(tool for tool in plan.tool_plans if tool.tool_name == "get_alb_target_health")
    assert alb.request_payload == {"load_balancer_name": "kkpp-onprem-edge"}


def test_rule_based_planner_keeps_sre_mutating_request_unsupported() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="sre_copilot",
        message="service-catalog pod delete 해줘",
        user_id="sre-1",
    )

    assert plan.intent == "unsupported"
    assert plan.capability == "unsupported"
    assert plan.tool_plans == []


def test_llm_planner_maps_admin_capability_to_backend_tool_bundle() -> None:
    planner = LlmAgentPlanner(
        llm_client=FakePlannerLlmClient(
            {
                "intent": "action_priority",
                "capability": "ops_action_prioritization",
                "requires_tools": True,
                "tool_plans": [],
            }
        )
    )

    plan = planner.plan(
        chat_type="admin_copilot",
        message="관리자 Action 우선순위 정리해줘",
        user_id="admin-1",
    )

    assert plan.provider_name == "llm"
    assert plan.intent == "action_priority"
    assert plan.capability == "ops_action_prioritization"
    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_bnpl_summary",
        "get_credit_review_queue",
        "query_multi_cluster_prometheus",
        "get_scaling_summary",
        "get_overdue_summary",
        "search_overdue_users",
    ]


def test_llm_planner_maps_sre_capability_to_backend_tool_bundle() -> None:
    planner = LlmAgentPlanner(
        llm_client=FakePlannerLlmClient(
            {
                "intent": "routing_failure",
                "capability": "edge_routing_analysis",
                "requires_tools": True,
                "tool_plans": [],
            }
        )
    )

    plan = planner.plan(
        chat_type="sre_copilot",
        message="CloudFront ALB EKS 라우팅 실패 분석해줘",
        user_id="sre-1",
    )

    tool_names = [tool.tool_name for tool in plan.tool_plans]
    assert plan.provider_name == "llm"
    assert plan.intent == "routing_failure"
    assert plan.capability == "edge_routing_analysis"
    assert "get_cloudfront_origin_mapping" in tool_names
    assert "get_alb_target_health" in tool_names
    assert "get_service_routing_path" in tool_names
    assert "get_service_dependency_map" in tool_names
    assert all(tool.server_name == "infraops-mcp" for tool in plan.tool_plans)


def test_llm_planner_falls_back_when_supported_admin_request_skips_tools() -> None:
    planner = LlmAgentPlanner(
        llm_client=FakePlannerLlmClient(
            {
                "intent": "unsupported",
                "requires_tools": False,
                "direct_answer": (
                    "현재 Admin Copilot에서 해당 분석에 필요한 운영 데이터를 조회할 수 없습니다."
                ),
                "tool_plans": [],
            }
        )
    )

    plan = planner.plan(
        chat_type="admin_copilot",
        message="관리자 Action 우선순위 정리해줘",
        user_id="admin-1",
    )

    assert plan.provider_name == "llm_with_rule_fallback"
    assert plan.intent == "action_priority"
    assert plan.capability == "ops_action_prioritization"
    assert "skipped tools" in str(plan.planner_error)
    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_bnpl_summary",
        "get_credit_review_queue",
        "query_multi_cluster_prometheus",
        "get_scaling_summary",
        "get_overdue_summary",
        "search_overdue_users",
    ]


def test_dispatcher_executes_read_tool_and_masks_payload() -> None:
    dispatcher = McpToolDispatcher()

    result = dispatcher.execute(
        AgentToolPlan(
            server_name="farmer-bnpl-mcp",
            tool_name="get_user_credit_limit",
            request_payload={"user_id": FARMER_1_ID, "access_token": "secret-token"},
            reason="Check credit limit.",
        )
    )

    assert result.call_status == McpToolCallStatus.SUCCESS
    assert result.will_execute is True
    assert result.response_payload["available_limit"] == 2550000
    assert "access_token" not in result.request_payload
    assert "access_token" not in result.masked_request_payload


def test_dispatcher_executes_sre_infraops_read_tool() -> None:
    dispatcher = McpToolDispatcher(infraops_service=FakeInfraOpsService())

    result = dispatcher.execute(
        AgentToolPlan(
            server_name="infraops-mcp",
            tool_name="query_multi_cluster_loki",
            request_payload={"query": '{namespace="service-catalog"}', "limit": 50},
            reason="Read logs.",
        )
    )

    assert result.call_status == McpToolCallStatus.SUCCESS
    assert result.will_execute is True
    assert result.response_payload["query"] == '{namespace="service-catalog"}'
    assert result.response_payload["limit"] == 50


def test_dispatcher_executes_sre_topology_knowledge_tool() -> None:
    dispatcher = McpToolDispatcher(
        infraops_service=FakeInfraOpsService(),
        topology_knowledge_service=FakeTopologyKnowledgeService(),
    )

    result = dispatcher.execute(
        AgentToolPlan(
            server_name="infraops-mcp",
            tool_name="get_service_routing_path",
            request_payload={"service": "checkout", "environment": "all"},
            reason="Read topology routing path.",
        )
    )

    assert result.call_status == McpToolCallStatus.SUCCESS
    assert result.will_execute is True
    assert result.response_payload["service"] == "checkout"


def test_sre_orchestrator_enriches_rca_snapshot_with_context_bundle() -> None:
    dispatcher = RecordingDispatcher()
    orchestrator = AgentOrchestrator(
        planner=FakeSreRcaPlanner(),
        dispatcher=dispatcher,
    )

    result = orchestrator.run(
        chat_type="sre_copilot",
        message="checkout 500 장애 분석해줘",
        user_id="sre-1",
    )

    assert [plan.tool_name for plan in dispatcher.plans] == [
        "get_topology_snapshot",
        "query_multi_cluster_loki",
        "create_rca_snapshot",
    ]
    rca_payload = dispatcher.plans[-1].request_payload
    assert "context_bundle" in rca_payload
    bundle = rca_payload["context_bundle"]
    assert bundle["schema_version"] == "incident_context_bundle.v1"
    assert "snapshots" in bundle["topology"]
    assert "multi_cluster_loki" in bundle["observability"]["logs"]
    assert bundle["cross_domain"]["scenario"] == "edge_to_eks_routing"
    assert bundle["summary_for_llm"]["cross_domain_scenario"] == "edge_to_eks_routing"
    assert [candidate["boundary"] for candidate in bundle["failure_boundary_candidates"]] == [
        "cloudfront",
        "aws_alb",
        "aws_target_group",
        "eks_ingress",
        "k8s_service",
        "pod_application",
    ]
    assert result.tool_results[-1].tool_name == "create_rca_snapshot"


def test_incident_context_bundle_identifies_onprem_to_sqs_path() -> None:
    bundle = build_incident_context_bundle(
        chat_type="sre_copilot",
        message="pin event sqs publish failure",
        capability="sqs_publish_failure_analysis",
        tool_results=[
            make_sre_tool_result(
                "get_sqs_queue_attributes",
                {"queue_name": "pin-events", "health": "healthy"},
            ),
            make_sre_tool_result(
                "query_multi_cluster_loki",
                {"sources": [{"cluster": "onprem", "status": "ready"}]},
            ),
        ],
    )

    boundaries = {
        candidate["boundary"]: candidate
        for candidate in bundle["failure_boundary_candidates"]
    }
    assert bundle["cross_domain"]["scenario"] == "onprem_to_sqs"
    assert bundle["cross_domain"]["path"] == [
        "pod_application",
        "dns",
        "vpn_route",
        "aws_sqs",
    ]
    assert boundaries["aws_sqs"]["status"] == "healthy"
    assert boundaries["aws_sqs"]["evidence_tools"] == ["get_sqs_queue_attributes"]


def test_incident_context_bundle_marks_degraded_edge_boundary() -> None:
    bundle = build_incident_context_bundle(
        chat_type="sre_copilot",
        message="CloudFront ALB EKS routing failure",
        capability="edge_routing_analysis",
        tool_results=[
            make_sre_tool_result(
                "get_alb_target_health",
                {"target_health": [{"target": "pod-ip", "state": "unhealthy"}]},
            ),
            make_sre_tool_result(
                "get_cloudfront_distribution_status",
                {"distribution_id": "EDFDVBD6EXAMPLE", "status": "Deployed"},
            ),
        ],
    )

    boundaries = {
        candidate["boundary"]: candidate
        for candidate in bundle["failure_boundary_candidates"]
    }
    assert bundle["cross_domain"]["scenario"] == "edge_to_eks_routing"
    assert boundaries["cloudfront"]["status"] == "healthy"
    assert boundaries["aws_alb"]["status"] == "degraded"
    assert boundaries["aws_target_group"]["status"] == "degraded"


def test_incident_context_bundle_avoids_substring_health_matches() -> None:
    bundle = build_incident_context_bundle(
        chat_type="sre_copilot",
        message="CloudFront ALB EKS routing failure",
        capability="edge_routing_analysis",
        tool_results=[
            make_sre_tool_result(
                "get_alb_target_health",
                {"message": "download completed", "state": "initializing"},
            ),
        ],
    )

    boundaries = {
        candidate["boundary"]: candidate
        for candidate in bundle["failure_boundary_candidates"]
    }
    assert boundaries["aws_alb"]["status"] == "unknown"
    assert boundaries["aws_target_group"]["status"] == "unknown"


def test_incident_context_bundle_marks_not_ready_as_degraded() -> None:
    bundle = build_incident_context_bundle(
        chat_type="sre_copilot",
        message="CloudFront ALB EKS routing failure",
        capability="edge_routing_analysis",
        tool_results=[
            make_sre_tool_result(
                "get_alb_target_health",
                {"conditions": [{"type": "Ready", "reason": "NotReady"}]},
            ),
        ],
    )

    boundaries = {
        candidate["boundary"]: candidate
        for candidate in bundle["failure_boundary_candidates"]
    }
    assert boundaries["aws_alb"]["status"] == "degraded"
    assert boundaries["aws_target_group"]["status"] == "degraded"


def test_incident_context_bundle_keeps_empty_masked_payloads() -> None:
    tool_result = AgentToolExecutionResult(
        server_name="infraops-mcp",
        tool_name="get_alb_target_health",
        tool_permission=McpToolPermission.READ,
        confirmation_policy=McpConfirmationPolicy.NONE,
        execution_policy=McpExecutionPolicy.ALLOWED,
        call_status=McpToolCallStatus.SUCCESS,
        will_execute=True,
        requires_approval=False,
        is_blocked=False,
        request_payload={"authorization": "Bearer raw-token"},
        masked_request_payload={},
        response_payload={
            "target_health": [{"target": "pod-ip", "state": "unhealthy"}],
            "secret": "raw-secret",
        },
        masked_response_payload={},
    )

    bundle = build_incident_context_bundle(
        chat_type="sre_copilot",
        message="CloudFront ALB EKS routing failure",
        capability="edge_routing_analysis",
        tool_results=[tool_result],
    )

    alb_entry = bundle["live_state"]["aws"]["alb_target_health"][0]
    raw_entry = bundle["raw_tool_results"][0]
    boundaries = {
        candidate["boundary"]: candidate
        for candidate in bundle["failure_boundary_candidates"]
    }

    assert alb_entry["request_payload"] == {}
    assert alb_entry["response_payload"] == {}
    assert raw_entry["request_payload"] == {}
    assert boundaries["aws_alb"]["status"] == "unknown"
    assert "raw-token" not in str(bundle)
    assert "raw-secret" not in str(bundle)


def test_dispatcher_blocks_user_confirmed_write_tool() -> None:
    dispatcher = McpToolDispatcher()

    result = dispatcher.execute(
        AgentToolPlan(
            server_name="farmer-bnpl-mcp",
            tool_name="create_bnpl_checkout",
            request_payload={
                "user_id": FARMER_1_ID,
                "checkout_intent_id": "checkout-intent-preview",
            },
            reason="Checkout requires user confirmation.",
        )
    )

    assert result.call_status == McpToolCallStatus.APPROVAL_REQUIRED
    assert result.will_execute is False
    assert result.requires_approval is True
    assert result.response_payload["dry_run"] is True


def test_assistant_content_preserves_empty_llm_answer() -> None:
    assert resolve_assistant_content({"answer": ""}, "fallback answer") == ""


def test_admin_llm_failure_does_not_expose_internal_agent_fallback() -> None:
    content = resolve_assistant_content(
        {},
        "Agent executed 2 MCP tool checks for the Admin Copilot flow.",
        chat_type="admin_copilot",
        llm_run_status="FAILED",
        tool_results=[
            AgentToolExecutionResult(
                server_name="admin-riskops-mcp",
                tool_name="get_bnpl_summary",
                tool_permission=McpToolPermission.READ,
                confirmation_policy=McpConfirmationPolicy.NONE,
                execution_policy=McpExecutionPolicy.ALLOWED,
                call_status=McpToolCallStatus.SUCCESS,
                will_execute=True,
                requires_approval=False,
                is_blocked=False,
                request_payload={},
                response_payload={"active_users": 3, "used_amount": 7_350_000},
            )
        ],
    )

    assert "Agent executed" not in content
    assert "AI 요약 생성에 실패했습니다" in content
    assert "BNPL 활성 사용자 3명" in content


def test_farmer_llm_failure_returns_tool_based_fallback() -> None:
    content = resolve_assistant_content(
        {},
        "Agent executed 2 MCP tool checks for the Farmer BNPL flow.",
        chat_type="farmer_bnpl",
        llm_run_status="FAILED",
        tool_results=[
            AgentToolExecutionResult(
                server_name="farmer-bnpl-mcp",
                tool_name="get_user_credit_limit",
                tool_permission=McpToolPermission.READ,
                confirmation_policy=McpConfirmationPolicy.NONE,
                execution_policy=McpExecutionPolicy.ALLOWED,
                call_status=McpToolCallStatus.SUCCESS,
                will_execute=True,
                requires_approval=False,
                is_blocked=False,
                request_payload={},
                response_payload={"available_limit": 2_550_000},
            ),
            AgentToolExecutionResult(
                server_name="farmer-bnpl-mcp",
                tool_name="search_lowest_price_fertilizer",
                tool_permission=McpToolPermission.READ,
                confirmation_policy=McpConfirmationPolicy.NONE,
                execution_policy=McpExecutionPolicy.ALLOWED,
                call_status=McpToolCallStatus.SUCCESS,
                will_execute=True,
                requires_approval=False,
                is_blocked=False,
                request_payload={},
                response_payload={
                    "items": [{"name": "Organic 20kg fertilizer", "unit_price": 24000}]
                },
            ),
        ],
    )

    assert "Agent executed" not in content
    assert "조회는 완료했지만 AI 답변 생성에 실패했습니다" in content
    assert "2,550,000 KRW" in content
    assert "Organic 20kg fertilizer" in content


def test_farmer_greeting_direct_response_does_not_need_tools() -> None:
    response = build_direct_chat_response(chat_type="farmer_bnpl", message="안녕")

    assert response is not None
    assert response["intent"] == "greeting"
    assert "외상 한도" in response["answer"]
