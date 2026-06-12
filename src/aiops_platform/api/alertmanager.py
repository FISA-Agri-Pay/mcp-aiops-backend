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
    execute: bool = Query(
        default=False,
        description="Execute READ-only evidence collection instead of returning a dry-run plan.",
    ),
    notify: bool = Query(
        default=False,
        description="Send Slack/Email notification after READ-only evidence collection.",
    ),
) -> AlertmanagerSrePlanResult:
    return service.handle_webhook(request, actor=actor, execute=execute, notify=notify)
