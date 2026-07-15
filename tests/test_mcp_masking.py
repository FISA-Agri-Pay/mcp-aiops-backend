from aiops_platform.mcp.masking import MASKED_VALUE, mask_payload


def test_mask_payload_redacts_nested_sensitive_values() -> None:
    payload = {
        "username": "farmer-1",
        "password": "secret-password",
        "headers": {
            "Authorization": "Bearer abc",
            "trace_id": "trace-1",
        },
        "items": [
            {"api_key": "key-1"},
            {"quantity": 3},
        ],
    }

    assert mask_payload(payload) == {
        "username": "farmer-1",
        "password": MASKED_VALUE,
        "headers": {
            "Authorization": MASKED_VALUE,
            "trace_id": "trace-1",
        },
        "items": [
            {"api_key": MASKED_VALUE},
            {"quantity": 3},
        ],
    }

