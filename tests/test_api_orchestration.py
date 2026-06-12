import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from aiops_platform.agent.orchestrator import AgentOrchestrator
from aiops_platform.agent.planner import RuleBasedAgentPlanner
from aiops_platform.agent.schemas import AgentToolExecutionResult
from aiops_platform.core.database import SessionLocal
from aiops_platform.llmops.client import FakeLlmClient, LlmClientError
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.main import create_app
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)
from aiops_platform.orchestration.repository import (
    OrchestrationRepository,
    SqlOrchestrationRepository,
)
from aiops_platform.orchestration.service import OrchestrationService, build_chat_ui_cards
from tests.seed_constants import CREDIT_APP_2_ID, FARMER_1_ID, FARMER_2_ID


class FailingAgentOrchestrator:
    def run(self, **kwargs):
        raise RuntimeError("planner unavailable")


class FailingAttachRepository(SqlOrchestrationRepository):
    def attach_llm_run_to_tool_calls(self, **kwargs: object) -> None:
        raise RuntimeError("link unavailable")


class FailingLlmClient:
    provider = "test-provider"
    model = "test-model"

    def complete(self, request):
        raise LlmClientError(
            "LLM provider returned HTTP 429.",
            error_type="http_error",
            http_status=429,
            response_body_excerpt='{"error":"rate limit"}',
            retryable=True,
        )


def build_successful_farmer_tool_result(
    *,
    tool_name: str,
    response_payload: dict,
) -> AgentToolExecutionResult:
    return AgentToolExecutionResult(
        server_name="farmer-bnpl-mcp",
        tool_name=tool_name,
        tool_permission=McpToolPermission.READ,
        confirmation_policy=McpConfirmationPolicy.NONE,
        execution_policy=McpExecutionPolicy.ALLOWED,
        call_status=McpToolCallStatus.SUCCESS,
        will_execute=True,
        requires_approval=False,
        is_blocked=False,
        request_payload={},
        response_payload=response_payload,
    )


def create_orchestration_test_client(
    *,
    agent_orchestrator: object | None = None,
    repository: OrchestrationRepository | None = None,
    llm_client: object | None = None,
) -> TestClient:
    app = create_app()
    app.state.orchestration_service = OrchestrationService(
        agent_orchestrator=agent_orchestrator
        or AgentOrchestrator(planner=RuleBasedAgentPlanner()),
        repository=repository,
        llmops_service=LlmOpsService(llm_client=llm_client or FakeLlmClient()),
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
    ]
    assert [result["tool_name"] for result in answer["tool_results"]] == [
        "get_user_credit_limit",
        "get_farmer_profile",
        "recommend_fertilizer_requirements",
        "search_lowest_price_fertilizer",
    ]
    assert {result["call_status"] for result in answer["tool_results"]} == {"SUCCESS"}
    assert answer["tool_results"][0]["response_payload"]["available_limit"] == 2550000
    assert {card["type"] for card in answer["ui_cards"]} == {
        "credit-summary",
        "recommendation",
    }
    credit_card = next(card for card in answer["ui_cards"] if card["type"] == "credit-summary")
    assert credit_card["remaining"] == 2_550_000

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
    assert messages.json()["items"][1]["ui_cards"] == answer["ui_cards"]

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
    }
    assert expected_farmer_tool_names.issubset(
        {item["tool_name"] for item in tool_call_items}
    )
    assert all("access_token" not in item["masked_request_payload"] for item in tool_call_items)

    detail = client.get(f"/mcp/tool-calls/{tool_call_items[0]['tool_call_id']}")
    assert detail.status_code == 200
    assert detail.json()["server_name"] == "farmer-bnpl-mcp"


