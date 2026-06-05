from fastapi.testclient import TestClient

from aiops_platform.main import create_app
from tests.seed_constants import FARMER_1_ID


def test_client_contract_exposes_expected_mcp_servers_and_tools() -> None:
    client = TestClient(create_app())

    servers_response = client.get("/mcp/servers")
    farmer_tools_response = client.get(
        "/mcp/tools",
        params={"server_name": "farmer-bnpl-mcp"},
    )
    ops_write_response = client.get(
        "/mcp/tools",
        params={"server_name": "infraops-mcp", "permission": "OPS_WRITE"},
    )

    assert servers_response.status_code == 200
    servers = servers_response.json()
    assert [server["server_name"] for server in servers] == [
        "farmer-bnpl-mcp",
        "farm-advisory-mcp",
        "admin-riskops-mcp",
        "infraops-mcp",
        "prediction-scaling-mcp",
    ]
    assert all(server["server_status"] == "ACTIVE" for server in servers)

    assert farmer_tools_response.status_code == 200
    farmer_tool_names = {tool["tool_name"] for tool in farmer_tools_response.json()}
    assert {
        "get_user_credit_limit",
        "search_products",
        "prepare_bnpl_checkout_payload",
        "create_bnpl_checkout",
    }.issubset(farmer_tool_names)

    assert ops_write_response.status_code == 200
    assert [tool["tool_name"] for tool in ops_write_response.json()] == [
        "scale_deployment",
        "restart_pod",
    ]


def test_client_contract_openapi_includes_chat_history_and_mcp_paths() -> None:
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in [
        "/farmer/chat/ask",
        "/admin/copilot/ask",
        "/jobs",
        "/mcp/servers",
        "/mcp/tools",
        "/mcp/tool-calls",
    ]:
        assert path in paths


def test_client_contract_farmer_agent_response_is_renderable() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/farmer/chat/ask",
        json={
            "user_id": FARMER_1_ID,
            "message": "내 BNPL 한도 안에서 비료 추천해줘",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session"]["chat_type"] == "farmer_bnpl"
    assert body["assistant_message"]["role"] == "ASSISTANT"
    assert body["assistant_message"]["content"]
    assert body["job"]["job_type"] == "farmer_chat"
    assert body["job"]["status"] == "SUCCEEDED"
    assert len(body["planned_tools"]) == len(body["tool_results"])
    assert all("server_name" in tool for tool in body["planned_tools"])
    assert all("tool_name" in result for result in body["tool_results"])
    assert all("access_token" not in result["request_payload"] for result in body["tool_results"])


def test_client_contract_approval_required_tool_result_is_explicit() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/farmer/chat/ask",
        json={
            "user_id": FARMER_1_ID,
            "message": "confirm checkout 생성",
        },
    )

    assert response.status_code == 200
    checkout_results = [
        result
        for result in response.json()["tool_results"]
        if result["tool_name"] == "create_bnpl_checkout"
    ]
    assert len(checkout_results) == 1
    checkout = checkout_results[0]
    assert checkout["tool_permission"] == "USER_CONFIRMED_WRITE"
    assert checkout["call_status"] == "APPROVAL_REQUIRED"
    assert checkout["execution_policy"] == "blocked_until_confirmed"
    assert checkout["will_execute"] is False
    assert checkout["requires_approval"] is True
    assert checkout["is_blocked"] is False


def test_client_contract_job_and_tool_call_history_are_queryable() -> None:
    client = TestClient(create_app())
    ask_response = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "위험 현황과 스케일링 상태 요약"},
    )
    assert ask_response.status_code == 200
    ask_body = ask_response.json()
    job_id = ask_body["job"]["job_id"]
    tool_call_ids = [
        result["tool_call_id"]
        for result in ask_body["tool_results"]
        if result["tool_call_id"] is not None
    ]

    jobs_response = client.get("/jobs", params={"job_type": "admin_copilot"})
    tool_calls_response = client.get(
        "/mcp/tool-calls",
        params={"status": "SUCCESS", "limit": 100},
    )

    assert jobs_response.status_code == 200
    assert job_id in {job["job_id"] for job in jobs_response.json()["items"]}

    assert tool_calls_response.status_code == 200
    tool_calls = tool_calls_response.json()["items"]
    listed_tool_call_ids = {tool_call["tool_call_id"] for tool_call in tool_calls}
    assert set(tool_call_ids).issubset(listed_tool_call_ids)
    assert all(
        "access_token" not in (tool_call["masked_request_payload"] or {})
        for tool_call in tool_calls
    )

    for tool_call_id in tool_call_ids:
        detail_response = client.get(f"/mcp/tool-calls/{tool_call_id}")
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["job_id"] == job_id
        assert "access_token" not in (detail["masked_request_payload"] or {})
