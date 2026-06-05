import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aiops_platform.core.database import SessionLocal
from aiops_platform.llmops.client import FakeLlmClient
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.main import create_app
from aiops_platform.orchestration.repository import (
    OrchestrationRepository,
    SqlOrchestrationRepository,
)
from aiops_platform.orchestration.service import OrchestrationService
from tests.seed_constants import FARMER_1_ID


class FailingAgentOrchestrator:
    def run(self, **kwargs):
        raise RuntimeError("planner unavailable")


class FailingAttachRepository(SqlOrchestrationRepository):
    def attach_llm_run_to_tool_calls(self, **kwargs: object) -> None:
        raise RuntimeError("link unavailable")


def create_orchestration_test_client(
    *,
    agent_orchestrator: object | None = None,
    repository: OrchestrationRepository | None = None,
) -> TestClient:
    app = create_app()
    app.state.orchestration_service = OrchestrationService(
        agent_orchestrator=agent_orchestrator,
        repository=repository,
        llmops_service=LlmOpsService(llm_client=FakeLlmClient()),
    )
    return TestClient(app)


def test_farmer_chat_api_creates_session_and_records_masked_tool_calls() -> None:
    client = create_orchestration_test_client()

    session_response = client.post(
        "/farmer/chat/sessions",
        json={"user_id": FARMER_1_ID, "title": "fertilizer help"},
    )
    assert session_response.status_code == 200
    session = session_response.json()

    ask_response = client.post(
        "/farmer/chat/ask",
        json={
            "session_id": session["session_id"],
            "user_id": FARMER_1_ID,
            "message": "Find fertilizer within my BNPL limit.",
        },
    )

    assert ask_response.status_code == 200
    answer = ask_response.json()
    assert answer["session"]["session_id"] == session["session_id"]
    assert answer["job"]["job_type"] == "farmer_chat"
    assert answer["job"]["status"] == "SUCCEEDED"
    assert [tool["tool_name"] for tool in answer["planned_tools"]] == [
        "get_user_credit_limit",
        "get_farmer_profile",
        "recommend_fertilizer_requirements",
        "search_lowest_price_fertilizer",
        "prepare_bnpl_checkout_payload",
    ]
    assert [result["tool_name"] for result in answer["tool_results"]] == [
        "get_user_credit_limit",
        "get_farmer_profile",
        "recommend_fertilizer_requirements",
        "search_lowest_price_fertilizer",
        "prepare_bnpl_checkout_payload",
    ]
    assert {result["call_status"] for result in answer["tool_results"]} == {"SUCCESS"}
    assert answer["tool_results"][0]["response_payload"]["available_limit"] == 2550000

    for result in answer["tool_results"]:
        detail_response = client.get(f"/mcp/tool-calls/{result['tool_call_id']}")
        assert detail_response.status_code == 200
        assert detail_response.json()["llm_run_id"] == answer["llm_run"]["llm_run_id"]

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
    expected_farmer_tool_names = {
        "get_user_credit_limit",
        "get_farmer_profile",
        "search_lowest_price_fertilizer",
        "prepare_bnpl_checkout_payload",
    }
    assert expected_farmer_tool_names.issubset(
        {item["tool_name"] for item in tool_call_items}
    )
    assert all("access_token" not in item["masked_request_payload"] for item in tool_call_items)

    detail = client.get(f"/mcp/tool-calls/{tool_call_items[0]['tool_call_id']}")
    assert detail.status_code == 200
    assert detail.json()["server_name"] == "farmer-bnpl-mcp"


def test_admin_copilot_api_creates_job_and_planned_tools() -> None:
    client = create_orchestration_test_client()

    ask_response = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "Summarize today's risk and scaling status."},
    )

    assert ask_response.status_code == 200
    answer = ask_response.json()
    assert answer["session"]["chat_type"] == "admin_copilot"
    assert answer["job"]["job_type"] == "admin_copilot"
    assert answer["job"]["status"] == "SUCCEEDED"
    assert {
        tool["server_name"] for tool in answer["planned_tools"]
    } == {
        "admin-riskops-mcp",
        "infraops-mcp",
        "prediction-scaling-mcp",
    }
    assert {result["call_status"] for result in answer["tool_results"]} == {"SUCCESS"}
    assert {
        result["server_name"] for result in answer["tool_results"]
    } == {
        "admin-riskops-mcp",
        "infraops-mcp",
        "prediction-scaling-mcp",
    }

    jobs = client.get("/jobs", params={"job_type": "admin_copilot"})
    assert jobs.status_code == 200
    job_items = jobs.json()["items"]
    assert answer["job"]["job_id"] in {job["job_id"] for job in job_items}

    retry = client.post(f"/jobs/{answer['job']['job_id']}/retry")
    cancel = client.post(f"/jobs/{answer['job']['job_id']}/cancel")
    assert retry.status_code == 200
    assert retry.json()["will_execute"] is False
    assert retry.json()["action"] == "retry"
    assert cancel.json()["action"] == "cancel"


