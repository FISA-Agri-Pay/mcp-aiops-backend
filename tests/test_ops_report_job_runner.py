from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from aiops_platform.ops_reports.job_runner import (
    parse_recipients,
    resolve_report_job_date,
    run_ops_report_job,
)
from aiops_platform.ops_reports.schemas import (
    OpsReportCreateRequest,
    OpsReportEmailRequest,
    OpsReportEmailResult,
)
from aiops_platform.ops_reports.service import OpsReportValidationError
from tests.test_ops_reports_service import build_endpoint_generation_result


@dataclass
class FakeSettings:
    app_timezone: str = "Asia/Seoul"
    ops_report_email_recipients: str = "ops@example.com,sre@example.com"


class FakeOpsReportJobService:
    def __init__(self) -> None:
        self.create_requests: list[OpsReportCreateRequest] = []
        self.email_requests: list[OpsReportEmailRequest] = []

    def create_ops_report(self, request: OpsReportCreateRequest):
        self.create_requests.append(request)
        return build_endpoint_generation_result()

    def send_ops_report_email(self, report_id: str, request: OpsReportEmailRequest):
        self.email_requests.append(request)
        return OpsReportEmailResult(
            report_id=report_id,
            notification_ids=["notification-1", "notification-2"],
            status="SENT",
        )


def test_ops_report_job_parses_recipients_from_env_style_value() -> None:
    assert parse_recipients("ops@example.com, sre@example.com\nadmin@example.com") == [
        "ops@example.com",
        "sre@example.com",
        "admin@example.com",
    ]


def test_ops_report_job_resolves_daily_and_weekly_report_dates() -> None:
    now = datetime(2026, 6, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))

    assert resolve_report_job_date("DAILY", now=now) == date(2026, 6, 14)
    assert resolve_report_job_date("WEEKLY", now=now) == date(2026, 6, 8)


def test_ops_report_job_creates_report_and_sends_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_REPORT_NAMESPACE", "aiops")
    monkeypatch.setenv("OPS_REPORT_SERVICE_NAME", "mcp-aiops-backend")
    service = FakeOpsReportJobService()

    result = run_ops_report_job(
        "DAILY",
        service=service,
        settings=FakeSettings(),
        now=datetime(2026, 6, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    assert result.report_id == "report-1"
    assert result.report_type == "DAILY"
    assert result.report_date == date(2026, 6, 14)
    assert result.email_status == "SENT"
    assert service.create_requests[0].namespace == "aiops"
    assert service.create_requests[0].service_name == "mcp-aiops-backend"
    assert service.email_requests[0].recipients == ["ops@example.com", "sre@example.com"]


def test_ops_report_job_requires_recipients() -> None:
    with pytest.raises(OpsReportValidationError, match="OPS_REPORT_EMAIL_RECIPIENTS"):
        run_ops_report_job(
            "DAILY",
            service=FakeOpsReportJobService(),
            settings=FakeSettings(ops_report_email_recipients=" "),
            now=datetime(2026, 6, 15, 9, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        )
