from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from aiops_platform.admin_riskops.service import AdminRiskOpsService
from aiops_platform.agent.schemas import AgentToolExecutionResult, AgentToolPlan
from aiops_platform.farm_advisory.service import FarmAdvisoryService
from aiops_platform.farmer_bnpl.service import FarmerBnplService
from aiops_platform.mcp.masking import mask_payload
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.registry import list_mcp_tools
from aiops_platform.mcp.schemas import (
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolMetadata,
    McpToolPermission,
)
from aiops_platform.prediction_scaling.service import PredictionScalingService

ToolOperation = Callable[[dict[str, Any]], Any]
EXECUTION_CONTEXT_KEYS = {"access_token"}


class McpToolDispatcher:
    def __init__(
        self,
        *,
        farmer_bnpl_service: FarmerBnplService | None = None,
        farm_advisory_service: FarmAdvisoryService | None = None,
        admin_riskops_service: AdminRiskOpsService | None = None,
        prediction_scaling_service: PredictionScalingService | None = None,
    ) -> None:
        self._farmer_bnpl = farmer_bnpl_service or FarmerBnplService()
        self._farm_advisory = farm_advisory_service or FarmAdvisoryService()
        self._admin_riskops = admin_riskops_service or AdminRiskOpsService()
        self._prediction_scaling = prediction_scaling_service or PredictionScalingService()

    def execute(self, plan: AgentToolPlan) -> AgentToolExecutionResult:
        tool = resolve_registered_tool(
            server_name=plan.server_name,
            tool_name=plan.tool_name,
        )
        permission = McpToolPermission(tool.tool_permission)
        policy = resolve_tool_policy(permission)
        execution_policy = McpExecutionPolicy(policy.execution_policy)
        request_payload = dict(plan.request_payload)

        if execution_policy != McpExecutionPolicy.ALLOWED:
            return build_tool_result(
                tool=tool,
                request_payload=request_payload,
                response_payload={
                    "dry_run": True,
                    "reason": plan.reason,
                    "message": "Tool execution requires explicit confirmation or approval.",
                },
                call_status=McpToolCallStatus(policy.call_status),
                execution_policy=execution_policy,
            )

        operation = self._resolve_operation(plan.server_name, plan.tool_name)
        if operation is None:
            return build_tool_result(
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                execution_policy=execution_policy,
                error_message="Tool dispatcher is not connected for this MCP tool.",
            )

        try:
            response_payload = dump_payload(operation(strip_execution_context(request_payload)))
        except Exception as exc:
            return build_tool_result(
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                execution_policy=execution_policy,
                error_message=exc.__class__.__name__,
            )

        return build_tool_result(
            tool=tool,
            request_payload=request_payload,
            response_payload=response_payload,
            call_status=McpToolCallStatus.SUCCESS,
            execution_policy=execution_policy,
        )

    def _resolve_operation(self, server_name: str, tool_name: str) -> ToolOperation | None:
        operations: dict[tuple[str, str], ToolOperation] = {
            ("farmer-bnpl-mcp", "get_user_credit_limit"): (
                lambda payload: self._farmer_bnpl.get_user_credit_limit(**payload)
            ),
            ("farmer-bnpl-mcp", "get_farmer_profile"): (
                lambda payload: self._farmer_bnpl.get_farmer_profile(**payload)
            ),
            ("farmer-bnpl-mcp", "get_required_documents"): (
                lambda payload: self._farmer_bnpl.get_required_documents(**payload)
            ),
            ("farmer-bnpl-mcp", "get_repayment_schedule"): (
                lambda payload: self._farmer_bnpl.get_repayment_schedule(**payload)
            ),
            ("farmer-bnpl-mcp", "get_interest_due"): (
                lambda payload: self._farmer_bnpl.get_interest_due(**payload)
            ),
            ("farmer-bnpl-mcp", "get_overdue_status"): (
                lambda payload: self._farmer_bnpl.get_overdue_status(**payload)
            ),
            ("farmer-bnpl-mcp", "search_products"): (
                lambda payload: self._farmer_bnpl.search_products(**payload)
            ),
            ("farmer-bnpl-mcp", "search_lowest_price_fertilizer"): (
                lambda payload: self._farmer_bnpl.search_lowest_price_fertilizer(**payload)
            ),
            ("farmer-bnpl-mcp", "prepare_bnpl_checkout_payload"): (
                lambda payload: self._farmer_bnpl.prepare_bnpl_checkout_payload(**payload)
            ),
            ("farm-advisory-mcp", "recommend_fertilizer_requirements"): (
                lambda payload: self._farm_advisory.recommend_fertilizer_requirements(**payload)
            ),
            ("admin-riskops-mcp", "get_bnpl_summary"): (
                lambda payload: self._admin_riskops.get_bnpl_summary()
            ),
            ("admin-riskops-mcp", "get_credit_review_queue"): (
                lambda payload: self._admin_riskops.get_credit_review_queue(**payload)
            ),
            ("admin-riskops-mcp", "get_overdue_summary"): (
                lambda payload: self._admin_riskops.get_overdue_summary()
            ),
            ("admin-riskops-mcp", "search_overdue_users"): (
                lambda payload: self._admin_riskops.search_overdue_users(**payload)
            ),
            ("infraops-mcp", "query_multi_cluster_prometheus"): (
                lambda payload: build_multi_cluster_prometheus_stub(payload)
            ),
            ("prediction-scaling-mcp", "get_scaling_summary"): (
                lambda payload: self._prediction_scaling.get_scaling_summary(**payload)
            ),
        }
        return operations.get((server_name, tool_name))


def build_tool_result(
    *,
    tool: McpToolMetadata,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | list[Any] | None,
    call_status: McpToolCallStatus,
    execution_policy: McpExecutionPolicy,
    error_message: str | None = None,
) -> AgentToolExecutionResult:
    permission = McpToolPermission(tool.tool_permission)
    policy = resolve_tool_policy(permission)
    return AgentToolExecutionResult(
        server_name=tool.server_name,
        tool_name=tool.tool_name,
        tool_permission=permission,
        confirmation_policy=policy.confirmation_policy,
        execution_policy=execution_policy,
        call_status=call_status,
        will_execute=execution_policy == McpExecutionPolicy.ALLOWED
        and call_status == McpToolCallStatus.SUCCESS,
        requires_approval=call_status == McpToolCallStatus.APPROVAL_REQUIRED,
        is_blocked=call_status == McpToolCallStatus.BLOCKED,
        request_payload=request_payload,
        masked_request_payload=mask_payload(request_payload),
        response_payload=response_payload,
        masked_response_payload=mask_payload(response_payload),
        error_message=error_message,
    )


def dump_payload(value: Any) -> dict[str, Any] | list[Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict | list):
        return value
    return {"value": value}


def resolve_registered_tool(*, server_name: str, tool_name: str) -> McpToolMetadata:
    for tool in list_mcp_tools(server_name=server_name):
        if tool.tool_name == tool_name:
            return tool
    raise ValueError("MCP tool is not registered.")


def strip_execution_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in EXECUTION_CONTEXT_KEYS}


def build_multi_cluster_prometheus_stub(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query") or "up"
    return {
        "query": query,
        "sources": [
            {
                "source_name": "local-skeleton",
                "status": "SUCCESS",
                "result_count": 0,
                "error": None,
            }
        ],
        "summary": "Multi-cluster Prometheus execution is represented as a safe skeleton result.",
    }
