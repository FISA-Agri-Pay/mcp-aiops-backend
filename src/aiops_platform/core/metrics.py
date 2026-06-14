from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Mapping
from typing import Any

PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
APPROX_CHARS_PER_TOKEN = 4

_LOCK = threading.Lock()
_GAUGES: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}

_HELP_TEXT = {
    "aiops_llm_prompt_tokens_last": "Most recent provider-reported LLM prompt token count.",
    "aiops_llm_completion_tokens_last": "Most recent provider-reported LLM completion token count.",
    "aiops_llm_total_tokens_last": "Most recent provider-reported LLM total token count.",
    "aiops_llm_estimated_prompt_tokens_last": "Most recent estimated LLM prompt token count.",
    "aiops_llm_prompt_chars_last": "Most recent serialized LLM prompt character count.",
    "aiops_llm_latency_ms_last": "Most recent LLM request latency in milliseconds.",
    "aiops_llm_request_timestamp_seconds": "Unix timestamp of the most recent LLM request.",
    "aiops_llm_requests_total": "Total LLM requests recorded by the AIOps backend.",
    "aiops_llm_failures_total": "Total failed LLM requests recorded by error type.",
}


def estimate_token_count(char_count: int) -> int:
    return max(math.ceil(max(char_count, 0) / APPROX_CHARS_PER_TOKEN), 0)


def json_char_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def record_llm_request_metrics(
    *,
    provider: str,
    model: str,
    prompt_key: str,
    chat_type: str,
    status: str,
    prompt_chars: int,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    latency_ms: int | None = None,
    error_type: str | None = None,
) -> None:
    labels = {
        "provider": provider or "unknown",
        "model": model or "unknown",
        "prompt_key": prompt_key or "unknown",
        "chat_type": chat_type or "unknown",
    }
    estimated_prompt_tokens = estimate_token_count(prompt_chars)
    with _LOCK:
        _set_gauge("aiops_llm_prompt_chars_last", labels, prompt_chars)
        _set_gauge("aiops_llm_estimated_prompt_tokens_last", labels, estimated_prompt_tokens)
        _set_gauge("aiops_llm_prompt_tokens_last", labels, prompt_tokens or 0)
        _set_gauge("aiops_llm_completion_tokens_last", labels, completion_tokens or 0)
        _set_gauge("aiops_llm_total_tokens_last", labels, total_tokens or 0)
        _set_gauge("aiops_llm_latency_ms_last", labels, latency_ms or 0)
        _set_gauge("aiops_llm_request_timestamp_seconds", labels, time.time())
        _inc_counter(
            "aiops_llm_requests_total",
            {**labels, "status": status or "unknown"},
        )
        if error_type:
            _inc_counter(
                "aiops_llm_failures_total",
                {**labels, "error_type": error_type},
            )


def render_prometheus_metrics() -> str:
    lines: list[str] = []
    with _LOCK:
        metric_items = [
            *((key, value, "gauge") for key, value in sorted(_GAUGES.items())),
            *((key, value, "counter") for key, value in sorted(_COUNTERS.items())),
        ]
    seen_names = set()
    for (name, labels), value, metric_type in metric_items:
        if name not in seen_names:
            lines.append(f"# HELP {name} {_HELP_TEXT.get(name, name)}")
            lines.append(f"# TYPE {name} {metric_type}")
            seen_names.add(name)
        lines.append(f"{name}{format_labels(dict(labels))} {format_number(value)}")
    lines.append("")
    return "\n".join(lines)


def reset_metrics_for_tests() -> None:
    with _LOCK:
        _GAUGES.clear()
        _COUNTERS.clear()


def _set_gauge(name: str, labels: Mapping[str, str], value: float) -> None:
    _GAUGES[(name, normalize_labels(labels))] = float(value)


def _inc_counter(name: str, labels: Mapping[str, str], amount: float = 1.0) -> None:
    key = (name, normalize_labels(labels))
    _COUNTERS[key] = _COUNTERS.get(key, 0.0) + amount


def normalize_labels(labels: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def format_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    values = ",".join(
        f'{key}="{escape_label_value(value)}"' for key, value in sorted(labels.items())
    )
    return f"{{{values}}}"


def escape_label_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.6f}".rstrip("0").rstrip(".")
