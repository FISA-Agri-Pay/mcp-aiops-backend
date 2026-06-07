from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from aiops_platform.admin_riskops.schemas import (
    AlertPreviewResult,
    BnplSummaryResult,
    BssScoreHistoryResult,
    CreditReviewDetailResult,
    CreditReviewQueueResult,
    CreditRiskSummaryResult,
    DisasterCreditRiskResult,
    OverdueSummaryResult,
)
from aiops_platform.admin_riskops.service import AdminRiskOpsValidationError
from aiops_platform.api.dependencies import AdminRiskOpsServiceDep

router = APIRouter(prefix="/admin/risk", tags=["admin-riskops"])

ADMIN_ROLES = {"SERVICE_ADMIN", "RISK_ADMIN"}


class DisasterSimulationRequest(BaseModel):
    region: str = Field(min_length=1, max_length=120)
    disaster_type: str = Field(min_length=1, max_length=120)
    affected_crop: str | None = Field(default=None, max_length=120)


class RepaymentAlertRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    channel: Literal["SMS", "KAKAO", "EMAIL", "PUSH"] = "SMS"


class OverdueAlertRequest(BaseModel):
    min_days_overdue: int = Field(default=1, ge=0)
    channel: Literal["SMS", "KAKAO", "EMAIL", "PUSH"] = "SMS"


def ensure_admin_role(x_admin_role: str | None) -> None:
    if x_admin_role is None:
        return
    if x_admin_role.strip().upper() in ADMIN_ROLES:
        return
    raise HTTPException(status_code=403, detail="admin role is required.")


@router.get("/credit-reviews", response_model=CreditReviewQueueResult)
def list_credit_reviews(
    service: AdminRiskOpsServiceDep,
    status_filter: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> CreditReviewQueueResult:
    ensure_admin_role(x_admin_role)
    try:
        return service.get_credit_review_queue(status_filter=status_filter, limit=limit)
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/credit-reviews/{review_id}", response_model=CreditReviewDetailResult)
def get_credit_review(
    review_id: str,
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> CreditReviewDetailResult:
    ensure_admin_role(x_admin_role)
    try:
        return service.get_credit_review_detail(application_id=review_id)
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/credit-reviews/{review_id}/summarize", response_model=CreditRiskSummaryResult)
def summarize_credit_review(
    review_id: str,
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> CreditRiskSummaryResult:
    ensure_admin_role(x_admin_role)
    try:
        detail = service.get_credit_review_detail(application_id=review_id)
        return service.summarize_credit_risk(user_id=detail.user_id)
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/bnpl/summary", response_model=BnplSummaryResult)
def get_bnpl_summary(
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> BnplSummaryResult:
    ensure_admin_role(x_admin_role)
    return service.get_bnpl_summary()


@router.get("/overdues/summary", response_model=OverdueSummaryResult)
def get_overdue_summary(
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> OverdueSummaryResult:
    ensure_admin_role(x_admin_role)
    return service.get_overdue_summary()


@router.get("/users/{user_id}/bss-history", response_model=BssScoreHistoryResult)
def get_bss_score_history(
    user_id: str,
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> BssScoreHistoryResult:
    ensure_admin_role(x_admin_role)
    try:
        return service.get_bss_score_history(user_id=user_id)
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/disaster/simulate", response_model=DisasterCreditRiskResult)
def simulate_disaster_credit_risk(
    request: DisasterSimulationRequest,
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> DisasterCreditRiskResult:
    ensure_admin_role(x_admin_role)
    try:
        return service.simulate_disaster_credit_risk(
            region=request.region,
            disaster_type=request.disaster_type,
            affected_crop=request.affected_crop,
        )
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/alerts/repayment", response_model=AlertPreviewResult)
def preview_repayment_alert(
    request: RepaymentAlertRequest,
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> AlertPreviewResult:
    ensure_admin_role(x_admin_role)
    try:
        return service.send_repayment_alert(user_id=request.user_id, channel=request.channel)
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/alerts/overdue", response_model=AlertPreviewResult)
def preview_overdue_alerts(
    request: OverdueAlertRequest,
    service: AdminRiskOpsServiceDep,
    x_admin_role: str | None = Header(default=None, alias="X-Admin-Role"),
) -> AlertPreviewResult:
    ensure_admin_role(x_admin_role)
    try:
        return service.send_overdue_alerts(
            min_days_overdue=request.min_days_overdue,
            channel=request.channel,
        )
    except AdminRiskOpsValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
