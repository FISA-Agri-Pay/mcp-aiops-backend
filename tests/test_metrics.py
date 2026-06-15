from fastapi.testclient import TestClient

from aiops_platform.core.metrics import (
    record_chat_response_metrics,
    record_llm_request_metrics,
    reset_metrics_for_tests,
)
from aiops_platform.main import create_app


def test_metrics_endpoint_exports_llm_token_usage() -> None:
    reset_metrics_for_tests()
    record_llm_request_metrics(
        provider="openai-compatible",
        model="Qwen/Qwen3-32B",
        prompt_key="rca.infra.v1",
        chat_type="admin_copilot",
        status="SUCCESS",
        prompt_chars=400,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        latency_ms=321,
    )
    client = TestClient(create_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "aiops_llm_prompt_tokens_last" in body
    assert 'prompt_key="rca.infra.v1"' in body
    assert "aiops_llm_estimated_prompt_tokens_last" in body
    assert "aiops_llm_latency_ms_sum" in body
    assert "aiops_llm_requests_total" in body


def test_metrics_endpoint_exports_chat_response_latency_by_source() -> None:
    reset_metrics_for_tests()
    record_chat_response_metrics(
        chat_type="farmer_bnpl",
        response_source="deterministic",
        status="SUCCEEDED",
        latency_ms=45,
        capability="credit_limit_status",
    )
    client = TestClient(create_app())

    response = client.get("/metrics")

    assert response.status_code == 200
    body = response.text
    assert "aiops_chat_response_latency_ms_last" in body
    assert "aiops_chat_response_latency_ms_sum" in body
    assert "aiops_chat_requests_total" in body
    assert 'chat_type="farmer_bnpl"' in body
    assert 'response_source="deterministic"' in body
