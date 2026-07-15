from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import LlmOpsServiceDep
from aiops_platform.llmops.schemas import (
    AgentSnapshotListResult,
    ApprovalRequestListResult,
    LlmRunListResult,
    LlmRunResult,
    NotificationOutboxListResult,
    PromptScope,
    PromptVersionListResult,
)
from aiops_platform.llmops.service import (
    LlmOpsNotFoundError,
    LlmOpsValidationError,
)

router = APIRouter(tags=["llmops"])


@router.get("/prompt-versions", response_model=PromptVersionListResult)
def list_prompt_versions(
    service: LlmOpsServiceDep,
    scope: Annotated[PromptScope | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PromptVersionListResult:
    try:
        return service.list_prompt_versions(scope=scope, limit=limit)
    except LlmOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/llm-runs", response_model=LlmRunListResult)
def list_llm_runs(
    service: LlmOpsServiceDep,
    provider: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> LlmRunListResult:
    try:
        return service.list_llm_runs(provider=provider, status=status, limit=limit)
    except LlmOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/llm-runs/{llm_run_id}", response_model=LlmRunResult)
def get_llm_run(llm_run_id: str, service: LlmOpsServiceDep) -> LlmRunResult:
    try:
        return service.get_llm_run(llm_run_id)
    except LlmOpsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/approvals", response_model=ApprovalRequestListResult)
def list_approval_requests(
    service: LlmOpsServiceDep,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ApprovalRequestListResult:
    try:
        return service.list_approval_requests(status=status, limit=limit)
    except LlmOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/notifications", response_model=NotificationOutboxListResult)
def list_notifications(
    service: LlmOpsServiceDep,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NotificationOutboxListResult:
    try:
        return service.list_notifications(status=status, limit=limit)
    except LlmOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/agent-snapshots", response_model=AgentSnapshotListResult)
def list_agent_snapshots(
    service: LlmOpsServiceDep,
    snapshot_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AgentSnapshotListResult:
    try:
        return service.list_agent_snapshots(snapshot_type=snapshot_type, limit=limit)
    except LlmOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
