import pytest

from aiops_platform.admin_riskops.service import (
    AdminRiskOpsService,
    AdminRiskOpsValidationError,
)
from tests.seed_constants import (
    CREDIT_APP_2_ID,
    CREDIT_APP_3_ID,
    FARMER_1_ID,
    FARMER_2_ID,
    FARMER_3_ID,
)


def test_credit_review_queue_and_detail_return_admin_review_data() -> None:
    service = AdminRiskOpsService()

    queue = service.get_credit_review_queue(limit=10)
    detail = service.get_credit_review_detail(application_id=CREDIT_APP_2_ID)

    assert [item.application_id for item in queue.items] == [
        CREDIT_APP_2_ID,
        CREDIT_APP_3_ID,
    ]
    assert detail.user_id == FARMER_2_ID
    assert detail.recommended_action == "REQUEST_DOCUMENTS"
    assert "insurance_certificate" in detail.missing_documents


def test_bnpl_and_overdue_summaries_are_deterministic() -> None:
    service = AdminRiskOpsService()

    bnpl_summary = service.get_bnpl_summary()
    overdue_summary = service.get_overdue_summary()

    assert bnpl_summary.active_users == 3
    assert bnpl_summary.used_amount == 7_350_000
    assert bnpl_summary.available_amount == 4_650_000
    assert overdue_summary.overdue_users == 2
    assert overdue_summary.overdue_amount == 670_000


def test_user_search_risk_summary_and_bss_history() -> None:
    service = AdminRiskOpsService()

    users = service.search_bnpl_users(query="pepper", limit=10)
    risk = service.summarize_credit_risk(user_id=FARMER_2_ID)
    history = service.get_bss_score_history(user_id=FARMER_2_ID)

    assert [user.user_id for user in users.items] == [FARMER_2_ID]
    assert risk.risk_level == "MEDIUM"
    assert risk.risk_factors == ["overdue_balance"]
    assert [item.score for item in history.items] == [740, 720]


def test_overdue_disaster_and_snapshot_results() -> None:
    service = AdminRiskOpsService()

    overdue_users = service.search_overdue_users(query="cabbage", min_days_overdue=10)
    disaster = service.simulate_disaster_credit_risk(
        region="gangwon",
        disaster_type="flood",
        affected_crop="custom",
    )
    snapshot = service.create_risk_analysis_snapshot(
        target_type="USER",
        target_id=FARMER_3_ID,
    )

    assert [user.user_id for user in overdue_users.items] == [FARMER_3_ID]
    assert overdue_users.items[0].days_overdue == 21
    assert disaster.affected_users == 1
    assert disaster.risk_level == "HIGH"
    assert snapshot.target_type == "USER"
    assert snapshot.summary["risk_level"] == "HIGH"


def test_admin_alert_tools_return_dry_run_preview_only() -> None:
    service = AdminRiskOpsService()

    repayment = service.send_repayment_alert(user_id=FARMER_1_ID, channel="kakao")
    overdue = service.send_overdue_alerts(min_days_overdue=1, channel="sms")

    assert repayment.dry_run is True
    assert repayment.channel == "KAKAO"
    assert repayment.target_user_ids == [FARMER_1_ID]
    assert overdue.target_user_ids == [FARMER_2_ID, FARMER_3_ID]
    assert overdue.estimated_recipient_count == 2


def test_overdue_filters_apply_min_days_overdue_threshold() -> None:
    service = AdminRiskOpsService()

    overdue_users = service.search_overdue_users(min_days_overdue=10)
    overdue_alert = service.send_overdue_alerts(min_days_overdue=10)

    assert [user.user_id for user in overdue_users.items] == [FARMER_3_ID]
    assert overdue_alert.target_user_ids == [FARMER_3_ID]


def test_invalid_admin_riskops_inputs_raise_domain_errors() -> None:
    service = AdminRiskOpsService()

    with pytest.raises(AdminRiskOpsValidationError, match="limit must be an integer"):
        service.search_bnpl_users(limit=True)

    with pytest.raises(AdminRiskOpsValidationError, match="channel is invalid"):
        service.send_repayment_alert(user_id=FARMER_1_ID, channel="fax")

    with pytest.raises(AdminRiskOpsValidationError, match="BNPL user was not found"):
        service.summarize_credit_risk(user_id="missing-user")
