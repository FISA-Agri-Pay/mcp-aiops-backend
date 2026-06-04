import logging
from time import perf_counter
from typing import Any

from fastmcp import FastMCP

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
    infraops_service: InfraOpsService | None = None,
) -> FastMCP:
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

    return mcp