def test_chat_session_close_blocks_follow_up_questions() -> None:
    client = create_orchestration_test_client()

    session = client.post("/farmer/chat/sessions", json={"user_id": FARMER_1_ID}).json()
    close_response = client.post(f"/farmer/chat/sessions/{session['session_id']}/close")
    follow_up = client.post(
        "/farmer/chat/ask",
        json={
            "session_id": session["session_id"],
            "user_id": FARMER_1_ID,
            "message": "Can I still use this session?",
        },
    )

    assert close_response.status_code == 200
    assert close_response.json()["status"] == "CLOSED"
    assert follow_up.status_code == 400


def test_farmer_chat_blank_session_id_creates_new_session() -> None:
    client = create_orchestration_test_client()

    ask_response = client.post(
        "/farmer/chat/ask",
        json={
            "session_id": "   ",
            "user_id": FARMER_1_ID,
            "message": "Start a new BNPL chat.",
        },
    )

    assert ask_response.status_code == 200
    assert ask_response.json()["session"]["status"] == "OPEN"


def test_farmer_chat_checkout_confirmation_requires_approval() -> None:
    client = create_orchestration_test_client()

    ask_response = client.post(
        "/farmer/chat/ask",
        json={
            "user_id": FARMER_1_ID,
            "message": "confirm checkout 생성",
        },
    )

    assert ask_response.status_code == 200
    checkout_results = [
        result
        for result in ask_response.json()["tool_results"]
        if result["tool_name"] == "create_bnpl_checkout"
    ]
    assert len(checkout_results) == 1
    assert checkout_results[0]["call_status"] == "APPROVAL_REQUIRED"
    assert checkout_results[0]["will_execute"] is False
    assert checkout_results[0]["requires_approval"] is True


def test_jobs_reject_invalid_status_filter() -> None:
    client = TestClient(create_app())

    response = client.get("/jobs", params={"status": "not-a-status"})

    assert response.status_code == 400
    assert response.json()["detail"] == "job status is invalid."


def test_job_updated_at_uses_finished_timestamp() -> None:
    repository = SqlOrchestrationRepository()
    job = repository.create_job(
        job_type="farmer_chat",
        entity_type="ai.chat_sessions",
        entity_id=FARMER_1_ID,
        status="RUNNING",
    )
    finished_at = "2030-01-01 00:00:00"
    with SessionLocal() as session:
        session.execute(
            text(
                """
                update ai.job_runs
                set finished_at = timestamp '2030-01-01 00:00:00'
                where public_id = cast(:job_id as uuid)
                """
            ),
            {"job_id": job.job_id},
        )
        session.commit()

    updated = repository.get_job(job.job_id)

    assert updated is not None
    assert updated.updated_at == finished_at


def test_attach_llm_run_to_tool_calls_rejects_invalid_identifiers(caplog) -> None:
    repository = SqlOrchestrationRepository()

    with caplog.at_level("ERROR"), pytest.raises(ValueError) as exc_info:
        repository.attach_llm_run_to_tool_calls(
            job_id="not-a-uuid",
            session_id=FARMER_1_ID,
            llm_run_id="also-not-a-uuid",
        )

    error_message = str(exc_info.value)
    assert "job_id" in error_message
    assert "llm_run_id" in error_message
    assert "Invalid MCP tool call LLM run link identifiers" in caplog.text


def test_chat_flow_continues_when_tool_call_llm_linking_fails(caplog) -> None:
    client = create_orchestration_test_client(repository=FailingAttachRepository())

    with caplog.at_level("ERROR"):
        response = client.post(
            "/farmer/chat/ask",
            json={"user_id": FARMER_1_ID, "message": "비료 추천해줘"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "SUCCEEDED"
    assert body["llm_run"]["run_status"] == "SUCCESS"
    assert "Failed to link MCP tool calls to LLM run" in caplog.text


def test_agent_failure_finishes_job() -> None:
    client = create_orchestration_test_client(
        agent_orchestrator=FailingAgentOrchestrator()
    )

    response = client.post(
        "/farmer/chat/ask",
        json={"user_id": FARMER_1_ID, "message": "비료 추천해줘"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job"]["status"] == "FAILED"
    assert body["job"]["error_message"] == "Agent execution failed: RuntimeError"
    assert body["planned_tools"] == []
    assert body["tool_results"] == []


def test_missing_orchestration_resources_return_404() -> None:
    client = TestClient(create_app())

    assert client.get("/jobs/missing-job").status_code == 404
    assert client.get("/mcp/tool-calls/missing-call").status_code == 404
    assert client.get("/admin/copilot/sessions/missing-session").status_code == 404
