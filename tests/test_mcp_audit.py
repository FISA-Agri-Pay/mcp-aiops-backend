from uuid import uuid4

from aiops_platform.mcp.audit import McpToolAuditService
from aiops_platform.mcp.schemas import (
    McpConfirmationPolicy,
    McpToolCallStatus,
    McpToolExecutionContext,
    McpToolPermission,
)


class FakeAuditRepository:
    def __init__(self) -> None:
        self.created_record = None
        self.server_public_id = uuid4()
        self.tool_public_id = uuid4()

    def get_tool_public_ids(self, server_name: str, tool_name: str):
        assert server_name == "infraops-mcp"
        assert tool_name == "query_prometheus"
        return self.server_public_id, self.tool_public_id

    def create_tool_call(self, record):
        self.created_record = record
        return record


def test_audit_service_masks_payloads_and_uses_policy() -> None:
    repository = FakeAuditRepository()
    service = McpToolAuditService(repository)

    record = service.record_tool_call(
        context=McpToolExecutionContext(
            server_name="infraops-mcp",
            tool_name="query_prometheus",
            request_payload={"query": "up", "authorization": "Bearer secret"},
        ),
        permission=McpToolPermission.READ,
        response_payload={"status": "ok", "access_token": "token"},
        call_status=McpToolCallStatus.SUCCESS,
        latency_ms=12,
    )

    assert record.mcp_server_public_id == repository.server_public_id
    assert record.mcp_tool_public_id == repository.tool_public_id
    assert record.confirmation_policy == McpConfirmationPolicy.NONE
    assert record.masked_request_payload == {
        "query": "up",
        "authorization": "***MASKED***",
    }
    assert record.masked_response_payload == {
        "status": "ok",
        "access_token": "***MASKED***",
    }
    assert repository.created_record == record


def test_audit_service_normalizes_list_response_payloads() -> None:
    repository = FakeAuditRepository()
    service = McpToolAuditService(repository)

    record = service.record_tool_call(
        context=McpToolExecutionContext(
            server_name="infraops-mcp",
            tool_name="query_prometheus",
            request_payload={},
        ),
        permission=McpToolPermission.READ,
        response_payload=[{"value": 1, "token": "secret"}],
        call_status=McpToolCallStatus.SUCCESS,
        latency_ms=7,
    )

    assert record.masked_response_payload == {
        "items": [{"value": 1, "token": "***MASKED***"}],
    }
