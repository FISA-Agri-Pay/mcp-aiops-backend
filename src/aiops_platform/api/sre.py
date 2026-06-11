from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import OrchestrationServiceDep
from aiops_platform.orchestration.schemas import (
    ChatAskRequest,
    ChatAskResult,
    ChatMessagesResult,
    ChatSessionCreateRequest,
    ChatSessionListResult,
    ChatSessionResult,
)
from aiops_platform.orchestration.service import (
    OrchestrationNotFoundError,
    OrchestrationValidationError,
)

router = APIRouter(prefix="/sre/copilot", tags=["sre-copilot"])


@router.post("/sessions", response_model=ChatSessionResult)
def create_sre_copilot_session(
    request: ChatSessionCreateRequest,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    return service.create_chat_session(
        chat_type="sre_copilot",
        user_id=request.user_id,
        title=request.title,
    )


@router.get("/sessions", response_model=ChatSessionListResult)
def list_sre_copilot_sessions(
    service: OrchestrationServiceDep,
    user_id: str | None = Query(default=None, max_length=120),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> ChatSessionListResult:
    try:
        return service.list_chat_sessions(
            chat_type="sre_copilot",
            user_id=user_id,
            status=status,
            limit=limit,
        )
    except OrchestrationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=ChatSessionResult)
def get_sre_copilot_session(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    try:
        return service.get_chat_session(session_id, chat_type="sre_copilot")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesResult)
def get_sre_copilot_messages(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatMessagesResult:
    try:
        return service.list_chat_messages(session_id, chat_type="sre_copilot")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ask", response_model=ChatAskResult)
def ask_sre_copilot(
    request: ChatAskRequest,
    service: OrchestrationServiceDep,
) -> ChatAskResult:
    try:
        return service.ask_sre_copilot(
            message=request.message,
            user_id=request.user_id,
            session_id=request.session_id,
        )
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrchestrationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
