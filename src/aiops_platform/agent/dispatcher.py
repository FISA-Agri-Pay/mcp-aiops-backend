from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from pydantic import BaseModel

from aiops_platform.admin_riskops.service import AdminRiskOpsService
from aiops_platform.agent.schemas import AgentToolExecutionResult, AgentToolPlan
from aiops_platform.farm_advisory.service import FarmAdvisoryService
from aiops_platform.farmer_bnpl.service import FarmerBnplService
from aiops_platform.infraops.service import InfraOpsService
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
from aiops_platform.topology_knowledge.service import TopologyKnowledgeService

ToolOperation = Callable[[dict[str, Any]], Any]
EXECUTION_CONTEXT_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
}


class McpToolDispatcher:
    def __init__(
        self,
        *,
        farmer_bnpl_service: FarmerBnplService | None = None,
        farm_advisory_service: FarmAdvisoryService | None = None,
        admin_riskops_service: AdminRiskOpsService | None = None,
        infraops_service: InfraOpsService | None = None,
        prediction_scaling_service: PredictionScalingService | None = None,
        topology_knowledge_service: TopologyKnowledgeService | None = None,
    ) -> None:
        self._farmer_bnpl = farmer_bnpl_service or FarmerBnplService()
        self._farm_advisory = farm_advisory_service or FarmAdvisoryService()
        self._admin_riskops = admin_riskops_service or AdminRiskOpsService()
        self._infraops = infraops_service or InfraOpsService.from_settings()
        self._prediction_scaling = prediction_scaling_service or PredictionScalingService()
        self._topology_knowledge = (
            topology_knowledge_service or TopologyKnowledgeService.from_settings()
        )

    def execute(self, plan: AgentToolPlan) -> AgentToolExecutionResult:
        tool = resolve_registered_tool(
            server_name=plan.server_name,
            tool_name=plan.tool_name,
        )
        permission = McpToolPermission(tool.tool_permission)
        policy = resolve_tool_policy(permission)
        execution_policy = McpExecutionPolicy(policy.execution_policy)
        request_payload = dict(plan.request_payload)
        sanitized_payload = sanitize_execution_context(request_payload)

        if execution_policy != McpExecutionPolicy.ALLOWED:
            return build_tool_result(
                tool=tool,
                request_payload=sanitized_payload,
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
                request_payload=sanitized_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                execution_policy=execution_policy,
                error_message="Tool dispatcher is not connected for this MCP tool.",
            )

        try:
            response_payload = dump_payload(operation(sanitized_payload))
        except Exception as exc:
            return build_tool_result(
                tool=tool,
                request_payload=sanitized_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                execution_policy=execution_policy,
                error_message=exc.__class__.__name__,
            )

        return build_tool_result(
            tool=tool,
            request_payload=sanitized_payload,
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
            ("farmer-bnpl-mcp", "get_latest_order_delivery_status"): (
                lambda payload: self._farmer_bnpl.get_latest_order_delivery_status(**payload)
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
            ("admin-riskops-mcp", "get_credit_review_detail"): (
                lambda payload: self._admin_riskops.get_credit_review_detail(**payload)
            ),
            ("admin-riskops-mcp", "summarize_credit_risk"): (
                lambda payload: self._admin_riskops.summarize_credit_risk(**payload)
            ),
            ("admin-riskops-mcp", "get_overdue_summary"): (
                lambda payload: self._admin_riskops.get_overdue_summary()
            ),
            ("admin-riskops-mcp", "search_overdue_users"): (
                lambda payload: self._admin_riskops.search_overdue_users(**payload)
            ),
            ("admin-riskops-mcp", "search_bnpl_users"): (
                lambda payload: self._admin_riskops.search_bnpl_users(**payload)
            ),
            ("admin-riskops-mcp", "get_bss_score_history"): (
                lambda payload: self._admin_riskops.get_bss_score_history(**payload)
            ),
            ("admin-riskops-mcp", "simulate_disaster_credit_risk"): (
                lambda payload: self._admin_riskops.simulate_disaster_credit_risk(**payload)
            ),
            ("admin-riskops-mcp", "create_risk_analysis_snapshot"): (
                lambda payload: self._admin_riskops.create_risk_analysis_snapshot(**payload)
            ),
            ("admin-riskops-mcp", "send_repayment_alert"): (
                lambda payload: self._admin_riskops.send_repayment_alert(**payload)
            ),
            ("admin-riskops-mcp", "send_overdue_alerts"): (
                lambda payload: self._admin_riskops.send_overdue_alerts(**payload)
            ),
            ("infraops-mcp", "query_prometheus"): (
                lambda payload: self._infraops.query_prometheus(**payload)
            ),
            ("infraops-mcp", "query_loki"): (
                lambda payload: self._infraops.query_loki(**payload)
            ),
            ("infraops-mcp", "query_multi_cluster_prometheus"): (
                lambda payload: self._infraops.query_multi_cluster_prometheus(**payload)
            ),
            ("infraops-mcp", "query_multi_cluster_loki"): (
                lambda payload: self._infraops.query_multi_cluster_loki(**payload)
            ),
            ("infraops-mcp", "search_traces"): (
                lambda payload: self._infraops.search_traces(**payload)
            ),
            ("infraops-mcp", "get_trace_by_id"): (
                lambda payload: self._infraops.get_trace_by_id(**payload)
            ),
            ("infraops-mcp", "get_service_trace_summary"): (
                lambda payload: self._infraops.get_service_trace_summary(**payload)
            ),
            ("infraops-mcp", "get_trace_error_spans"): (
                lambda payload: self._infraops.get_trace_error_spans(**payload)
            ),
            ("infraops-mcp", "get_k8s_pods"): (
                lambda payload: self._infraops.get_k8s_pods(**payload)
            ),
            ("infraops-mcp", "get_k8s_events"): (
                lambda payload: self._infraops.get_k8s_events(**payload)
            ),
            ("infraops-mcp", "get_k8s_deployments"): (
                lambda payload: self._infraops.get_k8s_deployments(**payload)
            ),
            ("infraops-mcp", "get_k8s_hpa"): (
                lambda payload: self._infraops.get_k8s_hpa(**payload)
            ),
            ("infraops-mcp", "get_pod_logs"): (
                lambda payload: self._infraops.get_pod_logs(**payload)
            ),
            ("infraops-mcp", "get_rollout_status"): (
                lambda payload: self._infraops.get_rollout_status(**payload)
            ),
            ("infraops-mcp", "get_alertmanager_alerts"): (
                lambda payload: self._infraops.get_alertmanager_alerts(**payload)
            ),
            ("infraops-mcp", "get_sqs_queue_attributes"): (
                lambda payload: self._infraops.get_sqs_queue_attributes(**payload)
            ),
            ("infraops-mcp", "get_sqs_dlq_attributes"): (
                lambda payload: self._infraops.get_sqs_dlq_attributes(**payload)
            ),
            ("infraops-mcp", "get_alb_target_health"): (
                lambda payload: self._infraops.get_alb_target_health(**payload)
            ),
            ("infraops-mcp", "get_cloudfront_origin_mapping"): (
                lambda payload: self._infraops.get_cloudfront_origin_mapping(**payload)
            ),
            ("infraops-mcp", "get_cloudfront_distribution_status"): (
                lambda payload: self._infraops.get_cloudfront_distribution_status(**payload)
            ),
            ("infraops-mcp", "get_argocd_application_status"): (
                lambda payload: self._infraops.get_argocd_application_status(**payload)
            ),
            ("infraops-mcp", "get_current_image_tags"): (
                lambda payload: self._infraops.get_current_image_tags(**payload)
            ),
            ("infraops-mcp", "get_recent_deployments"): (
                lambda payload: self._infraops.get_recent_deployments(**payload)
            ),
            ("infraops-mcp", "get_topology_snapshot"): (
                lambda payload: self._topology_knowledge.get_topology_snapshot(**payload)
            ),
            ("infraops-mcp", "search_topology_knowledge"): (
                lambda payload: self._topology_knowledge.search_topology_knowledge(**payload)
            ),
            ("infraops-mcp", "get_service_routing_path"): (
                lambda payload: self._topology_knowledge.get_service_routing_path(**payload)
            ),
            ("infraops-mcp", "get_service_dependency_map"): (
                lambda payload: self._topology_knowledge.get_service_dependency_map(**payload)
            ),
            ("infraops-mcp", "create_rca_snapshot"): (
                lambda payload: self._infraops.create_rca_snapshot(**payload)
            ),
            ("infraops-mcp", "search_incidents"): (
                lambda payload: self._infraops.search_incidents(**payload)
            ),
            ("infraops-mcp", "search_rca_history"): (
                lambda payload: self._infraops.search_rca_history(**payload)
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


def sanitize_execution_context(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_payload(deepcopy(payload))


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_payload(item)
            for key, item in value.items()
            if key.lower() not in EXECUTION_CONTEXT_KEYS
        }
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    return value
