from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from aiops_platform.api.dependencies import OpsReportServiceDep
from aiops_platform.ops_reports.schemas import (
    OpsReportCreateRequest,
    OpsReportDetailResult,
    OpsReportEmailRequest,
    OpsReportEmailResult,
    OpsReportGenerationResult,
    OpsReportListResult,
    ReportMetricSummaryResult,
)
from aiops_platform.ops_reports.service import (
    OpsReportNotFoundError,
    OpsReportValidationError,
)

router = APIRouter(prefix="/reports/ops", tags=["ops-reports"])


@router.post("", response_model=OpsReportGenerationResult)
def create_ops_report(
    request: OpsReportCreateRequest,
    service: OpsReportServiceDep,
) -> OpsReportGenerationResult:
    try:
        return service.create_ops_report(request)
    except OpsReportValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("", response_model=OpsReportListResult)
def list_ops_reports(
    service: OpsReportServiceDep,
    report_type: Annotated[str | None, Query()] = None,
    status: Annotated[str | None, Query()] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    namespace: Annotated[str | None, Query()] = None,
    service_name: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> OpsReportListResult:
    try:
        return service.list_ops_reports(
            report_type=report_type,
            status=status,
            date_from=date_from,
            date_to=date_to,
            namespace=namespace,
            service_name=service_name,
            limit=limit,
        )
    except OpsReportValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{report_id}", response_model=OpsReportDetailResult)
def get_ops_report(
    report_id: str,
    service: OpsReportServiceDep,
) -> OpsReportDetailResult:
    try:
        return service.get_ops_report(report_id)
    except OpsReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{report_id}/metric-summaries", response_model=list[ReportMetricSummaryResult])
def list_ops_report_metric_summaries(
    report_id: str,
    service: OpsReportServiceDep,
) -> list[ReportMetricSummaryResult]:
    try:
        return service.list_metric_summaries(report_id)
    except OpsReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{report_id}/send-email", response_model=OpsReportEmailResult)
def send_ops_report_email(
    report_id: str,
    request: OpsReportEmailRequest,
    service: OpsReportServiceDep,
) -> OpsReportEmailResult:
    try:
        return service.send_ops_report_email(report_id, request)
    except OpsReportNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OpsReportValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
