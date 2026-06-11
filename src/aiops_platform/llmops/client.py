from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from aiops_platform.core.config import Settings
from aiops_platform.orchestration.schemas import ChatType

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class LlmCompletionRequest(BaseModel):
    chat_type: ChatType
    prompt_key: str
    prompt_template: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)


class LlmCompletionResponse(BaseModel):
    provider: str
    model: str
    content: str
    output_payload: dict[str, Any]
    latency_ms: int = 0


class LlmClient(Protocol):
    provider: str
    model: str

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        pass


class LlmClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_type: str = "unknown",
        http_status: int | None = None,
        response_body_excerpt: str | None = None,
        retryable: bool = False,
    ) -> None:
        details = [message]
        details.append(f"error_type={error_type}")
        if http_status is not None:
            details.append(f"http_status={http_status}")
        if response_body_excerpt:
            details.append(f"response_body_excerpt={response_body_excerpt}")
        details.append(f"retryable={retryable}")
        super().__init__("; ".join(details))
        self.error_type = error_type
        self.http_status = http_status
        self.response_body_excerpt = response_body_excerpt
        self.retryable = retryable


class FakeLlmClient:
    provider = "fake"
    model = "fake-agentic-planner"

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        tool_results = request.input_payload.get("tool_results", [])
        tool_count = len(tool_results) if isinstance(tool_results, list) else 0
        content = build_fake_answer(chat_type=request.chat_type, tool_count=tool_count)
        return LlmCompletionResponse(
            provider=self.provider,
            model=self.model,
            content=content,
            output_payload={
                "answer": content,
                "tool_count": tool_count,
                "prompt_key": request.prompt_key,
            },
        )