def test_farmer_chat_session_list_returns_only_requested_user_sessions() -> None:
    client = create_orchestration_test_client()

    first = client.post(
        "/farmer/chat/sessions",
        json={"user_id": FARMER_1_ID, "title": "first farmer chat"},
    ).json()
    client.post(
        "/farmer/chat/sessions",
        json={"user_id": FARMER_2_ID, "title": "other farmer chat"},
    )
    second = client.post(
        "/farmer/chat/sessions",
        json={"user_id": FARMER_1_ID, "title": "second farmer chat"},
    ).json()

    response = client.get(
        "/farmer/chat/sessions",
        params={"user_id": FARMER_1_ID, "status": "OPEN", "limit": 10},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == FARMER_1_ID
    assert body["status"] == "OPEN"
    sessions = body["items"]
    assert [item["session_id"] for item in sessions[:2]] == [
        second["session_id"],
        first["session_id"],
    ]
    assert {item["user_id"] for item in sessions} == {FARMER_1_ID}


def test_farmer_chat_delivery_question_returns_delivery_card() -> None:
    client = create_orchestration_test_client()
    order_id = "90000000-0000-0000-0000-000000000101"
    insert_latest_order(order_id=order_id, user_id=FARMER_1_ID)
    try:
        delivery_response = client.get(
            "/farmer/orders/latest/delivery",
            params={"user_id": FARMER_1_ID},
        )
        ask_response = client.post(
            "/farmer/chat/ask",
            json={"user_id": FARMER_1_ID, "message": "배송 현황 조회"},
        )

        assert delivery_response.status_code == 200
        assert delivery_response.json()["delivery_status"] == "PREPARING"
        assert ask_response.status_code == 200
        answer = ask_response.json()
        assert "get_latest_order_delivery_status" in {
            result["tool_name"] for result in answer["tool_results"]
        }
        delivery_cards = answer["ui_cards"]
        assert [card["type"] for card in delivery_cards] == ["delivery-status"]
        assert delivery_cards[0]["order_id"] == order_id
        assert delivery_cards[0]["delivery_status"] == "PREPARING"
    finally:
        delete_order(order_id)


def test_farmer_chat_ui_cards_include_repayment_summary_type() -> None:
    cards = build_chat_ui_cards(
        "farmer_bnpl",
        "상환 일정과 연체 여부 알려줘",
        [
            build_successful_farmer_tool_result(
                tool_name="get_repayment_schedule",
                response_payload={
                    "currency": "KRW",
                    "schedule": [
                        {
                            "due_date": "2026-06-30",
                            "principal_due": 120000,
                            "interest_due": 3500,
                            "status": "DUE",
                        }
                    ],
                },
            ),
            build_successful_farmer_tool_result(
                tool_name="get_overdue_status",
                response_payload={
                    "is_overdue": False,
                    "overdue_amount": 0,
                    "days_overdue": 0,
                    "currency": "KRW",
                },
            ),
        ],
    )

    assert any(card["type"] == "repayment-summary" for card in cards)


def test_farmer_chat_ui_cards_include_checkout_confirmation_type() -> None:
    cards = build_chat_ui_cards(
        "farmer_bnpl",
        "비료 외상 결제 준비해줘",
        [
            build_successful_farmer_tool_result(
                tool_name="prepare_bnpl_checkout_payload",
                response_payload={
                    "eligible": True,
                    "checkout_intent_id": "checkout-123",
                    "total_amount": 84000,
                    "available_limit": 2550000,
                    "currency": "KRW",
                },
            )
        ],
    )

    checkout_card = next(card for card in cards if card["type"] == "checkout-confirmation")
    assert checkout_card["checkout_intent_id"] == "checkout-123"


def test_farmer_latest_delivery_api_maps_invalid_user_id_to_bad_request() -> None:
    client = create_orchestration_test_client()

    response = client.get(
        "/farmer/orders/latest/delivery",
        params={"user_id": "invalid user"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "user_id is invalid."


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


def test_admin_copilot_greeting_does_not_execute_tools_or_llm() -> None:
    client = create_orchestration_test_client()

    ask_response = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "안녕"},
    )

    assert ask_response.status_code == 200
    answer = ask_response.json()
    assert answer["job"]["status"] == "SUCCEEDED"
    assert answer["planned_tools"] == []
    assert answer["tool_results"] == []
    assert answer["llm_run"] is None
    assert "BNPL 심사 현황" not in answer["assistant_message"]["content"]
    assert "Agent executed" not in answer["assistant_message"]["content"]
    assert answer["assistant_message"]["metadata"]["intent"] == "greeting"
    assert answer["assistant_message"]["metadata"]["response_source"] == "direct"


def test_admin_copilot_llm_failure_uses_user_safe_fallback() -> None:
    client = create_orchestration_test_client(llm_client=FailingLlmClient())

    ask_response = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "연체 위험 고객 현황 알려줘"},
    )

    assert ask_response.status_code == 200
    answer = ask_response.json()
    assert answer["job"]["status"] == "SUCCEEDED"
    assert answer["llm_run"]["run_status"] == "FAILED"
    assert "http_status=429" in answer["llm_run"]["last_error"]
    assert "Agent executed" not in answer["assistant_message"]["content"]
    assert "AI 요약 생성에 실패했습니다" in answer["assistant_message"]["content"]
    assert answer["assistant_message"]["metadata"]["fallback_used"] is True
    assert answer["assistant_message"]["metadata"]["llm_run_status"] == "FAILED"


