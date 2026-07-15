from fastapi import APIRouter, HTTPException

from aiops_platform.api.dependencies import InfraRcaServiceDep
from aiops_platform.infra_rca.schemas import (
    AlertmanagerWebhookRequest,
    AlertWebhookResult,
    DueRcaJobRunResult,
    RcaReportEmailRequest,
    RcaReportEmailResult,
)
from aiops_platform.infra_rca.service import (
    InfraRcaNotFoundError,
    InfraRcaValidationError,
)

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


@router.post("/api/alerts", response_model=AlertWebhookResult)
def receive_alertmanager_api_alert(
    request: AlertmanagerWebhookRequest,
    service: InfraRcaServiceDep,
) -> AlertWebhookResult:
    return receive_alertmanager_webhook(request=request, service=service)


@router.post("/rca/reports/{rca_report_id}/send-email", response_model=RcaReportEmailResult)
def send_rca_report_email(
    rca_report_id: str,
    request: RcaReportEmailRequest,
    service: InfraRcaServiceDep,
) -> RcaReportEmailResult:
    try:
        return service.send_rca_report_email(rca_report_id, request)
    except InfraRcaNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InfraRcaValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/rca/jobs/run-due", response_model=DueRcaJobRunResult)
def run_due_rca_jobs(
    service: InfraRcaServiceDep,
    limit: int = 10,
) -> DueRcaJobRunResult:
    return service.run_due_rca_jobs(limit=limit)
