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

router = APIRouter(prefix="/farmer/chat", tags=["farmer-chat"])


@router.post("/sessions", response_model=ChatSessionResult)
def create_farmer_chat_session(
    request: ChatSessionCreateRequest,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    return service.create_chat_session(
        chat_type="farmer_bnpl",
        user_id=request.user_id,
        title=request.title,
    )


@router.get("/sessions", response_model=ChatSessionListResult)
def list_farmer_chat_sessions(
    service: OrchestrationServiceDep,
    user_id: str = Query(..., min_length=1, max_length=120),
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
) -> ChatSessionListResult:
    try:
        return service.list_chat_sessions(
            chat_type="farmer_bnpl",
            user_id=user_id,
            status=status,
            limit=limit,
        )
    except OrchestrationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=ChatSessionResult)
def get_farmer_chat_session(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    try:
        return service.get_chat_session(session_id, chat_type="farmer_bnpl")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesResult)
def get_farmer_chat_messages(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatMessagesResult:
    try:
        return service.list_chat_messages(session_id, chat_type="farmer_bnpl")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ask", response_model=ChatAskResult)
def ask_farmer_chat(
    request: ChatAskRequest,
    service: OrchestrationServiceDep,
) -> ChatAskResult:
    try:
        return service.ask_farmer_chat(
            message=request.message,
            user_id=request.user_id,
            session_id=request.session_id,
        )
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrchestrationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/close", response_model=ChatSessionResult)
def close_farmer_chat_session(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    try:
        return service.close_chat_session(session_id, chat_type="farmer_bnpl")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
