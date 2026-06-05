from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from aiops_platform.admin_riskops.schemas import (
    AlertPreviewResult,
    BnplSummaryResult,
    BnplUserResult,
    BnplUserSearchResult,
    BssScoreHistoryItem,
    BssScoreHistoryResult,
    CreditReviewDetailResult,
    CreditReviewQueueItem,
    CreditReviewQueueResult,
    CreditRiskSummaryResult,
    DisasterCreditRiskResult,
    OverdueSummaryResult,
    OverdueUserSearchResult,
    RiskAnalysisSnapshotResult,
)


class AdminRiskOpsValidationError(ValueError):
    pass


IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}$")
MAX_SEARCH_LIMIT = 100
MAX_ALERT_RECIPIENTS = 100


BNPL_USERS = (
    BnplUserResult(
        user_id="farmer-1",
        farmer_name="Sample farmer",
        region="jeonbuk",
        main_crop="rice",
        credit_limit=3_000_000,
        used_amount=450_000,
        risk_level="LOW",
        overdue_amount=0,
        days_overdue=0,
    ),
    BnplUserResult(
        user_id="farmer-2",
        farmer_name="Pepper grower",
        region="gyeongbuk",
        main_crop="pepper",
        credit_limit=5_000_000,
        used_amount=3_200_000,
        risk_level="MEDIUM",
        overdue_amount=120_000,
        days_overdue=7,
    ),
    BnplUserResult(
        user_id="farmer-3",
        farmer_name="Cabbage farm",
        region="gangwon",
        main_crop="cabbage",
        credit_limit=4_000_000,
        used_amount=3_700_000,
        risk_level="HIGH",
        overdue_amount=550_000,
        days_overdue=21,
    ),
)


CREDIT_REVIEW_QUEUE = (
    CreditReviewQueueItem(
        application_id="credit-app-farmer-2",
        user_id="farmer-2",
        farmer_name="Pepper grower",
        requested_amount=2_500_000,
        risk_level="MEDIUM",
        status="PENDING_REVIEW",
        submitted_at="2026-06-01T09:00:00+00:00",
    ),
    CreditReviewQueueItem(
        application_id="credit-app-farmer-3",
        user_id="farmer-3",
        farmer_name="Cabbage farm",
        requested_amount=4_500_000,
        risk_level="HIGH",
        status="ESCALATED",
        submitted_at="2026-06-02T10:30:00+00:00",
    ),
)


