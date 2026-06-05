from typing import Annotated

from fastapi import Depends, Request

from aiops_platform.orchestration.service import OrchestrationService


def get_orchestration_service(request: Request) -> OrchestrationService:
    return request.app.state.orchestration_service


OrchestrationServiceDep = Annotated[
    OrchestrationService,
    Depends(get_orchestration_service),
]
