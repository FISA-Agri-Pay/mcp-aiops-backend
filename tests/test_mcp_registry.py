from fastapi.testclient import TestClient

from aiops_platform.main import create_app
from aiops_platform.mcp.registry import list_mcp_servers, list_mcp_tools


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
BATCH_TOOL_NAMES = {
    "get_batch_run_status",
}


def test_mcp_servers_returns_initial_registry() -> None:
    client = TestClient(create_app())

    response = client.get("/mcp/servers")

    assert response.status_code == 200
    servers = response.json()
    expected_server_names = {
        "farmer-bnpl-mcp",
        "farm-advisory-mcp",
        "admin-riskops-mcp",
        "infraops-mcp",
        "prediction-scaling-mcp",
    }
    server_names = {server["server_name"] for server in servers}

    assert len(servers) == 5
    assert len(server_names) == len(servers)
    assert server_names == expected_server_names
    assert all(server["server_status"] == "ACTIVE" for server in servers)


def test_external_api_prefix_exposes_mcp_registry() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/mcp/servers")

    assert response.status_code == 200
    assert {server["server_name"] for server in response.json()} == {
        "farmer-bnpl-mcp",
        "farm-advisory-mcp",
        "admin-riskops-mcp",
        "infraops-mcp",
        "prediction-scaling-mcp",
    }


def test_mcp_tools_can_be_filtered_by_server_and_permission() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/mcp/tools",
        params={"server_name": "infraops-mcp", "permission": "DESTRUCTIVE"},
    )

    assert response.status_code == 200
    tools = response.json()
    assert len(tools) == 2
    assert [tool["tool_name"] for tool in tools] == ["delete_pod", "run_kubectl_exec"]
    assert all(tool["server_name"] == "infraops-mcp" for tool in tools)
    assert all(tool["tool_permission"] == "DESTRUCTIVE" for tool in tools)


def test_mcp_tools_include_elk_registry_entries() -> None:
    client = TestClient(create_app())

    response = client.get("/mcp/tools", params={"server_name": "infraops-mcp"})

    assert response.status_code == 200
    tool_names = {tool["tool_name"] for tool in response.json()}
    assert ELK_TOOL_NAMES.issubset(tool_names)


def test_mcp_registry_can_hide_elk_tools() -> None:
    tools = list_mcp_tools(server_name="infraops-mcp", include_elk=False)
    servers = list_mcp_servers(include_elk=False)

    assert ELK_TOOL_NAMES.isdisjoint({tool.tool_name for tool in tools})
    infraops_server = next(server for server in servers if server.server_name == "infraops-mcp")
    assert ELK_TOOL_NAMES.isdisjoint({tool.tool_name for tool in infraops_server.tools})


def test_mcp_registry_can_hide_kafka_tools() -> None:
    tools = list_mcp_tools(server_name="infraops-mcp", include_kafka=False)
    servers = list_mcp_servers(include_kafka=False)

    assert KAFKA_TOOL_NAMES.isdisjoint({tool.tool_name for tool in tools})
    infraops_server = next(server for server in servers if server.server_name == "infraops-mcp")
    assert KAFKA_TOOL_NAMES.isdisjoint({tool.tool_name for tool in infraops_server.tools})


def test_mcp_registry_can_hide_batch_tools() -> None:
    tools = list_mcp_tools(server_name="infraops-mcp", include_batch=False)
    servers = list_mcp_servers(include_batch=False)

    assert BATCH_TOOL_NAMES.isdisjoint({tool.tool_name for tool in tools})
    infraops_server = next(server for server in servers if server.server_name == "infraops-mcp")
    assert BATCH_TOOL_NAMES.isdisjoint({tool.tool_name for tool in infraops_server.tools})


def test_mcp_tools_trims_server_name_filter() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/mcp/tools",
        params={"server_name": "prediction-scaling-mcp "},
    )

    assert response.status_code == 200
    tools = response.json()
    assert len(tools) == 11
    assert {tool["server_name"] for tool in tools} == {"prediction-scaling-mcp"}
    assert "get_model_versions" in {tool["tool_name"] for tool in tools}