class AdminRiskOpsService:
    def get_credit_review_queue(
        self,
        *,
        status_filter: str | None = None,
        limit: int = 20,
    ) -> CreditReviewQueueResult:
        clamped_limit = clamp_limit(limit)
        normalized_status = normalize_optional_text(status_filter)
        items = [
            item
            for item in CREDIT_REVIEW_QUEUE
            if normalized_status is None or item.status.lower() == normalized_status
        ][:clamped_limit]
        return CreditReviewQueueResult(
            status_filter=status_filter,
            limit=clamped_limit,
            items=items,
        )

    def get_credit_review_detail(self, *, application_id: str) -> CreditReviewDetailResult:
        validate_identifier(application_id, field_name="application_id")
        queue_item = get_review_queue_item(application_id)
        user = get_user(queue_item.user_id)
        return CreditReviewDetailResult(
            application_id=queue_item.application_id,
            user_id=user.user_id,
            farmer_name=user.farmer_name,
            requested_amount=queue_item.requested_amount,
            crop_type=user.main_crop,
            farmland_area_hectare=1.2 if user.user_id == "farmer-2" else 2.5,
            bss_score=720 if user.risk_level == "MEDIUM" else 610,
            risk_level=user.risk_level,
            missing_documents=["insurance_certificate"] if user.user_id == "farmer-2" else [],
            risk_factors=build_risk_factors(user),
            recommended_action=(
                "REQUEST_DOCUMENTS" if user.user_id == "farmer-2" else "ESCALATE"
            ),
        )

    def summarize_credit_risk(self, *, user_id: str) -> CreditRiskSummaryResult:
        user = get_user(user_id)
        return CreditRiskSummaryResult(
            user_id=user.user_id,
            risk_level=user.risk_level,
            bss_score=score_for_user(user),
            credit_limit=user.credit_limit,
            exposure_amount=user.used_amount,
            overdue_amount=user.overdue_amount,
            risk_factors=build_risk_factors(user),
        )

    def get_bnpl_summary(self) -> BnplSummaryResult:
        total_credit_limit = sum(user.credit_limit for user in BNPL_USERS)
        used_amount = sum(user.used_amount for user in BNPL_USERS)
        overdue_users = [user for user in BNPL_USERS if user.overdue_amount > 0]
        return BnplSummaryResult(
            active_users=len(BNPL_USERS),
            total_credit_limit=total_credit_limit,
            used_amount=used_amount,
            available_amount=total_credit_limit - used_amount,
            overdue_users=len(overdue_users),
            overdue_amount=sum(user.overdue_amount for user in overdue_users),
        )

    def search_bnpl_users(
        self,
        *,
        query: str | None = None,
        limit: int = 20,
    ) -> BnplUserSearchResult:
        clamped_limit = clamp_limit(limit)
        normalized_query = normalize_optional_text(query)
        items = [
            user
            for user in BNPL_USERS
            if normalized_query is None or user_matches(user, normalized_query)
        ][:clamped_limit]
        return BnplUserSearchResult(query=query, limit=clamped_limit, items=items)

    def get_overdue_summary(self) -> OverdueSummaryResult:
        overdue_users = [user for user in BNPL_USERS if user.overdue_amount > 0]
        return OverdueSummaryResult(
            overdue_users=len(overdue_users),
            overdue_amount=sum(user.overdue_amount for user in overdue_users),
            max_days_overdue=21,
            high_risk_users=sum(user.risk_level == "HIGH" for user in overdue_users),
        )

    def search_overdue_users(
        self,
        *,
        query: str | None = None,
        min_days_overdue: int = 1,
        limit: int = 20,
    ) -> OverdueUserSearchResult:
        validate_non_negative_int(min_days_overdue, field_name="min_days_overdue")
        clamped_limit = clamp_limit(limit)
        normalized_query = normalize_optional_text(query)
        items = [
            user
            for user in BNPL_USERS
            if user.overdue_amount > 0
            and user.days_overdue >= min_days_overdue
            and (normalized_query is None or user_matches(user, normalized_query))
        ][:clamped_limit]
        return OverdueUserSearchResult(
            query=query,
            min_days_overdue=min_days_overdue,
            limit=clamped_limit,
            items=items,
        )

    def get_bss_score_history(self, *, user_id: str) -> BssScoreHistoryResult:
        user = get_user(user_id)
        base_score = score_for_user(user)
        return BssScoreHistoryResult(
            user_id=user.user_id,
            items=[
                BssScoreHistoryItem(
                    measured_at="2026-04-01T00:00:00+00:00",
                    score=base_score + 20,
                    reason="Initial seasonal credit profile.",
                ),
                BssScoreHistoryItem(
                    measured_at="2026-05-01T00:00:00+00:00",
                    score=base_score,
                    reason="Updated with BNPL usage and repayment status.",
                ),
            ],
        )

    def simulate_disaster_credit_risk(
        self,
        *,
        region: str,
        disaster_type: str,
        affected_crop: str | None = None,
    ) -> DisasterCreditRiskResult:
        normalized_region = normalize_required_text(region, field_name="region")
        normalized_disaster = normalize_required_text(disaster_type, field_name="disaster_type")
        normalized_crop = normalize_optional_text(affected_crop)
        affected_users = [
            user
            for user in BNPL_USERS
            if user.region == normalized_region
            and (normalized_crop is None or user.main_crop == normalized_crop)
        ]
        estimated_exposure = sum(user.used_amount for user in affected_users)
        risk_level = disaster_risk_level(len(affected_users), estimated_exposure)
        return DisasterCreditRiskResult(
            region=normalized_region,
            disaster_type=normalized_disaster,
            affected_crop=normalized_crop,
            affected_users=len(affected_users),
            estimated_exposure_amount=estimated_exposure,
            risk_level=risk_level,
            recommended_actions=[
                "Review affected BNPL users before limit increases.",
                "Prepare repayment grace-period candidates if disaster is confirmed.",
                "Create notification preview for affected users.",
            ],
        )

    def create_risk_analysis_snapshot(
        self,
        *,
        target_type: str,
        target_id: str,
    ) -> RiskAnalysisSnapshotResult:
        normalized_target_type = normalize_required_text(
            target_type,
            field_name="target_type",
        ).upper()
        if normalized_target_type not in {"USER", "REGION", "PORTFOLIO"}:
            raise AdminRiskOpsValidationError("target_type is invalid.")
        validate_identifier(target_id, field_name="target_id")
        summary = self._build_snapshot_summary(normalized_target_type, target_id)
        return RiskAnalysisSnapshotResult(
            snapshot_id=build_snapshot_id(normalized_target_type, target_id),
            target_type=normalized_target_type,
            target_id=target_id,
            summary=summary,
            generated_at=datetime.now(UTC).isoformat(),
        )

    def send_repayment_alert(
        self,
        *,
        user_id: str,
        channel: str = "SMS",
    ) -> AlertPreviewResult:
        user = get_user(user_id)
        normalized_channel = normalize_channel(channel)
        return AlertPreviewResult(
            action="send_repayment_alert",
            target_user_ids=[user.user_id],
            channel=normalized_channel,
            message_template="repayment_due_reminder",
            estimated_recipient_count=1,
            safety_notes=[
                "Notification delivery is a dry-run preview.",
                "No external SMS, Kakao, email, or push request was sent.",
            ],
        )

    def send_overdue_alerts(
        self,
        *,
        min_days_overdue: int = 1,
        channel: str = "SMS",
    ) -> AlertPreviewResult:
        validate_non_negative_int(min_days_overdue, field_name="min_days_overdue")
        normalized_channel = normalize_channel(channel)
        overdue_users = [
            user
            for user in BNPL_USERS
            if user.overdue_amount > 0 and user.days_overdue >= min_days_overdue
        ]
        if len(overdue_users) > MAX_ALERT_RECIPIENTS:
            raise AdminRiskOpsValidationError("too many alert recipients.")
        return AlertPreviewResult(
            action="send_overdue_alerts",
            target_user_ids=[user.user_id for user in overdue_users],
            channel=normalized_channel,
            message_template="overdue_payment_reminder",
            estimated_recipient_count=len(overdue_users),
            safety_notes=[
                "Bulk overdue alert delivery is a dry-run preview.",
                "No external notification channel was called.",
            ],
        )

    def _build_snapshot_summary(self, target_type: str, target_id: str) -> dict[str, int | str]:
        if target_type == "USER":
            risk = self.summarize_credit_risk(user_id=target_id)
            return {
                "risk_level": risk.risk_level,
                "bss_score": risk.bss_score,
                "exposure_amount": risk.exposure_amount,
                "overdue_amount": risk.overdue_amount,
            }
        if target_type == "REGION":
            users = [user for user in BNPL_USERS if user.region == target_id.lower()]
            return {
                "region": target_id.lower(),
                "user_count": len(users),
                "exposure_amount": sum(user.used_amount for user in users),
                "overdue_amount": sum(user.overdue_amount for user in users),
            }
        summary = self.get_bnpl_summary()
        return {
            "active_users": summary.active_users,
            "used_amount": summary.used_amount,
            "overdue_amount": summary.overdue_amount,
        }


