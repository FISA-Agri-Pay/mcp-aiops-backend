from aiops_platform.agent.dispatcher import McpToolDispatcher
from aiops_platform.agent.planner import RuleBasedAgentPlanner
from aiops_platform.agent.schemas import AgentToolPlan
from aiops_platform.mcp.schemas import McpToolCallStatus
from tests.seed_constants import FARMER_1_ID


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
