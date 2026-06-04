from fastapi.testclient import TestClient

from aiops_platform.main import create_app


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


def test_mcp_tools_can_be_filtered_by_server_and_permission() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/mcp/tools",
        params={"server_name": "infraops-mcp", "permission": "DESTRUCTIVE"},
    )

    assert response.status_code == 200
    tools = response.json()
    assert {tool["tool_name"] for tool in tools} == {"delete_pod", "run_kubectl_exec"}
    assert all(tool["server_name"] == "infraops-mcp" for tool in tools)
    assert all(tool["tool_permission"] == "DESTRUCTIVE" for tool in tools)
