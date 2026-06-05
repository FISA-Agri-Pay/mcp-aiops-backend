from typing import Annotated

from fastapi import Depends, Request

from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.orchestration.service import OrchestrationService


def get_orchestration_service(request: Request) -> OrchestrationService:
    return request.app.state.orchestration_service


def get_llmops_service(request: Request) -> LlmOpsService:
    return request.app.state.llmops_service


OrchestrationServiceDep = Annotated[
    OrchestrationService,
    Depends(get_orchestration_service),
]
LlmOpsServiceDep = Annotated[
    LlmOpsService,
    Depends(get_llmops_service),
]
