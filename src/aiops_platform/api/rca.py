from fastapi import APIRouter, HTTPException

from aiops_platform.api.dependencies import InfraRcaServiceDep
from aiops_platform.infra_rca.schemas import AlertmanagerWebhookRequest, AlertWebhookResult
from aiops_platform.infra_rca.service import InfraRcaValidationError

router = APIRouter(tags=["infra-rca"])


@router.post("/alerts/webhook", response_model=AlertWebhookResult)
def receive_alertmanager_webhook(
    request: AlertmanagerWebhookRequest,
    service: InfraRcaServiceDep,
) -> AlertWebhookResult:
    try:
        return service.handle_alertmanager_webhook(request)
    except InfraRcaValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
