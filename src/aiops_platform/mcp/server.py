import logging
from collections.abc import Callable
from time import perf_counter
from typing import Any

from fastmcp import FastMCP

from aiops_platform.farmer_bnpl.service import FarmerBnplService
from aiops_platform.infraops.service import InfraOpsService
from aiops_platform.mcp.audit import McpToolAuditService, elapsed_ms
from aiops_platform.mcp.policy import resolve_tool_policy
from aiops_platform.mcp.registry import list_mcp_servers, list_mcp_tools
from aiops_platform.mcp.schemas import (
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolExecutionContext,
    McpToolMetadata,
    McpToolPermission,
)

MCP_TRANSPORT_MOUNT_PATH = "/mcp-server"
MCP_TRANSPORT_PATH = "/mcp"
logger = logging.getLogger(__name__)


def _permission_from_query(permission: str | None) -> McpToolPermission | None:
    if permission is None:
        return None
    return McpToolPermission(permission)


def _resolve_registered_tool(server_name: str | None, tool_name: str) -> McpToolMetadata:
    matches = [
        tool
        for tool in list_mcp_tools(server_name=server_name)
        if tool.tool_name == tool_name
    ]
    if not matches:
        raise ValueError("MCP tool is not registered.")
    if len(matches) > 1:
        raise ValueError("server_name is required for duplicated tool names.")
    return matches[0]


def _policy_response(tool: McpToolMetadata) -> dict[str, Any]:
    permission = McpToolPermission(tool.tool_permission)
    policy = resolve_tool_policy(permission)
    return {
        "server_name": tool.server_name,
        "tool_name": tool.tool_name,
        "tool_permission": policy.tool_permission,
        "confirmation_policy": policy.confirmation_policy,
        "execution_policy": policy.execution_policy,
        "call_status": policy.call_status,
    }


def _policy_preview_response(
    tool: McpToolMetadata,
    preview_payload: dict[str, Any],
) -> dict[str, Any]:
    policy = resolve_tool_policy(McpToolPermission(tool.tool_permission))
    return {
        **_policy_response(tool),
        "will_execute": False,
        "requires_approval": (
            McpExecutionPolicy(policy.execution_policy)
            == McpExecutionPolicy.BLOCKED_UNTIL_APPROVED
        ),
        "is_blocked": (
            McpExecutionPolicy(policy.execution_policy) == McpExecutionPolicy.BLOCKED
        ),
        "preview": preview_payload,
    }


def _record_tool_audit(
    *,
    audit_service: McpToolAuditService | None,
    tool: McpToolMetadata,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any] | list[Any] | None,
    call_status: McpToolCallStatus,
    started_at: float,
    last_error: str | None = None,
) -> None:
    if audit_service is None:
        return

    permission = McpToolPermission(tool.tool_permission)
    try:
        audit_service.record_tool_call(
            context=McpToolExecutionContext(
                server_name=tool.server_name,
                tool_name=tool.tool_name,
                request_payload=request_payload,
            ),
            permission=permission,
            response_payload=response_payload,
            call_status=call_status,
            latency_ms=elapsed_ms(started_at),
            last_error=last_error,
        )
    except Exception:
        logger.exception("Failed to record MCP tool audit log.")