def validate_identifier(value: str, *, field_name: str) -> None:
    if isinstance(value, str) and IDENTIFIER_PATTERN.fullmatch(value):
        return
    raise AdminRiskOpsValidationError(f"{field_name} is invalid.")


def normalize_required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise AdminRiskOpsValidationError(f"{field_name} is invalid.")
    normalized = value.strip().lower()
    if normalized:
        return normalized
    raise AdminRiskOpsValidationError(f"{field_name} must not be empty.")


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return normalize_required_text(value, field_name="value")


def validate_non_negative_int(value: int, *, field_name: str) -> None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return
    raise AdminRiskOpsValidationError(f"{field_name} must be greater than or equal to 0.")


def clamp_limit(limit: int) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise AdminRiskOpsValidationError("limit must be an integer.")
    return min(max(limit, 1), MAX_SEARCH_LIMIT)


def normalize_channel(channel: str) -> str:
    normalized_channel = normalize_required_text(channel, field_name="channel").upper()
    if normalized_channel in {"SMS", "KAKAO", "EMAIL", "PUSH"}:
        return normalized_channel
    raise AdminRiskOpsValidationError("channel is invalid.")


def get_user(user_id: str) -> BnplUserResult:
    validate_identifier(user_id, field_name="user_id")
    for user in BNPL_USERS:
        if user.user_id == user_id:
            return user
    raise AdminRiskOpsValidationError("BNPL user was not found.")


def get_review_queue_item(application_id: str) -> CreditReviewQueueItem:
    for item in CREDIT_REVIEW_QUEUE:
        if item.application_id == application_id:
            return item
    raise AdminRiskOpsValidationError("credit review application was not found.")


def user_matches(user: BnplUserResult, query: str) -> bool:
    searchable = f"{user.user_id} {user.farmer_name} {user.region} {user.main_crop}".lower()
    return query in searchable


def build_risk_factors(user: BnplUserResult) -> list[str]:
    factors = []
    if user.used_amount / user.credit_limit > 0.7:
        factors.append("high_limit_utilization")
    if user.overdue_amount > 0:
        factors.append("overdue_balance")
    if user.risk_level == "HIGH":
        factors.append("manual_review_required")
    return factors or ["stable_repayment_profile"]


def score_for_user(user: BnplUserResult) -> int:
    scores = {"LOW": 820, "MEDIUM": 720, "HIGH": 610}
    return scores[user.risk_level]


def disaster_risk_level(affected_users: int, estimated_exposure: int) -> str:
    if affected_users == 0:
        return "LOW"
    if affected_users >= 2 or estimated_exposure >= 3_000_000:
        return "HIGH"
    return "MEDIUM"


def build_snapshot_id(target_type: str, target_id: str) -> str:
    digest = hashlib.sha256(f"{target_type}:{target_id}".encode()).hexdigest()[:8]
    safe_target = target_id.lower().replace("_", "-").replace(".", "-").replace(":", "-")
    return f"risk-snapshot-{target_type.lower()}-{safe_target}-{digest}"
