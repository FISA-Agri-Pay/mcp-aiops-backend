from aiops_platform.agent.dispatcher import McpToolDispatcher
from aiops_platform.agent.planner import (
    LlmAgentPlanner,
    RuleBasedAgentPlanner,
    classify_admin_copilot_intent,
    classify_farmer_bnpl_intent,
)
from aiops_platform.agent.schemas import AgentToolExecutionResult, AgentToolPlan
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)
from aiops_platform.llmops.client import LlmCompletionResponse
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
    assert plan.tool_plans == []


def test_rule_based_planner_selects_overdue_tools_for_admin_risk_question() -> None:
    planner = RuleBasedAgentPlanner()

    plan = planner.plan(
        chat_type="admin_copilot",
        message="연체 위험 고객 현황 알려줘",
        user_id="admin-1",
    )

    assert [tool.tool_name for tool in plan.tool_plans] == [
        "get_overdue_summary",
        "search_overdue_users",
        "search_bnpl_users",
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