def create_mcp_server(
    audit_service: McpToolAuditService | None = None,
    farmer_bnpl_service: FarmerBnplService | None = None,
    infraops_service: InfraOpsService | None = None,
) -> FastMCP:
    farmer_bnpl = farmer_bnpl_service or FarmerBnplService()
    infraops = infraops_service or InfraOpsService.from_settings()
    mcp = FastMCP(
        name="aiops-platform-mcp",
        instructions="Use the registry tools to discover allowed AIOps MCP capabilities.",
        on_duplicate_tools="error",
    )

    @mcp.tool(
        name="list_mcp_servers",
        description="List registered AIOps MCP servers from the curated registry.",
        tags={"registry", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def list_servers_tool() -> list[dict[str, Any]]:
        return [server.model_dump(mode="json") for server in list_mcp_servers()]

    @mcp.tool(
        name="list_mcp_tools",
        description="List registered AIOps MCP tools, optionally filtered by server or permission.",
        tags={"registry", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def list_tools_tool(
        server_name: str | None = None,
        permission: str | None = None,
    ) -> list[dict[str, Any]]:
        return [
            tool.model_dump(mode="json")
            for tool in list_mcp_tools(
                server_name=server_name,
                permission=_permission_from_query(permission),
            )
        ]

    @mcp.tool(
        name="get_mcp_tool_policy",
        description="Resolve the confirmation and execution policy for a registered MCP tool.",
        tags={"registry", "policy", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_tool_policy_tool(
        tool_name: str,
        server_name: str | None = None,
    ) -> dict[str, Any]:
        tool = _resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        return _policy_response(tool)

    @mcp.tool(
        name="preview_mcp_tool_execution",
        description="Preview policy and audit status for a registered MCP tool execution.",
        tags={"registry", "policy", "audit", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def preview_tool_execution(
        tool_name: str,
        server_name: str,
        request_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool(server_name=server_name, tool_name=tool_name)
        permission = McpToolPermission(tool.tool_permission)
        policy = resolve_tool_policy(permission)
        response = {
            **_policy_response(tool),
            "will_execute": (
                McpExecutionPolicy(policy.execution_policy) == McpExecutionPolicy.ALLOWED
            ),
        }

        if audit_service is not None:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload or {},
                response_payload=response,
                call_status=McpToolCallStatus(policy.call_status),
                started_at=started_at,
            )

        return response

    def call_farmer_bnpl_tool(
        *,
        tool_name: str,
        request_payload: dict[str, Any],
        operation: Callable[[], Any],
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("farmer-bnpl-mcp", tool_name)
        permission = McpToolPermission(tool.tool_permission)
        policy = resolve_tool_policy(permission)

        try:
            result_payload = operation().model_dump(mode="json")
            if McpExecutionPolicy(policy.execution_policy) == McpExecutionPolicy.ALLOWED:
                response = result_payload
            else:
                response = _policy_preview_response(tool, result_payload)
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=response,
            call_status=McpToolCallStatus(policy.call_status),
            started_at=started_at,
        )
        return response

    @mcp.tool(
        name="start_credit_application",
        description="Create a dry-run BNPL credit application draft for a farmer.",
        tags={"farmer-bnpl", "credit", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def start_credit_application_tool(
        user_id: str,
        requested_amount: int,
        crop_type: str | None = None,
        season: str | None = None,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "requested_amount": requested_amount,
            "crop_type": crop_type,
            "season": season,
        }
        return call_farmer_bnpl_tool(
            tool_name="start_credit_application",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.start_credit_application(**request_payload),
        )

    @mcp.tool(
        name="save_farmland_info",
        description="Prepare a farmer farmland information draft.",
        tags={"farmer-bnpl", "profile", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def save_farmland_info_tool(
        user_id: str,
        location: str,
        area_hectare: float,
        ownership_type: str,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "location": location,
            "area_hectare": area_hectare,
            "ownership_type": ownership_type,
        }
        return call_farmer_bnpl_tool(
            tool_name="save_farmland_info",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.save_farmland_info(**request_payload),
        )

    @mcp.tool(
        name="save_crop_info",
        description="Prepare a farmer crop information draft.",
        tags={"farmer-bnpl", "profile", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def save_crop_info_tool(
        user_id: str,
        crop_type: str,
        expected_yield_kg: int | None = None,
        expected_revenue: int | None = None,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "crop_type": crop_type,
            "expected_yield_kg": expected_yield_kg,
            "expected_revenue": expected_revenue,
        }
        return call_farmer_bnpl_tool(
            tool_name="save_crop_info",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.save_crop_info(**request_payload),
        )

    @mcp.tool(
        name="save_insurance_info",
        description="Prepare a farmer crop insurance information draft.",
        tags={"farmer-bnpl", "profile", "insurance", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def save_insurance_info_tool(
        user_id: str,
        provider: str,
        policy_number: str | None = None,
        coverage_amount: int | None = None,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "provider": provider,
            "policy_number": policy_number,
            "coverage_amount": coverage_amount,
        }
        return call_farmer_bnpl_tool(
            tool_name="save_insurance_info",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.save_insurance_info(**request_payload),
        )

    @mcp.tool(
        name="get_required_documents",
        description="List required documents for a farmer BNPL credit application.",
        tags={"farmer-bnpl", "credit", "documents", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_required_documents_tool(
        user_id: str,
        application_type: str = "credit_application",
    ) -> dict[str, Any]:
        request_payload = {"user_id": user_id, "application_type": application_type}
        return call_farmer_bnpl_tool(
            tool_name="get_required_documents",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_required_documents(**request_payload),
        )

    @mcp.tool(
        name="submit_credit_documents",
        description="Prepare a credit document submission draft.",
        tags={"farmer-bnpl", "credit", "documents", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def submit_credit_documents_tool(
        user_id: str,
        application_id: str,
        document_types: list[str],
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "application_id": application_id,
            "document_types": document_types,
        }
        return call_farmer_bnpl_tool(
            tool_name="submit_credit_documents",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.submit_credit_documents(**request_payload),
        )

    @mcp.tool(
        name="get_credit_limit_status",
        description="Read the skeleton credit limit review status.",
        tags={"farmer-bnpl", "credit", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_credit_limit_status_tool(
        user_id: str,
        application_id: str | None = None,
    ) -> dict[str, Any]:
        request_payload = {"user_id": user_id, "application_id": application_id}
        return call_farmer_bnpl_tool(
            tool_name="get_credit_limit_status",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_credit_limit_status(**request_payload),
        )

    @mcp.tool(
        name="get_user_credit_limit",
        description="Read the user's skeleton BNPL credit limit.",
        tags={"farmer-bnpl", "credit", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_user_credit_limit_tool(user_id: str) -> dict[str, Any]:
        request_payload = {"user_id": user_id}
        return call_farmer_bnpl_tool(
            tool_name="get_user_credit_limit",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_user_credit_limit(**request_payload),
        )

    @mcp.tool(
        name="get_farmer_profile",
        description="Read the farmer profile summary used by the BNPL chatbot.",
        tags={"farmer-bnpl", "profile", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_farmer_profile_tool(user_id: str) -> dict[str, Any]:
        request_payload = {"user_id": user_id}
        return call_farmer_bnpl_tool(
            tool_name="get_farmer_profile",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_farmer_profile(**request_payload),
        )

    @mcp.tool(
        name="get_repayment_schedule",
        description="Read the user's skeleton BNPL repayment schedule.",
        tags={"farmer-bnpl", "repayment", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_repayment_schedule_tool(user_id: str) -> dict[str, Any]:
        request_payload = {"user_id": user_id}
        return call_farmer_bnpl_tool(
            tool_name="get_repayment_schedule",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_repayment_schedule(**request_payload),
        )

    @mcp.tool(
        name="get_interest_due",
        description="Read the next BNPL interest due amount.",
        tags={"farmer-bnpl", "repayment", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_interest_due_tool(user_id: str) -> dict[str, Any]:
        request_payload = {"user_id": user_id}
        return call_farmer_bnpl_tool(
            tool_name="get_interest_due",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_interest_due(**request_payload),
        )

    @mcp.tool(
        name="get_overdue_status",
        description="Read the user's skeleton overdue status.",
        tags={"farmer-bnpl", "repayment", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_overdue_status_tool(user_id: str) -> dict[str, Any]:
        request_payload = {"user_id": user_id}
        return call_farmer_bnpl_tool(
            tool_name="get_overdue_status",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_overdue_status(**request_payload),
        )

    @mcp.tool(
        name="search_products",
        description="Search the skeleton agricultural input catalog.",
        tags={"farmer-bnpl", "products", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def search_products_tool(
        query: str | None = None,
        category: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        request_payload = {"query": query, "category": category, "limit": limit}
        return call_farmer_bnpl_tool(
            tool_name="search_products",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.search_products(**request_payload),
        )

    @mcp.tool(
        name="search_lowest_price_fertilizer",
        description="Search the lowest-priced fertilizer items in the skeleton catalog.",
        tags={"farmer-bnpl", "products", "fertilizer", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def search_lowest_price_fertilizer_tool(limit: int = 5) -> dict[str, Any]:
        request_payload = {"limit": limit}
        return call_farmer_bnpl_tool(
            tool_name="search_lowest_price_fertilizer",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.search_lowest_price_fertilizer(**request_payload),
        )

    @mcp.tool(
        name="get_product_detail",
        description="Read a skeleton agricultural input product detail.",
        tags={"farmer-bnpl", "products", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_product_detail_tool(product_id: str) -> dict[str, Any]:
        request_payload = {"product_id": product_id}
        return call_farmer_bnpl_tool(
            tool_name="get_product_detail",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.get_product_detail(**request_payload),
        )

    @mcp.tool(
        name="calculate_cart_total",
        description="Calculate a skeleton cart total for BNPL eligibility checks.",
        tags={"farmer-bnpl", "cart", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def calculate_cart_total_tool(items: list[dict[str, Any]]) -> dict[str, Any]:
        request_payload = {"items": items}
        return call_farmer_bnpl_tool(
            tool_name="calculate_cart_total",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.calculate_cart_total(**request_payload),
        )

    @mcp.tool(
        name="prepare_bnpl_checkout_payload",
        description="Prepare a dry-run BNPL checkout payload from cart items.",
        tags={"farmer-bnpl", "checkout", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def prepare_bnpl_checkout_payload_tool(
        user_id: str,
        items: list[dict[str, Any]],
        credit_limit_id: str | None = None,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "items": items,
            "credit_limit_id": credit_limit_id,
        }
        return call_farmer_bnpl_tool(
            tool_name="prepare_bnpl_checkout_payload",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.prepare_bnpl_checkout_payload(**request_payload),
        )

    @mcp.tool(
        name="create_checkout_intent",
        description="Create a dry-run checkout intent that still requires user confirmation.",
        tags={"farmer-bnpl", "checkout", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def create_checkout_intent_tool(
        user_id: str,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        request_payload = {"user_id": user_id, "items": items}
        return call_farmer_bnpl_tool(
            tool_name="create_checkout_intent",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.create_checkout_intent(**request_payload),
        )

    @mcp.tool(
        name="add_cart_item",
        description="Prepare a cart item add draft.",
        tags={"farmer-bnpl", "cart", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def add_cart_item_tool(
        user_id: str,
        product_id: str,
        quantity: int,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "product_id": product_id,
            "quantity": quantity,
        }
        return call_farmer_bnpl_tool(
            tool_name="add_cart_item",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.add_cart_item(**request_payload),
        )

    @mcp.tool(
        name="update_cart_item",
        description="Prepare a cart item quantity update draft.",
        tags={"farmer-bnpl", "cart", "write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def update_cart_item_tool(
        user_id: str,
        product_id: str,
        quantity: int,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "product_id": product_id,
            "quantity": quantity,
        }
        return call_farmer_bnpl_tool(
            tool_name="update_cart_item",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.update_cart_item(**request_payload),
        )

    @mcp.tool(
        name="create_bnpl_checkout",
        description="Prepare the final BNPL checkout action that requires user confirmation.",
        tags={"farmer-bnpl", "checkout", "user-confirmed-write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def create_bnpl_checkout_tool(
        user_id: str,
        checkout_intent_id: str,
        confirmation_token: str | None = None,
    ) -> dict[str, Any]:
        request_payload = {
            "user_id": user_id,
            "checkout_intent_id": checkout_intent_id,
            "confirmation_token": confirmation_token,
        }
        return call_farmer_bnpl_tool(
            tool_name="create_bnpl_checkout",
            request_payload=request_payload,
            operation=lambda: farmer_bnpl.create_bnpl_checkout(**request_payload),
        )

    @mcp.tool(
        name="query_prometheus",
        description="Run an instant PromQL query through infraops-mcp.",
        tags={"infraops", "prometheus", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def query_prometheus_tool(query: str, time: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "query_prometheus")
        request_payload = {"query": query, "time": time}

        try:
            result = infraops.query_prometheus(query=query, time=time).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="query_loki",
        description="Run a Loki query_range log query through infraops-mcp.",
        tags={"infraops", "loki", "logs", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def query_loki_tool(
        query: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "query_loki")
        request_payload = {"query": query, "start": start, "end": end, "limit": limit}

        try:
            result = infraops.query_loki(
                query=query,
                start=start,
                end=end,
                limit=limit,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_k8s_pods",
        description="Read Kubernetes pods from an allowlisted namespace through infraops-mcp.",
        tags={"infraops", "kubernetes", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_k8s_pods_tool(namespace: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_k8s_pods")
        request_payload = {"namespace": namespace}

        try:
            result = infraops.get_k8s_pods(namespace=namespace).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_k8s_events",
        description="Read Kubernetes events from an allowlisted namespace through infraops-mcp.",
        tags={"infraops", "kubernetes", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_k8s_events_tool(namespace: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_k8s_events")
        request_payload = {"namespace": namespace}

        try:
            result = infraops.get_k8s_events(namespace=namespace).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_k8s_deployments",
        description="Read Kubernetes deployments from an allowlisted namespace.",
        tags={"infraops", "kubernetes", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_k8s_deployments_tool(namespace: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_k8s_deployments")
        request_payload = {"namespace": namespace}

        try:
            result = infraops.get_k8s_deployments(namespace=namespace).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_k8s_hpa",
        description="Read Kubernetes HPA objects from an allowlisted namespace.",
        tags={"infraops", "kubernetes", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_k8s_hpa_tool(namespace: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_k8s_hpa")
        request_payload = {"namespace": namespace}

        try:
            result = infraops.get_k8s_hpa(namespace=namespace).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_kafka_consumer_lag",
        description="Read Kafka consumer group lag through infraops-mcp.",
        tags={"infraops", "kafka", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_kafka_consumer_lag_tool(
        consumer_group: str,
        topic: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_kafka_consumer_lag")
        request_payload = {"consumer_group": consumer_group, "topic": topic}

        try:
            result = infraops.get_kafka_consumer_lag(
                consumer_group=consumer_group,
                topic=topic,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_batch_run_status",
        description="Read batch run status through infraops-mcp.",
        tags={"infraops", "batch", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_batch_run_status_tool(job_name: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_batch_run_status")
        request_payload = {"job_name": job_name}

        try:
            result = infraops.get_batch_run_status(job_name=job_name).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="scale_deployment",
        description="Preview a Kubernetes deployment scale request without executing it.",
        tags={"infraops", "kubernetes", "ops-write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def scale_deployment_tool(
        deployment_name: str,
        replicas: int,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "scale_deployment")
        request_payload = {
            "deployment_name": deployment_name,
            "replicas": replicas,
            "namespace": namespace,
        }

        try:
            preview = infraops.preview_scale_deployment(
                deployment_name=deployment_name,
                replicas=replicas,
                namespace=namespace,
            ).model_dump(mode="json")
            response = _policy_preview_response(tool, preview)
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=response,
            call_status=McpToolCallStatus.APPROVAL_REQUIRED,
            started_at=started_at,
        )
        return response

    @mcp.tool(
        name="restart_pod",
        description="Preview a Kubernetes pod restart request without executing it.",
        tags={"infraops", "kubernetes", "ops-write", "preview"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def restart_pod_tool(
        pod_name: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "restart_pod")
        request_payload = {"pod_name": pod_name, "namespace": namespace}

        try:
            preview = infraops.preview_restart_pod(
                pod_name=pod_name,
                namespace=namespace,
            ).model_dump(mode="json")
            response = _policy_preview_response(tool, preview)
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=response,
            call_status=McpToolCallStatus.APPROVAL_REQUIRED,
            started_at=started_at,
        )
        return response

    @mcp.tool(
        name="delete_pod",
        description="Return the blocked policy preview for a Kubernetes pod delete request.",
        tags={"infraops", "kubernetes", "destructive", "blocked"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def delete_pod_tool(
        pod_name: str,
        namespace: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "delete_pod")
        request_payload = {"pod_name": pod_name, "namespace": namespace}

        try:
            preview = infraops.preview_delete_pod(
                pod_name=pod_name,
                namespace=namespace,
            ).model_dump(mode="json")
            response = _policy_preview_response(tool, preview)
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=response,
            call_status=McpToolCallStatus.BLOCKED,
            started_at=started_at,
        )
        return response

    @mcp.tool(
        name="run_kubectl_exec",
        description="Return the blocked policy preview for a Kubernetes exec request.",
        tags={"infraops", "kubernetes", "destructive", "blocked"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def run_kubectl_exec_tool(
        pod_name: str,
        command: list[str],
        namespace: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "run_kubectl_exec")
        request_payload = {
            "pod_name": pod_name,
            "command": command,
            "namespace": namespace,
        }

        try:
            preview = infraops.preview_kubectl_exec(
                pod_name=pod_name,
                command=command,
                namespace=namespace,
            ).model_dump(mode="json")
            response = _policy_preview_response(tool, preview)
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=response,
            call_status=McpToolCallStatus.BLOCKED,
            started_at=started_at,
        )
        return response

    @mcp.tool(
        name="query_elasticsearch",
        description="Run an allowlisted Elasticsearch search query through infraops-mcp.",
        tags={"infraops", "elasticsearch", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def query_elasticsearch_tool(index_pattern: str, query: dict[str, Any]) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "query_elasticsearch")
        request_payload = {"index_pattern": index_pattern, "query": query}

        try:
            result = infraops.query_elasticsearch(
                index_pattern=index_pattern,
                query=query,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="search_elasticsearch_logs",
        description="Search allowlisted Elasticsearch log indices through infraops-mcp.",
        tags={"infraops", "elasticsearch", "logs", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def search_elasticsearch_logs_tool(
        query: str,
        index_pattern: str | None = None,
        size: int = 10,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "search_elasticsearch_logs")
        request_payload = {"query": query, "index_pattern": index_pattern, "size": size}

        try:
            result = infraops.search_elasticsearch_logs(
                query=query,
                index_pattern=index_pattern,
                size=size,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_elasticsearch_cluster_health",
        description="Read Elasticsearch cluster health through infraops-mcp.",
        tags={"infraops", "elasticsearch", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_elasticsearch_cluster_health_tool() -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_elasticsearch_cluster_health")

        try:
            result = infraops.get_elasticsearch_cluster_health().model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload={},
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload={},
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_elasticsearch_index_health",
        description="Read allowlisted Elasticsearch index health through infraops-mcp.",
        tags={"infraops", "elasticsearch", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_elasticsearch_index_health_tool(index_pattern: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_elasticsearch_index_health")
        request_payload = {"index_pattern": index_pattern}

        try:
            result = infraops.get_elasticsearch_index_health(
                index_pattern=index_pattern,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="get_kibana_saved_objects",
        description="List Kibana saved objects through infraops-mcp.",
        tags={"infraops", "kibana", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def get_kibana_saved_objects_tool(
        saved_object_type: str = "dashboard",
        search: str | None = None,
        per_page: int = 20,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "get_kibana_saved_objects")
        request_payload = {
            "saved_object_type": saved_object_type,
            "search": search,
            "per_page": per_page,
        }

        try:
            result = infraops.get_kibana_saved_objects(
                saved_object_type=saved_object_type,
                search=search,
                per_page=per_page,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="create_elk_snapshot",
        description="Create a read-only ELK health snapshot through infraops-mcp.",
        tags={"infraops", "elasticsearch", "kibana", "snapshot", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def create_elk_snapshot_tool(index_pattern: str | None = None) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "create_elk_snapshot")
        request_payload = {"index_pattern": index_pattern}

        try:
            result = infraops.create_elk_snapshot(
                index_pattern=index_pattern,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="create_rca_snapshot",
        description="Create a read-only RCA evidence snapshot from infraops sources.",
        tags={"infraops", "rca", "snapshot", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def create_rca_snapshot_tool(
        incident_key: str | None = None,
        namespace: str | None = None,
        index_pattern: str | None = None,
        prometheus_query: str = "up",
        loki_query: str = '{job=~".+"}',
        loki_limit: int = 100,
        kafka_consumer_group: str | None = None,
        kafka_topic: str | None = None,
        batch_job_name: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "create_rca_snapshot")
        request_payload = {
            "incident_key": incident_key,
            "namespace": namespace,
            "index_pattern": index_pattern,
            "prometheus_query": prometheus_query,
            "loki_query": loki_query,
            "loki_limit": loki_limit,
            "kafka_consumer_group": kafka_consumer_group,
            "kafka_topic": kafka_topic,
            "batch_job_name": batch_job_name,
        }

        try:
            result = infraops.create_rca_snapshot(**request_payload).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="aggregate_daily_ops_metrics",
        description="Aggregate a read-only daily operations metrics summary.",
        tags={"infraops", "metrics", "report", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def aggregate_daily_ops_metrics_tool(
        report_date: str | None = None,
        namespace: str | None = None,
        index_pattern: str | None = None,
        prometheus_query: str = "up",
        kafka_consumer_group: str | None = None,
        kafka_topic: str | None = None,
        batch_job_name: str | None = None,
    ) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "aggregate_daily_ops_metrics")
        request_payload = {
            "report_date": report_date,
            "namespace": namespace,
            "index_pattern": index_pattern,
            "prometheus_query": prometheus_query,
            "kafka_consumer_group": kafka_consumer_group,
            "kafka_topic": kafka_topic,
            "batch_job_name": batch_job_name,
        }

        try:
            result = infraops.aggregate_daily_ops_metrics(**request_payload).model_dump(
                mode="json"
            )
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="search_incidents",
        description="Search incident records through the infraops read-only interface.",
        tags={"infraops", "incidents", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def search_incidents_tool(query: str | None = None, limit: int = 20) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "search_incidents")
        request_payload = {"query": query, "limit": limit}

        try:
            result = infraops.search_incidents(
                query=query,
                limit=limit,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    @mcp.tool(
        name="search_rca_history",
        description="Search RCA history records through the infraops read-only interface.",
        tags={"infraops", "rca", "history", "read"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
    )
    def search_rca_history_tool(query: str | None = None, limit: int = 20) -> dict[str, Any]:
        started_at = perf_counter()
        tool = _resolve_registered_tool("infraops-mcp", "search_rca_history")
        request_payload = {"query": query, "limit": limit}

        try:
            result = infraops.search_rca_history(
                query=query,
                limit=limit,
            ).model_dump(mode="json")
        except Exception as exc:
            _record_tool_audit(
                audit_service=audit_service,
                tool=tool,
                request_payload=request_payload,
                response_payload=None,
                call_status=McpToolCallStatus.FAILED,
                started_at=started_at,
                last_error=str(exc),
            )
            raise

        _record_tool_audit(
            audit_service=audit_service,
            tool=tool,
            request_payload=request_payload,
            response_payload=result,
            call_status=McpToolCallStatus.SUCCESS,
            started_at=started_at,
        )
        return result

    return mcp
