from fastapi.testclient import TestClient

from aiops_platform.main import create_app


def test_farmer_chat_api_creates_session_and_records_masked_tool_calls() -> None:
    client = TestClient(create_app())

    session_response = client.post(
        "/farmer/chat/sessions",
        json={"user_id": "farmer-1", "title": "fertilizer help"},
    )
    assert session_response.status_code == 200
    session = session_response.json()

    ask_response = client.post(
        "/farmer/chat/ask",
        json={
            "session_id": session["session_id"],
            "user_id": "farmer-1",
            "message": "Find fertilizer within my BNPL limit.",
        },
    )

    assert ask_response.status_code == 200
    answer = ask_response.json()
    assert answer["session"]["session_id"] == session["session_id"]
    assert answer["job"]["job_type"] == "farmer_chat"
    assert [tool["tool_name"] for tool in answer["planned_tools"]] == [
        "get_user_credit_limit",
        "get_farmer_profile",
        "recommend_fertilizer_requirements",
        "search_lowest_price_fertilizer",
        "prepare_bnpl_checkout_payload",
    ]

    messages = client.get(f"/farmer/chat/sessions/{session['session_id']}/messages")
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()["items"]] == [
        "USER",
        "ASSISTANT",
    ]

    tool_calls = client.get(
        "/mcp/tool-calls",
        params={"server_name": "farmer-bnpl-mcp", "limit": 10},
    )
    assert tool_calls.status_code == 200
    tool_call_items = tool_calls.json()["items"]
    assert len(tool_call_items) == 4
    assert {
        item["masked_request_payload"]["access_token"] for item in tool_call_items
    } == {"***MASKED***"}

    detail = client.get(f"/mcp/tool-calls/{tool_call_items[0]['tool_call_id']}")
    assert detail.status_code == 200
    assert detail.json()["server_name"] == "farmer-bnpl-mcp"


def test_admin_copilot_api_creates_job_and_planned_tools() -> None:
    client = TestClient(create_app())

    ask_response = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "Summarize today's risk and scaling status."},
    )

    assert ask_response.status_code == 200
    answer = ask_response.json()
    assert answer["session"]["chat_type"] == "admin_copilot"
    assert answer["job"]["job_type"] == "admin_copilot"
    assert {
        tool["server_name"] for tool in answer["planned_tools"]
    } == {
        "admin-riskops-mcp",
        "infraops-mcp",
        "prediction-scaling-mcp",
    }

    jobs = client.get("/jobs", params={"job_type": "admin_copilot"})
    assert jobs.status_code == 200
    job_items = jobs.json()["items"]
    assert [job["job_id"] for job in job_items] == [answer["job"]["job_id"]]

    retry = client.post(f"/jobs/{answer['job']['job_id']}/retry")
    cancel = client.post(f"/jobs/{answer['job']['job_id']}/cancel")
    assert retry.status_code == 200
    assert retry.json()["will_execute"] is False
    assert retry.json()["action"] == "retry"
    assert cancel.json()["action"] == "cancel"


def test_chat_session_close_blocks_follow_up_questions() -> None:
    client = TestClient(create_app())

    session = client.post("/farmer/chat/sessions", json={"user_id": "farmer-1"}).json()
    close_response = client.post(f"/farmer/chat/sessions/{session['session_id']}/close")
    follow_up = client.post(
        "/farmer/chat/ask",
        json={
            "session_id": session["session_id"],
            "user_id": "farmer-1",
            "message": "Can I still use this session?",
        },
    )

    assert close_response.status_code == 200
    assert close_response.json()["status"] == "CLOSED"
    assert follow_up.status_code == 400


def test_farmer_chat_blank_session_id_creates_new_session() -> None:
    client = TestClient(create_app())

    ask_response = client.post(
        "/farmer/chat/ask",
        json={
            "session_id": "   ",
            "user_id": "farmer-1",
            "message": "Start a new BNPL chat.",
        },
    )

    assert ask_response.status_code == 200
    assert ask_response.json()["session"]["status"] == "OPEN"


def test_jobs_reject_invalid_status_filter() -> None:
    client = TestClient(create_app())

    response = client.get("/jobs", params={"status": "not-a-status"})

    assert response.status_code == 400
    assert response.json()["detail"] == "job status is invalid."


def test_missing_orchestration_resources_return_404() -> None:
    client = TestClient(create_app())

    assert client.get("/jobs/missing-job").status_code == 404
    assert client.get("/mcp/tool-calls/missing-call").status_code == 404
    assert client.get("/admin/copilot/sessions/missing-session").status_code == 404
