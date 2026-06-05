from fastapi import APIRouter, HTTPException

from aiops_platform.api.dependencies import OrchestrationServiceDep
from aiops_platform.orchestration.schemas import (
    ChatAskRequest,
    ChatAskResult,
    ChatMessagesResult,
    ChatSessionCreateRequest,
    ChatSessionResult,
)
from aiops_platform.orchestration.service import (
    OrchestrationNotFoundError,
    OrchestrationValidationError,
)

router = APIRouter(prefix="/admin/copilot", tags=["admin-copilot"])


@router.post("/sessions", response_model=ChatSessionResult)
def create_admin_copilot_session(
    request: ChatSessionCreateRequest,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    return service.create_chat_session(
        chat_type="admin_copilot",
        user_id=request.user_id,
        title=request.title,
    )


@router.get("/sessions/{session_id}", response_model=ChatSessionResult)
def get_admin_copilot_session(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatSessionResult:
    try:
        return service.get_chat_session(session_id, chat_type="admin_copilot")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesResult)
def get_admin_copilot_messages(
    session_id: str,
    service: OrchestrationServiceDep,
) -> ChatMessagesResult:
    try:
        return service.list_chat_messages(session_id, chat_type="admin_copilot")
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/ask", response_model=ChatAskResult)
def ask_admin_copilot(
    request: ChatAskRequest,
    service: OrchestrationServiceDep,
) -> ChatAskResult:
    try:
        return service.ask_admin_copilot(
            message=request.message,
            user_id=request.user_id,
            session_id=request.session_id,
        )
    except OrchestrationNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OrchestrationValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
