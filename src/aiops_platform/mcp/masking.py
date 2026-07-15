from typing import Any

MASKED_VALUE = "***MASKED***"

SENSITIVE_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "access_key",
    "refresh_key",
    "private_key",
)


def is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(keyword in normalized for keyword in SENSITIVE_KEYWORDS)


def mask_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: MASKED_VALUE if is_sensitive_key(str(key)) else mask_payload(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [mask_payload(item) for item in value]

    return value

