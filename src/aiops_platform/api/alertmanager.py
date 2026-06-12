from fastapi import APIRouter, Query

from aiops_platform.alertmanager_agent.schemas import AlertmanagerSrePlanResult
from aiops_platform.api.dependencies import AlertmanagerSreAgentServiceDep
from aiops_platform.infra_rca.schemas import AlertmanagerWebhookRequest

router = APIRouter(prefix="/infra-rca/alertmanager", tags=["alertmanager-sre"])


@router.post("/webhook", response_model=AlertmanagerSrePlanResult)
def receive_alertmanager_sre_webhook(
    request: AlertmanagerWebhookRequest,
    service: AlertmanagerSreAgentServiceDep,
    actor: str = Query(default="alertmanager", min_length=1, max_length=120),
) -> AlertmanagerSrePlanResult:
    return service.plan_from_webhook(request, actor=actor)
