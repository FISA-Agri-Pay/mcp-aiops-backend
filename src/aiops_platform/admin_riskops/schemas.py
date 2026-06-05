from typing import Any, Literal

from pydantic import BaseModel, Field


class CreditReviewQueueItem(BaseModel):
    application_id: str
    user_id: str
    farmer_name: str
    requested_amount: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    status: Literal["PENDING_REVIEW", "NEEDS_DOCUMENTS", "ESCALATED"]
    submitted_at: str


class CreditReviewQueueResult(BaseModel):
    status_filter: str | None = None
    limit: int
    items: list[CreditReviewQueueItem]


class CreditReviewDetailResult(BaseModel):
    application_id: str
    user_id: str
    farmer_name: str
    requested_amount: int
    crop_type: str
    farmland_area_hectare: float
    bss_score: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    missing_documents: list[str]
    risk_factors: list[str]
    recommended_action: Literal["APPROVE", "REQUEST_DOCUMENTS", "ESCALATE"]


class CreditRiskSummaryResult(BaseModel):
    user_id: str
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    bss_score: int
    credit_limit: int
    exposure_amount: int
    overdue_amount: int
    risk_factors: list[str]


class BnplSummaryResult(BaseModel):
    active_users: int
    total_credit_limit: int
    used_amount: int
    available_amount: int
    overdue_users: int
    overdue_amount: int
    currency: Literal["KRW"] = "KRW"


class BnplUserResult(BaseModel):
    user_id: str
    farmer_name: str
    region: str
    main_crop: str
    credit_limit: int
    used_amount: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    overdue_amount: int
    days_overdue: int


class BnplUserSearchResult(BaseModel):
    query: str | None = None
    limit: int
    items: list[BnplUserResult]


class OverdueSummaryResult(BaseModel):
    overdue_users: int
    overdue_amount: int
    max_days_overdue: int
    high_risk_users: int
    currency: Literal["KRW"] = "KRW"


class OverdueUserSearchResult(BaseModel):
    query: str | None = None
    min_days_overdue: int
    limit: int
    items: list[BnplUserResult]


class BssScoreHistoryItem(BaseModel):
    measured_at: str
    score: int
    reason: str


class BssScoreHistoryResult(BaseModel):
    user_id: str
    items: list[BssScoreHistoryItem]


class DisasterCreditRiskResult(BaseModel):
    region: str
    disaster_type: str
    affected_crop: str | None = None
    affected_users: int
    estimated_exposure_amount: int
    risk_level: Literal["LOW", "MEDIUM", "HIGH"]
    recommended_actions: list[str]
    currency: Literal["KRW"] = "KRW"


class RiskAnalysisSnapshotResult(BaseModel):
    snapshot_id: str
    target_type: Literal["USER", "REGION", "PORTFOLIO"]
    target_id: str
    summary: dict[str, Any]
    generated_at: str


class AlertPreviewResult(BaseModel):
    action: str
    dry_run: bool = True
    target_user_ids: list[str]
    channel: Literal["SMS", "KAKAO", "EMAIL", "PUSH"]
    message_template: str
    estimated_recipient_count: int
    safety_notes: list[str] = Field(default_factory=list)
