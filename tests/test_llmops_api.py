from fastapi.testclient import TestClient

from aiops_platform.agent.orchestrator import AgentOrchestrator
from aiops_platform.agent.planner import RuleBasedAgentPlanner
from aiops_platform.agent.schemas import AgentToolExecutionResult
from aiops_platform.llmops.client import (
    FakeLlmClient,
    LlmCompletionResponse,
    build_fake_answer,
)
from aiops_platform.llmops.schemas import LlmRunResult, PromptVersionResult
from aiops_platform.llmops.service import (
    DEFAULT_PROMPTS,
    OUTPUT_SCHEMA,
    LlmOpsService,
    LlmOpsValidationError,
    serialize_tool_result_for_llm,
)
from aiops_platform.llmops.validation import validate_output_payload
from aiops_platform.main import create_app
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpExecutionPolicy,
    McpToolCallStatus,
    McpToolPermission,
)
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
    assert "Agent executed" not in answer["assistant_message"]["content"]
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


def test_agent_answer_schema_rejects_structured_answer_object() -> None:
    validation = validate_output_payload(
        {"answer": {"summary": "structured objects should not reach chat content"}},
        OUTPUT_SCHEMA,
    )

    assert validation.is_valid is False
    assert "answer must be a string." in validation.errors


class StructuredRcaAnswerLlmClient:
    provider = "fake"
    model = "structured-rca"

    def complete(self, request):
        return LlmCompletionResponse(
            provider=self.provider,
            model=self.model,
            content="{}",
            output_payload={
                "answer": {
                    "summary": ["VPN route and MetalLB boundaries are degraded."],
                    "evidence": [
                        "vpn_route=degraded",
                        "onprem_metallb=degraded",
                    ],
                    "probable_root_cause": (
                        "Traffic appears to break before on-prem ingress."
                    ),
                    "recommended_checks_actions": [
                        "Check pfSense route table.",
                        "Check MetalLB L2 leader and ingress-nginx endpoint.",
                    ],
                    "data_limits": ["Synthetic alert evidence only."],
                }
            },
            latency_ms=1,
        )


class FakeLlmOpsRepository:
    def ensure_prompt_version(self, **kwargs: object) -> PromptVersionResult:
        return PromptVersionResult(
            prompt_version_id="prompt-rca-1",
            prompt_key=str(kwargs["prompt_key"]),
            version=str(kwargs["version"]),
            scope=kwargs["scope"],
            template=str(kwargs["template"]),
            is_active=True,
            created_at="2026-06-12T00:00:00",
        )

    def record_llm_run(self, **kwargs: object) -> LlmRunResult:
        return LlmRunResult(
            llm_run_id="llm-run-rca-1",
            provider=str(kwargs["provider"]),
            model=str(kwargs["model"]),
            prompt_version_id=kwargs.get("prompt_version_id"),
            prompt_key=str(kwargs["prompt_key"]),
            run_status=kwargs["status"],
            job_id=kwargs.get("job_id"),
            session_id=kwargs.get("session_id"),
            masked_input=kwargs["masked_input"],
            masked_output=kwargs["masked_output"],
            output_schema=kwargs["output_schema"],
            validation_errors=kwargs["validation_errors"],
            latency_ms=int(kwargs.get("latency_ms") or 0),
            created_at="2026-06-12T00:00:01",
            last_error=kwargs.get("last_error"),
        )


def test_rca_completion_normalizes_structured_answer_object() -> None:
    service = LlmOpsService(
        repository=FakeLlmOpsRepository(),
        llm_client=StructuredRcaAnswerLlmClient(),
    )

    result = service.run_rca_completion(
        incident={"incident_key": "INC-1"},
        alert={"alertname": "OnpremMetalLBRoutingFailure"},
        snapshot={},
        evidence=[],
    )

    assert result.run_status == "SUCCESS"
    assert result.validation_errors == []
    assert isinstance(result.masked_output["answer"], str)
    assert "요약" in result.masked_output["answer"]
    assert "관측 근거" in result.masked_output["answer"]
    assert "VPN route" in result.masked_output["answer"]


def test_admin_copilot_prompt_requires_readable_plain_text_sections() -> None:
    _, template = DEFAULT_PROMPTS["admin_copilot"]

    assert "plain text" in template
    assert "긴 단일 문단" in template
    assert "요약, 주요 지표, 판단, 우선 조치, 데이터 한계 5개 섹션" in template
    assert "섹션 사이는 빈 줄로 구분" in template
    assert "'- ' 불릿" in template
    assert "smalltalk, help, unsupported이면 섹션 형식을 강제하지 않고" in template


def test_farmer_bnpl_prompt_requires_korean_user_facing_guidance() -> None:
    _, template = DEFAULT_PROMPTS["farmer_bnpl"]

    assert "한국어로만 답변" in template
    assert "내부 tool 이름" in template
    assert "외상 한도 수치는 본문에서 길게 반복하지 말고" in template
    assert "fertilizer_recommendation" in template
    assert "상품명, 가격, 한도 내 구매 가능 여부" in template
    assert "현재 추천 가능한 상품을 찾지 못했습니다" in template
    assert "작물, 재배 면적, 지역, 생육 단계" in template


def test_fake_farmer_answer_is_user_facing() -> None:
    answer = build_fake_answer(chat_type="farmer_bnpl", tool_count=2)

    assert "Agent executed" not in answer
    assert "관련 정보 2건을 조회했습니다" in answer


def test_failed_farmer_tool_result_hides_internal_error_from_llm_input() -> None:
    payload = serialize_tool_result_for_llm(
        AgentToolExecutionResult(
            server_name="farm-advisory-mcp",
            tool_name="recommend_fertilizer_requirements",
            tool_permission=McpToolPermission.READ,
            confirmation_policy=McpConfirmationPolicy.NONE,
            execution_policy=McpExecutionPolicy.ALLOWED,
            call_status=McpToolCallStatus.FAILED,
            will_execute=True,
            requires_approval=False,
            is_blocked=False,
            request_payload={},
            response_payload={"debug": "raw internal detail"},
            error_message="ProgrammingError: validation failed",
        ),
        chat_type="farmer_bnpl",
    )

    assert "ProgrammingError" not in str(payload)
    assert "validation failed" not in str(payload)
    assert payload["failure_policy"] == "hide_internal_error_from_user"


def test_farmer_approval_required_tool_result_keeps_approval_context() -> None:
    payload = serialize_tool_result_for_llm(
        AgentToolExecutionResult(
            server_name="farmer-bnpl-mcp",
            tool_name="create_bnpl_checkout",
            tool_permission=McpToolPermission.USER_CONFIRMED_WRITE,
            confirmation_policy=McpConfirmationPolicy.USER_CONFIRMATION,
            execution_policy=McpExecutionPolicy.BLOCKED_UNTIL_CONFIRMED,
            call_status=McpToolCallStatus.APPROVAL_REQUIRED,
            will_execute=False,
            requires_approval=True,
            is_blocked=False,
            request_payload={"order_id": "order-1"},
            response_payload={"approval_type": "USER_CONFIRMATION"},
            error_message="사용자 확인 후 실행됩니다.",
        ),
        chat_type="farmer_bnpl",
    )

    assert payload["call_status"] == "APPROVAL_REQUIRED"
    assert payload["requires_approval"] is True
    assert payload["response_payload"] == {"approval_type": "USER_CONFIRMATION"}
    assert "failure_policy" not in payload


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
