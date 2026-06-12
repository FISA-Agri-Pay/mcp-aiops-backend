from __future__ import annotations

from aiops_platform.agent.context_bundle import build_incident_context_bundle
from aiops_platform.agent.dispatcher import McpToolDispatcher
from aiops_platform.agent.planner import AgentPlanner, LlmAgentPlanner
from aiops_platform.agent.schemas import AgentRunResult, AgentToolPlan
from aiops_platform.orchestration.schemas import ChatType


class AgentOrchestrator:
    def __init__(
        self,
        *,
        planner: AgentPlanner | None = None,
        dispatcher: McpToolDispatcher | None = None,
    ) -> None:
        self._planner = planner or LlmAgentPlanner()
        self._dispatcher = dispatcher or McpToolDispatcher()

    def run(self, *, chat_type: ChatType, message: str, user_id: str) -> AgentRunResult:
        plan = self._planner.plan(chat_type=chat_type, message=message, user_id=user_id)
        if plan.direct_answer is not None and not plan.tool_plans:
            return AgentRunResult(
                provider_name=plan.provider_name,
                answer=plan.direct_answer,
                tool_results=[],
                intent=plan.intent,
                capability=plan.capability,
                is_direct_response=True,
                planner_error=plan.planner_error,
            )
        tool_results = []
        deferred_rca_plans: list[AgentToolPlan] = []
        for tool_plan in plan.tool_plans:
            if (
                chat_type == "sre_copilot"
                and tool_plan.server_name == "infraops-mcp"
                and tool_plan.tool_name == "create_rca_snapshot"
            ):
                deferred_rca_plans.append(tool_plan)
                continue
            tool_results.append(self._dispatcher.execute(tool_plan))

        for tool_plan in deferred_rca_plans:
            context_bundle = build_incident_context_bundle(
                chat_type=chat_type,
                message=message,
                capability=plan.capability,
                tool_results=tool_results,
            )
            enriched_payload = {
                **tool_plan.request_payload,
                "context_bundle": context_bundle,
            }
            tool_results.append(
                self._dispatcher.execute(
                    tool_plan.model_copy(update={"request_payload": enriched_payload})
                )
            )

        return AgentRunResult(
            provider_name=plan.provider_name,
            answer=build_agent_answer(chat_type=chat_type, tool_count=len(tool_results)),
            tool_results=tool_results,
            intent=plan.intent,
            capability=plan.capability,
            is_direct_response=False,
            planner_error=plan.planner_error,
        )


def build_agent_answer(*, chat_type: ChatType, tool_count: int) -> str:
    if chat_type == "farmer_bnpl":
        return (
            f"Agent executed {tool_count} MCP tool checks for the Farmer BNPL flow. "
            "Review tool_results for credit limit, profile, recommendation, and checkout details."
        )
    if chat_type == "sre_copilot":
        return (
            f"Agent executed {tool_count} MCP tool checks for the SRE Copilot flow. "
            "Review tool_results for logs, metrics, traces, Kubernetes, AWS, and GitOps evidence."
        )
    return (
        f"Agent executed {tool_count} MCP tool checks for the Admin Copilot flow. "
        "Review tool_results for risk, observability, and scaling evidence."
    )
