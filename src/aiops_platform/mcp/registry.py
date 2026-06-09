from collections.abc import Iterable

from aiops_platform.core.config import settings
from aiops_platform.mcp.schemas import McpServerMetadata, McpToolMetadata, McpToolPermission

ToolDefinition = tuple[str, McpToolPermission]


def _tool(server_name: str, tool_name: str, permission: McpToolPermission) -> McpToolMetadata:
    return McpToolMetadata(
        server_name=server_name,
        tool_name=tool_name,
        display_name=tool_name.replace("_", " "),
        tool_permission=permission,
    )


def _tools(server_name: str, definitions: Iterable[ToolDefinition]) -> list[McpToolMetadata]:
    return [_tool(server_name, tool_name, permission) for tool_name, permission in definitions]


READ = McpToolPermission.READ
WRITE = McpToolPermission.WRITE
USER_CONFIRMED_WRITE = McpToolPermission.USER_CONFIRMED_WRITE
OPS_WRITE = McpToolPermission.OPS_WRITE
DESTRUCTIVE = McpToolPermission.DESTRUCTIVE
ELK_TOOL_NAMES = {
    "query_elasticsearch",
    "search_elasticsearch_logs",
    "get_elasticsearch_cluster_health",
    "get_elasticsearch_index_health",
    "get_kibana_saved_objects",
    "create_elk_snapshot",
}
KAFKA_TOOL_NAMES = {
    "get_kafka_consumer_lag",
}


MCP_SERVERS: tuple[McpServerMetadata, ...] = (
    McpServerMetadata(
        server_name="farmer-bnpl-mcp",
        display_name="Farmer BNPL MCP",
        description="BNPL credit, products, cart, and checkout intent tools.",
        server_metadata={"domain": "FARMER_BNPL"},
        tools=_tools(
            "farmer-bnpl-mcp",
            (
                ("start_credit_application", WRITE),
                ("save_farmland_info", WRITE),
                ("save_crop_info", WRITE),
                ("save_insurance_info", WRITE),
                ("get_required_documents", READ),
                ("submit_credit_documents", WRITE),
                ("get_credit_limit_status", READ),
                ("get_user_credit_limit", READ),
                ("get_farmer_profile", READ),
                ("get_repayment_schedule", READ),
                ("get_interest_due", READ),
                ("get_overdue_status", READ),
                ("get_latest_order_delivery_status", READ),
                ("search_products", READ),
                ("search_lowest_price_fertilizer", READ),
                ("get_product_detail", READ),
                ("calculate_cart_total", READ),
                ("prepare_bnpl_checkout_payload", READ),
                ("create_checkout_intent", WRITE),
                ("add_cart_item", WRITE),
                ("update_cart_item", WRITE),
                ("create_bnpl_checkout", USER_CONFIRMED_WRITE),
            ),
        ),
    ),
    McpServerMetadata(
        server_name="farm-advisory-mcp",
        display_name="Farm Advisory MCP",
        description="Crop calendar, material recommendation, and farm risk tools.",
        server_metadata={"domain": "FARM_ADVISORY"},
        tools=_tools(
            "farm-advisory-mcp",
            (
                ("get_crop_calendar", READ),
                ("recommend_farming_materials", READ),
                ("recommend_fertilizer_requirements", READ),
                ("rank_material_options", READ),
                ("recommend_product_bundle", READ),
                ("get_weather_risk", READ),
                ("triage_crop_disease", READ),
                ("simulate_crop_income", READ),
                ("simulate_season_cashflow", READ),
                ("translate_finance_terms_for_farmer", READ),
            ),
        ),
    ),
    McpServerMetadata(
        server_name="admin-riskops-mcp",
        display_name="Admin RiskOps MCP",
        description="Admin credit review, overdue, and disaster risk tools.",
        server_metadata={"domain": "RISKOPS"},
        tools=_tools(
            "admin-riskops-mcp",
            (
                ("get_credit_review_queue", READ),
                ("get_credit_review_detail", READ),
                ("summarize_credit_risk", READ),
                ("get_bnpl_summary", READ),
                ("search_bnpl_users", READ),
                ("get_overdue_summary", READ),
                ("search_overdue_users", READ),
                ("get_bss_score_history", READ),
                ("simulate_disaster_credit_risk", READ),
                ("create_risk_analysis_snapshot", READ),
                ("send_repayment_alert", WRITE),
                ("send_overdue_alerts", WRITE),
            ),
        ),
    ),
    McpServerMetadata(
        server_name="infraops-mcp",
        display_name="InfraOps MCP",
        description="Observability, Kubernetes, Kafka, and RCA evidence tools.",
        server_metadata={"domain": "INFRAOPS"},
        tools=_tools(
            "infraops-mcp",
            (
                ("query_prometheus", READ),
                ("query_loki", READ),
                ("query_multi_cluster_prometheus", READ),
                ("query_multi_cluster_loki", READ),
                ("query_elasticsearch", READ),
                ("search_elasticsearch_logs", READ),
                ("get_elasticsearch_cluster_health", READ),
                ("get_elasticsearch_index_health", READ),
                ("get_kibana_saved_objects", READ),
                ("create_elk_snapshot", READ),
                ("get_k8s_pods", READ),
                ("get_k8s_events", READ),
                ("get_k8s_deployments", READ),
                ("get_k8s_hpa", READ),
                ("get_kafka_consumer_lag", READ),
                ("get_batch_run_status", READ),
                ("aggregate_daily_ops_metrics", READ),
                ("create_rca_snapshot", READ),
                ("search_incidents", READ),
                ("search_rca_history", READ),
                ("scale_deployment", OPS_WRITE),
                ("restart_pod", OPS_WRITE),
                ("delete_pod", DESTRUCTIVE),
                ("run_kubectl_exec", DESTRUCTIVE),
            ),
        ),
    ),
    McpServerMetadata(
        server_name="prediction-scaling-mcp",
        display_name="Prediction Scaling MCP",
        description="Prediction metric, actual metric, and scaling event tools.",
        server_metadata={"domain": "PREDICTION_SCALING"},
        tools=_tools(
            "prediction-scaling-mcp",
            (
                ("get_model_versions", READ),
                ("get_prediction_runs", READ),
                ("get_prediction_metrics", READ),
                ("get_latest_prediction", READ),
                ("get_actual_metrics", READ),
                ("get_prediction_errors", READ),
                ("get_prediction_error_metrics", READ),
                ("get_scaling_events", READ),
                ("get_scaling_summary", READ),
                ("create_prediction_snapshot", READ),
                ("create_scaling_analysis_snapshot", READ),
            ),
        ),
    ),
)


