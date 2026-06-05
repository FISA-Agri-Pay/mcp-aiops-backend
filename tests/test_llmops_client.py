import json

import pytest

from aiops_platform.core.config import Settings
from aiops_platform.llmops.client import (
    DEFAULT_ANTHROPIC_BASE_URL,
    DEFAULT_OPENAI_BASE_URL,
    AnthropicLlmClient,
    LlmCompletionRequest,
    OpenAICompatibleLlmClient,
    create_llm_client,
)


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_openai_compatible_client_sends_mcp_context_and_parses_json_answer() -> None:
    captured = {}

    def fake_post(request, timeout: float):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "answer": (
                                        "한도는 255만원이고 checkout은 "
                                        "사용자 확인이 필요합니다."
                                    ),
                                    "confidence": "high",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )

    client = OpenAICompatibleLlmClient(
        model="gpt-test",
        api_key="test-key",
        base_url="https://llm.example.test/v1",
        timeout_seconds=12,
        temperature=0.2,
        max_tokens=256,
        post=fake_post,
    )

    response = client.complete(
        LlmCompletionRequest(
            chat_type="farmer_bnpl",
            prompt_key="farmer_bnpl_chat",
            prompt_template="Answer safely.",
            input_payload={
                "tool_results": [
                    {
                        "server_name": "farmer-bnpl-mcp",
                        "tool_name": "get_user_credit_limit",
                        "response_payload": {"available_limit": 2_550_000},
                    }
                ]
            },
            output_schema={"required": ["answer"]},
        )
    )

    assert captured["url"] == "https://llm.example.test/v1/chat/completions"
    assert captured["timeout"] == 12
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["body"]["model"] == "gpt-test"
    user_message = captured["body"]["messages"][1]["content"]
    assert "farmer-bnpl-mcp" in user_message
    assert response.provider == "openai-compatible"
    assert response.output_payload["answer"] == (
        "한도는 255만원이고 checkout은 사용자 확인이 필요합니다."
    )


def test_llm_client_factory_falls_back_to_fake_without_api_key() -> None:
    client = create_llm_client(
        Settings(
            LLM_PROVIDER="openai",
            LLM_MODEL="gpt-test",
            LLM_API_KEY="",
            LLM_REQUIRE_API_KEY=True,
        )
    )

    assert client.provider == "fake"


def test_openai_compatible_client_can_call_keyless_vllm_endpoint() -> None:
    captured = {}

    def fake_post(request, timeout: float):
        captured["headers"] = dict(request.header_items())
        return FakeHttpResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps({"answer": "vLLM 응답입니다."})
                        }
                    }
                ]
            }
        )

    client = OpenAICompatibleLlmClient(
        model="Qwen/Qwen3-32B",
        api_key=None,
        base_url="http://gpu-pod.example.test:8000/v1",
        timeout_seconds=30,
        temperature=0.1,
        max_tokens=512,
        post=fake_post,
    )

    response = client.complete(
        LlmCompletionRequest(
            chat_type="admin_copilot",
            prompt_key="admin_copilot",
            prompt_template="Answer with MCP evidence.",
            input_payload={"tool_results": []},
            output_schema={"required": ["answer"]},
        )
    )

    assert "Authorization" not in captured["headers"]
    assert response.output_payload["answer"] == "vLLM 응답입니다."


def test_llm_client_factory_uses_keyless_openai_compatible_when_allowed() -> None:
    client = create_llm_client(
        Settings(
            LLM_PROVIDER="openai-compatible",
            LLM_MODEL="Qwen/Qwen3-32B",
            LLM_API_BASE_URL="http://gpu-pod.example.test:8000/v1",
            LLM_API_KEY="",
            LLM_REQUIRE_API_KEY=False,
        )
    )

    assert client.provider == "openai-compatible"


def test_llm_client_factory_rejects_invalid_openai_compatible_base_url() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        create_llm_client(
            Settings(
                LLM_PROVIDER="openai-compatible",
                LLM_MODEL="Qwen/Qwen3-32B",
                LLM_API_BASE_URL="file:///tmp/model",
                LLM_API_KEY="",
                LLM_REQUIRE_API_KEY=False,
            )
        )


def test_llm_client_factory_rejects_invalid_anthropic_base_url() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        create_llm_client(
            Settings(
                LLM_PROVIDER="anthropic",
                LLM_MODEL="claude-test",
                LLM_API_BASE_URL="ftp://anthropic.example.test/v1",
                LLM_API_KEY="test-key",
            )
        )


def test_anthropic_client_sends_mcp_context_and_parses_json_answer() -> None:
    captured = {}

    def fake_post(request, timeout: float):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeHttpResponse(
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {"answer": "운영 지표와 RCA 근거를 바탕으로 요약했습니다."},
                            ensure_ascii=False,
                        ),
                    }
                ]
            }
        )

    client = AnthropicLlmClient(
        model="claude-test",
        api_key="test-key",
        base_url="https://anthropic.example.test/v1",
        timeout_seconds=8,
        temperature=0.1,
        max_tokens=300,
        post=fake_post,
    )

    response = client.complete(
        LlmCompletionRequest(
            chat_type="admin_copilot",
            prompt_key="admin_copilot",
            prompt_template="Summarize ops evidence.",
            input_payload={
                "tool_results": [
                    {
                        "server_name": "infraops-mcp",
                        "tool_name": "query_multi_cluster_prometheus",
                        "response_payload": {"sources": []},
                    }
                ]
            },
            output_schema={"required": ["answer"]},
        )
    )

    assert captured["url"] == "https://anthropic.example.test/v1/messages"
    assert captured["timeout"] == 8
    assert captured["headers"]["X-api-key"] == "test-key"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "claude-test"
    assert "infraops-mcp" in captured["body"]["messages"][0]["content"]
    assert response.provider == "anthropic"
    assert response.output_payload["answer"] == "운영 지표와 RCA 근거를 바탕으로 요약했습니다."


def test_llm_client_factory_uses_anthropic_default_base_url() -> None:
    client = create_llm_client(
        Settings(
            LLM_PROVIDER="anthropic",
            LLM_MODEL="claude-test",
            LLM_API_BASE_URL=DEFAULT_OPENAI_BASE_URL,
            LLM_API_KEY="test-key",
        )
    )

    assert client.provider == "anthropic"
    assert client.base_url == DEFAULT_ANTHROPIC_BASE_URL
