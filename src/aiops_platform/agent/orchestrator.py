from __future__ import annotations

from aiops_platform.agent.dispatcher import McpToolDispatcher
from aiops_platform.agent.planner import AgentPlanner, RuleBasedAgentPlanner
from aiops_platform.agent.schemas import AgentRunResult
from aiops_platform.orchestration.schemas import ChatType


class AgentOrchestrator:
    def __init__(
        self,
        *,
        planner: AgentPlanner | None = None,
        dispatcher: McpToolDispatcher | None = None,
    ) -> None:
        self._planner = planner or RuleBasedAgentPlanner()
        self._dispatcher = dispatcher or McpToolDispatcher()

    def run(self, *, chat_type: ChatType, message: str, user_id: str) -> AgentRunResult:
        plan = self._planner.plan(chat_type=chat_type, message=message, user_id=user_id)
        tool_results = [self._dispatcher.execute(tool_plan) for tool_plan in plan.tool_plans]
        return AgentRunResult(
            provider_name=plan.provider_name,
            answer=build_agent_answer(chat_type=chat_type, tool_count=len(tool_results)),
            tool_results=tool_results,
        )


def build_agent_answer(*, chat_type: ChatType, tool_count: int) -> str:
    if chat_type == "farmer_bnpl":
        return (
            f"Agent executed {tool_count} MCP tool checks for the Farmer BNPL flow. "
            "Review tool_results for credit limit, profile, recommendation, and checkout details."
        )
    return (
        f"Agent executed {tool_count} MCP tool checks for the Admin Copilot flow. "
        "Review tool_results for risk, observability, and scaling evidence."
    )

