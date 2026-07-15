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
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        properties = {}
    for field_name, rules in properties.items():
        if field_name not in payload or not isinstance(rules, dict):
            continue
        expected_type = rules.get("type")
        value = payload[field_name]
        if expected_type == "string" and not isinstance(value, str):
            errors.append(f"{field_name} must be a string.")
        if expected_type == "array" and not isinstance(value, list):
            errors.append(f"{field_name} must be an array.")
        if expected_type == "object" and not isinstance(value, dict):
            errors.append(f"{field_name} must be an object.")
    return LlmOutputValidationResult(is_valid=not errors, errors=errors)