def _filter_infraops_tools(
    tools: Iterable[McpToolMetadata],
    *,
    include_elk: bool,
    include_kafka: bool,
) -> list[McpToolMetadata]:
    disabled_tools: set[str] = set()
    if not include_elk:
        disabled_tools.update(ELK_TOOL_NAMES)
    if not include_kafka:
        disabled_tools.update(KAFKA_TOOL_NAMES)
    return [tool for tool in tools if tool.tool_name not in disabled_tools]


def list_mcp_servers(
    *,
    include_elk: bool | None = None,
    include_kafka: bool | None = None,
) -> list[McpServerMetadata]:
    resolved_include_elk = settings.infraops_elk_enabled if include_elk is None else include_elk
    resolved_include_kafka = (
        settings.infraops_kafka_enabled if include_kafka is None else include_kafka
    )
    return [
        server.model_copy(
            update={
                "tools": _filter_infraops_tools(
                    server.tools,
                    include_elk=resolved_include_elk,
                    include_kafka=resolved_include_kafka,
                )
            }
        )
        for server in MCP_SERVERS
    ]


def list_mcp_tools(
    server_name: str | None = None,
    permission: McpToolPermission | None = None,
    include_elk: bool | None = None,
    include_kafka: bool | None = None,
) -> list[McpToolMetadata]:
    resolved_include_elk = settings.infraops_elk_enabled if include_elk is None else include_elk
    resolved_include_kafka = (
        settings.infraops_kafka_enabled if include_kafka is None else include_kafka
    )
    tools = [
        tool
        for server in MCP_SERVERS
        for tool in _filter_infraops_tools(
            server.tools,
            include_elk=resolved_include_elk,
            include_kafka=resolved_include_kafka,
        )
    ]
    normalized_server_name = server_name.strip() if server_name is not None else None

    if normalized_server_name:
        tools = [tool for tool in tools if tool.server_name == normalized_server_name]

    if permission is not None:
        tools = [tool for tool in tools if tool.tool_permission == permission]

    return tools
