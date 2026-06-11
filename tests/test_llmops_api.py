from fastapi.testclient import TestClient

from aiops_platform.llmops.client import FakeLlmClient
from aiops_platform.llmops.service import LlmOpsService, LlmOpsValidationError
from aiops_platform.main import create_app
from aiops_platform.agent.orchestrator import AgentOrchestrator
from aiops_platform.agent.planner import RuleBasedAgentPlanner
from aiops_platform.orchestration.service import OrchestrationService
from tests.seed_constants import FARMER_1_ID


def create_llmops_test_client() -> TestClient:
    app = create_app()
    llmops_service = LlmOpsService(llm_client=FakeLlmClient())
    app.state.llmops_service = llmops_service
    app.state.orchestration_service = OrchestrationService(
        agent_orchestrator=AgentOrchestrator(planner=RuleBasedAgentPlanner()),
        llmops_service=llmops_service,
    )
    return TestClient(app)


class FailingPromptVersionService:
    def list_prompt_versions(self, **kwargs: object) -> None:
        raise LlmOpsValidationError("prompt scope is invalid.")


class FailingAgentSnapshotService:
    def list_agent_snapshots(self, **kwargs: object) -> None:
        raise LlmOpsValidationError("snapshot type is invalid.")


def test_farmer_agent_records_llm_run_and_prompt_version() -> None:
    client = create_llmops_test_client()

    answer_response = client.post(
        "/farmer/chat/ask",
        json={"user_id": FARMER_1_ID, "message": "비료 추천해줘"},
    )

    assert answer_response.status_code == 200
    answer = answer_response.json()
    assert answer["llm_run"]["provider"] == "fake"
    assert answer["llm_run"]["prompt_key"] == "farmer_bnpl_chat"
    assert answer["llm_run"]["run_status"] == "SUCCESS"
    assert answer["assistant_message"]["content"] == answer["llm_run"]["masked_output"]["answer"]
    assert "access_token" not in answer["llm_run"]["masked_input"]

    llm_run_id = answer["llm_run"]["llm_run_id"]
    detail_response = client.get(f"/llm-runs/{llm_run_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["llm_run_id"] == llm_run_id

    prompt_versions = client.get(
        "/prompt-versions",
        params={"scope": "farmer_bnpl", "limit": 10},
    )
    assert prompt_versions.status_code == 200
    assert any(
        item["prompt_key"] == "farmer_bnpl_chat"
        for item in prompt_versions.json()["items"]
    )

    snapshots = client.get("/agent-snapshots", params={"snapshot_type": "farmer_bnpl"})
    assert snapshots.status_code == 200
    matched_snapshot = next(
        item
        for item in snapshots.json()["items"]
        if item["job_id"] == answer["job"]["job_id"]
    )
    assert matched_snapshot["session_id"] == answer["session"]["session_id"]
    assert matched_snapshot["llm_run_id"] == answer["llm_run"]["llm_run_id"]
    assert matched_snapshot["payload"]["llm_run_id"] == answer["llm_run"]["llm_run_id"]


def test_llm_runs_can_be_filtered_for_client_history() -> None:
    client = create_llmops_test_client()
    ask_response = client.post(
        "/admin/copilot/ask",
        json={"user_id": "admin-1", "message": "위험 현황 요약"},
    )
    assert ask_response.status_code == 200
    llm_run_id = ask_response.json()["llm_run"]["llm_run_id"]

    response = client.get(
        "/llm-runs",
        params={"provider": "fake", "status": "SUCCESS", "limit": 20},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "fake"
    assert body["status"] == "SUCCESS"
    assert llm_run_id in {item["llm_run_id"] for item in body["items"]}


def test_checkout_confirmation_creates_approval_request_skeleton() -> None:
    client = create_llmops_test_client()
    ask_response = client.post(
        "/farmer/chat/ask",
        json={"user_id": FARMER_1_ID, "message": "confirm checkout 생성"},
    )
    assert ask_response.status_code == 200

    response = client.get("/approvals", params={"status": "PENDING", "limit": 20})

    assert response.status_code == 200
    approvals = response.json()["items"]
    checkout_approvals = [
        item
        for item in approvals
        if item["target_type"] == "farmer-bnpl-mcp.create_bnpl_checkout"
    ]
    assert checkout_approvals
    assert checkout_approvals[0]["approval_type"] == "USER_CONFIRMATION"
    assert checkout_approvals[0]["approval_status"] == "PENDING"
    assert "access_token" not in checkout_approvals[0]["request_payload"]


def test_notification_outbox_skeleton_is_queryable() -> None:
    app = create_app()
    created = app.state.llmops_service.create_notification(
        channel="dashboard",
        content="RCA report is ready for review.",
        payload={"report_id": "report-1", "access_token": "secret"},
        recipient="admin-1",
        title="RCA ready",
    )
    client = TestClient(app)

    response = client.get("/notifications", params={"status": "PENDING", "limit": 20})

    assert response.status_code == 200
    notifications = response.json()["items"]
    matched = [item for item in notifications if item["notification_id"] == created.notification_id]
    assert matched
    assert matched[0]["channel"] == "DASHBOARD"
    assert matched[0]["payload"]["access_token"] == "***MASKED***"


def test_ops_report_completion_rejects_blank_report_type() -> None:
    service = LlmOpsService(llm_client=FakeLlmClient())

    result = service.run_ops_report_completion(
        report_type=" ",
        period={},
        incidents=[],
        rca_reports=[],
        metric_summaries=[],
        job_id=None,
    )

    assert result.run_status == "FAILED"
    assert result.prompt_key == "ops_report.invalid.v1"
    assert result.last_error == "report_type is required."


def test_prompt_versions_validation_error_returns_400() -> None:
    app = create_app()
    app.state.llmops_service = FailingPromptVersionService()
    client = TestClient(app)

    response = client.get("/prompt-versions")

    assert response.status_code == 400
    assert response.json()["detail"] == "prompt scope is invalid."


def test_agent_snapshots_validation_error_returns_400() -> None:
    app = create_app()
    app.state.llmops_service = FailingAgentSnapshotService()
    client = TestClient(app)

    response = client.get("/agent-snapshots")

    assert response.status_code == 400
    assert response.json()["detail"] == "snapshot type is invalid."