class OpenAICompatibleLlmClient:
    provider = "openai-compatible"

    def __init__(
        self,
        *,
        provider: str = "openai-compatible",
        model: str,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
        post: Callable[..., Any] = urlopen,
    ) -> None:
        self.provider = provider
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._post = post

    @property
    def base_url(self) -> str:
        return self._base_url.rstrip("/")

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        started = time.perf_counter()
        payload = {
            "model": self.model,
            "messages": build_chat_messages(request),
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
            "response_format": {"type": "json_object"},
        }
        for attempt in range(3):
            try:
                response = self._post_json(payload)
                content = extract_chat_content(response)
                output_payload = parse_output_payload(content)
                return LlmCompletionResponse(
                    provider=self.provider,
                    model=self.model,
                    content=content,
                    output_payload=output_payload,
                    latency_ms=max(int((time.perf_counter() - started) * 1000), 0),
                )
            except LlmClientError as exc:
                if not exc.retryable or attempt >= 2:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise LlmClientError("LLM provider retry loop exited unexpectedly.")

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            urljoin(self._base_url, "chat/completions"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=build_openai_compatible_headers(self._api_key),
            method="POST",
        )
        try:
            with self._post(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body_excerpt = read_error_body_excerpt(exc)
            raise LlmClientError(
                f"LLM provider returned HTTP {exc.code}.",
                error_type="http_error",
                http_status=exc.code,
                response_body_excerpt=body_excerpt,
                retryable=is_retryable_http_status(exc.code),
            ) from exc
        except URLError as exc:
            raise LlmClientError(
                f"LLM provider request failed: {exc.reason}",
                error_type="network_error",
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise LlmClientError(
                "LLM provider request timed out.",
                error_type="timeout",
                retryable=True,
            ) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmClientError(
                "LLM provider returned invalid JSON.",
                error_type="provider_json_parse_error",
                response_body_excerpt=excerpt_text(body),
                retryable=True,
            ) from exc
        if not isinstance(parsed, dict):
            raise LlmClientError(
                "LLM provider returned an invalid response shape.",
                error_type="provider_invalid_shape",
                response_body_excerpt=excerpt_text(body),
                retryable=True,
            )
        return parsed


class AnthropicLlmClient:
    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        base_url: str,
        timeout_seconds: float,
        temperature: float,
        max_tokens: int,
        post: Callable[..., Any] = urlopen,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/") + "/"
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._post = post

    @property
    def base_url(self) -> str:
        return self._base_url.rstrip("/")

    def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        started = time.perf_counter()
        messages = build_chat_messages(request)
        payload = {
            "model": self.model,
            "system": messages[0]["content"],
            "messages": messages[1:],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        for attempt in range(3):
            try:
                response = self._post_json(payload)
                content = extract_anthropic_content(response)
                output_payload = parse_output_payload(content)
                return LlmCompletionResponse(
                    provider=self.provider,
                    model=self.model,
                    content=content,
                    output_payload=output_payload,
                    latency_ms=max(int((time.perf_counter() - started) * 1000), 0),
                )
            except LlmClientError as exc:
                if not exc.retryable or attempt >= 2:
                    raise
                time.sleep(0.2 * (attempt + 1))
        raise LlmClientError("LLM provider retry loop exited unexpectedly.")

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            urljoin(self._base_url, "messages"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=build_anthropic_headers(self._api_key),
            method="POST",
        )
        try:
            with self._post(request, timeout=self._timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body_excerpt = read_error_body_excerpt(exc)
            raise LlmClientError(
                f"LLM provider returned HTTP {exc.code}.",
                error_type="http_error",
                http_status=exc.code,
                response_body_excerpt=body_excerpt,
                retryable=is_retryable_http_status(exc.code),
            ) from exc
        except URLError as exc:
            raise LlmClientError(
                f"LLM provider request failed: {exc.reason}",
                error_type="network_error",
                retryable=True,
            ) from exc
        except TimeoutError as exc:
            raise LlmClientError(
                "LLM provider request timed out.",
                error_type="timeout",
                retryable=True,
            ) from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmClientError(
                "LLM provider returned invalid JSON.",
                error_type="provider_json_parse_error",
                response_body_excerpt=excerpt_text(body),
                retryable=True,
            ) from exc
        if not isinstance(parsed, dict):
            raise LlmClientError(
                "LLM provider returned an invalid response shape.",
                error_type="provider_invalid_shape",
                response_body_excerpt=excerpt_text(body),
                retryable=True,
            )
        return parsed


def create_llm_client(settings: Settings) -> LlmClient:
    provider = settings.llm_provider.strip().lower()
    has_api_key = bool(settings.llm_api_key.strip())
    can_call_without_key = not settings.llm_require_api_key
    if provider in {"openai", "openai-compatible", "openai_compatible", "groq"} and (
        has_api_key or can_call_without_key
    ):
        return OpenAICompatibleLlmClient(
            provider="groq" if provider == "groq" else "openai-compatible",
            model=settings.llm_model,
            api_key=settings.llm_api_key or None,
            base_url=validate_llm_base_url(settings.llm_api_base_url),
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    if provider in {"anthropic", "claude"} and has_api_key:
        return AnthropicLlmClient(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=validate_llm_base_url(
                resolve_anthropic_base_url(settings.llm_api_base_url)
            ),
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )
    return FakeLlmClient()


def validate_llm_base_url(base_url: str) -> str:
    normalized = base_url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("LLM API base URL must be an absolute http(s) URL.")
    return normalized


def build_openai_compatible_headers(api_key: str | None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "aiops-platform/0.1",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def build_anthropic_headers(api_key: str | None) -> dict[str, str]:
    headers = {
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
    }
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def build_chat_messages(request: LlmCompletionRequest) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"{request.prompt_template}\n"
                "Return only a JSON object. The object must include an 'answer' string. "
                "Base the answer only on the provided MCP tool_results and do not expose secrets."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "chat_type": request.chat_type,
                    "prompt_key": request.prompt_key,
                    "input_payload": request.input_payload,
                    "output_schema": request.output_schema,
                },
                ensure_ascii=False,
            ),
        },
    ]


def extract_chat_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LlmClientError(
            "LLM provider response did not include choices.",
            error_type="provider_invalid_shape",
            response_body_excerpt=excerpt_json(response),
            retryable=True,
        )
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise LlmClientError(
            "LLM provider response did not include message content.",
            error_type="provider_invalid_shape",
            response_body_excerpt=excerpt_json(response),
            retryable=True,
        )
    return content


def extract_anthropic_content(response: dict[str, Any]) -> str:
    content_items = response.get("content")
    if not isinstance(content_items, list) or not content_items:
        raise LlmClientError(
            "LLM provider response did not include content.",
            error_type="provider_invalid_shape",
            response_body_excerpt=excerpt_json(response),
            retryable=True,
        )
    first_item = content_items[0]
    text = first_item.get("text") if isinstance(first_item, dict) else None
    if not isinstance(text, str):
        raise LlmClientError(
            "LLM provider response did not include text content.",
            error_type="provider_invalid_shape",
            response_body_excerpt=excerpt_json(response),
            retryable=True,
        )
    return text


def parse_output_payload(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise LlmClientError(
            "LLM response content was not valid JSON.",
            error_type="llm_output_json_parse_error",
            response_body_excerpt=excerpt_text(content),
            retryable=True,
        ) from exc
    if not isinstance(parsed, dict):
        raise LlmClientError(
            "LLM response content JSON was not an object.",
            error_type="llm_output_invalid_shape",
            response_body_excerpt=excerpt_text(content),
            retryable=True,
        )
    if "answer" not in parsed:
        raise LlmClientError(
            "LLM response JSON did not include answer.",
            error_type="llm_output_invalid_shape",
            response_body_excerpt=excerpt_text(content),
            retryable=True,
        )
    return parsed


def resolve_anthropic_base_url(base_url: str) -> str:
    if base_url.rstrip("/") == DEFAULT_OPENAI_BASE_URL:
        return DEFAULT_ANTHROPIC_BASE_URL
    return base_url


def is_retryable_http_status(status_code: int) -> bool:
    return status_code == 429 or 500 <= status_code <= 599


def read_error_body_excerpt(exc: HTTPError) -> str | None:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return None
    return excerpt_text(body)


def excerpt_json(payload: dict[str, Any]) -> str:
    return excerpt_text(json.dumps(payload, ensure_ascii=False))


def excerpt_text(value: str, *, limit: int = 500) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[:limit]}..."


def build_fake_answer(*, chat_type: ChatType, tool_count: int) -> str:
    if chat_type == "farmer_bnpl":
        return (
            f"요청하신 내용을 확인하기 위해 관련 정보 {tool_count}건을 조회했습니다. "
            "외상 한도, 추천 상품, 상환 또는 배송 정보를 기준으로 안내드릴게요."
        )
    return (
        f"운영 판단에 필요한 데이터 {tool_count}건을 조회했습니다. "
        "조회된 지표를 기준으로 리스크와 다음 조치를 정리하겠습니다."
    )