def test_admin_copilot_session_list_supports_recent_chat_ui() -> None:
    client = create_orchestration_test_client()

    first = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "심사 대기 12건 요약해줘"},
    ).json()
    second = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "연체 위험 고객 현황 알려줘"},
    ).json()

    response = client.get(
        "/admin/copilot/sessions",
        params={"user_id": "admin-1", "status": "OPEN", "limit": 10},
    )

    assert response.status_code == 200
    sessions = response.json()["items"]
    assert [item["session_id"] for item in sessions[:2]] == [
        second["session"]["session_id"],
        first["session"]["session_id"],
    ]
    assert sessions[0]["title"] == "연체 위험 고객 현황 알려줘"
    assert sessions[0]["status"] == "OPEN"

    messages = client.get(f"/admin/copilot/sessions/{sessions[0]['session_id']}/messages")
    assert messages.status_code == 200
    assert [message["role"] for message in messages.json()["items"]] == [
        "USER",
        "ASSISTANT",
    ]


def test_admin_riskops_rest_api_exposes_planned_admin_surfaces() -> None:
    client = create_orchestration_test_client()
    headers = {"X-Admin-Role": "SERVICE_ADMIN"}

    queue = client.get("/admin/risk/credit-reviews", params={"limit": 10}, headers=headers)
    detail = client.get(f"/admin/risk/credit-reviews/{CREDIT_APP_2_ID}", headers=headers)
    summary = client.post(
        f"/admin/risk/credit-reviews/{CREDIT_APP_2_ID}/summarize",
        headers=headers,
    )
    bnpl = client.get("/admin/risk/bnpl/summary", headers=headers)
    overdue = client.get("/admin/risk/overdues/summary", headers=headers)
    bss = client.get(f"/admin/risk/users/{FARMER_2_ID}/bss-history", headers=headers)

    assert queue.status_code == 200
    assert CREDIT_APP_2_ID in {item["application_id"] for item in queue.json()["items"]}
    assert detail.status_code == 200
    assert detail.json()["user_id"] == FARMER_2_ID
    assert summary.status_code == 200
    assert summary.json()["user_id"] == FARMER_2_ID
    assert bnpl.status_code == 200
    assert bnpl.json()["active_users"] == 3
    assert overdue.status_code == 200
    assert overdue.json()["overdue_users"] == 2
    assert bss.status_code == 200
    assert bss.json()["items"][0]["score"] == 740


def test_admin_riskops_rest_api_blocks_invalid_admin_role_header() -> None:
    client = create_orchestration_test_client()

    missing_header_response = client.get("/admin/risk/bnpl/summary")
    response = client.get(
        "/admin/risk/bnpl/summary",
        headers={"X-Admin-Role": "FARMER"},
    )

    assert missing_header_response.status_code == 403
    assert response.status_code == 403


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


def insert_latest_order(*, order_id: str, user_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                """
                insert into core.orders (
                    public_id,
                    user_public_id,
                    payment_request_public_id,
                    total_amount,
                    order_status,
                    delivery_status,
                    recipient_name,
                    recipient_phone,
                    delivery_address,
                    delivery_zip_code,
                    ordered_at,
                    created_at,
                    updated_at
                ) values (
                    cast(:order_id as uuid),
                    cast(:user_id as uuid),
                    '92000000-0000-0000-0000-000000000101',
                    50000.00,
                    'CONFIRMED',
                    'PREPARING',
                    'Sample farmer',
                    '010-1111-2222',
                    'jeonbuk',
                    '55000',
                    timestamp '2026-06-06 10:00:00',
                    timestamp '2026-06-06 10:00:00',
                    timestamp '2026-06-06 10:00:00'
                )
                on conflict (public_id) do update set
                    delivery_status = excluded.delivery_status,
                    ordered_at = excluded.ordered_at,
                    updated_at = excluded.updated_at
                """
            ),
            {"order_id": order_id, "user_id": user_id},
        )
        session.commit()


def delete_order(order_id: str) -> None:
    with SessionLocal() as session:
        session.execute(
            text(
                """
                delete from core.orders
                where public_id = cast(:order_id as uuid)
                """
            ),
            {"order_id": order_id},
        )
        session.commit()
