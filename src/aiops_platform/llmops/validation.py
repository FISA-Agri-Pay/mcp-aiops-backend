from __future__ import annotations

from typing import Any

from aiops_platform.llmops.schemas import LlmOutputValidationResult


def validate_output_payload(
    payload: dict[str, Any],
    schema: dict[str, Any],
) -> LlmOutputValidationResult:
    required = schema.get("required", [])
    errors = []
    if not isinstance(required, list):
        errors.append("output_schema.required must be a list.")
        required = []
    for field_name in required:
        if not isinstance(field_name, str):
            errors.append("output_schema.required entries must be strings.")
            continue
        if field_name not in payload:
            errors.append(f"{field_name} is required.")
    return LlmOutputValidationResult(is_valid=not errors, errors=errors)
