from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from aiops_platform.orchestration.schemas import ChatType


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


def build_fake_answer(*, chat_type: ChatType, tool_count: int) -> str:
    if chat_type == "farmer_bnpl":
        return (
            f"Agent executed {tool_count} MCP tool checks for the Farmer BNPL flow. "
            "Review tool_results for credit limit, profile, recommendation, and checkout details."
        )
    return (
        f"Agent executed {tool_count} MCP tool checks for the Admin Copilot flow. "
        "Review tool_results for risk, observability, and scaling evidence."
    )
