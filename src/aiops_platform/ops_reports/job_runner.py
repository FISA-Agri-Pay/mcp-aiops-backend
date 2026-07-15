from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiops_platform.core.config import Settings, get_settings
from aiops_platform.ops_reports.schemas import (
    OpsReportCreateRequest,
    OpsReportEmailRequest,
    OpsReportType,
)
from aiops_platform.ops_reports.service import OpsReportService, OpsReportValidationError

logger = logging.getLogger(__name__)

OpsReportJobMode = OpsReportType


@dataclass(frozen=True)
class OpsReportJobResult:
    report_id: str
    report_type: OpsReportType
    report_date: date
    email_status: str
    notification_ids: list[str]


def parse_recipients(raw_recipients: str) -> list[str]:
    normalized = raw_recipients.replace(";", ",").replace("\n", ",")
    return [recipient.strip() for recipient in normalized.split(",") if recipient.strip()]


def resolve_report_job_date(
    mode: OpsReportJobMode,
    *,
    now: datetime | None = None,
    timezone: str = "Asia/Seoul",
) -> date:
    try:
        tzinfo = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise OpsReportValidationError("timezone is invalid.") from exc

    local_today = (now or datetime.now(tzinfo)).astimezone(tzinfo).date()
    if mode == "DAILY":
        return local_today - timedelta(days=1)
    current_week_start = local_today - timedelta(days=local_today.weekday())
    return current_week_start - timedelta(days=7)


def run_ops_report_job(
    mode: OpsReportJobMode,
    *,
    service: OpsReportService | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
    report_date: date | None = None,
    namespace: str | None = None,
    service_name: str | None = None,
) -> OpsReportJobResult:
    resolved_settings = settings or get_settings()
    recipients = parse_recipients(resolved_settings.ops_report_email_recipients)
    if not recipients:
        raise OpsReportValidationError("OPS_REPORT_EMAIL_RECIPIENTS is required.")

    timezone = resolved_settings.app_timezone
    resolved_report_date = report_date or resolve_report_job_date(
        mode,
        now=now,
        timezone=timezone,
    )
    resolved_namespace = namespace if namespace is not None else os.getenv("OPS_REPORT_NAMESPACE")
    resolved_service_name = (
        service_name if service_name is not None else os.getenv("OPS_REPORT_SERVICE_NAME")
    )
    report_service = service or OpsReportService()

    logger.info(
        "Creating %s ops report for report_date=%s namespace=%s service_name=%s.",
        mode,
        resolved_report_date.isoformat(),
        resolved_namespace or "-",
        resolved_service_name or "-",
    )
    report_result = report_service.create_ops_report(
        OpsReportCreateRequest(
            report_type=mode,
            report_date=resolved_report_date,
            timezone=timezone,
            namespace=resolved_namespace,
            service_name=resolved_service_name,
        )
    )
    report_id = report_result.report.report_id

    logger.info(
        "Sending %s ops report email for report_id=%s to %d recipients.",
        mode,
        report_id,
        len(recipients),
    )
    email_result = report_service.send_ops_report_email(
        report_id,
        OpsReportEmailRequest(recipients=recipients),
    )
    logger.info(
        "Ops report job completed: report_id=%s email_status=%s notifications=%s.",
        report_id,
        email_result.status,
        ",".join(email_result.notification_ids),
    )
    return OpsReportJobResult(
        report_id=report_id,
        report_type=mode,
        report_date=resolved_report_date,
        email_status=email_result.status,
        notification_ids=email_result.notification_ids,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled operations report jobs.")
    parser.add_argument("mode", choices=["daily", "weekly"], help="Report schedule mode.")
    parser.add_argument("--report-date", help="Override report date in YYYY-MM-DD format.")
    parser.add_argument("--namespace", help="Override report namespace filter.")
    parser.add_argument("--service-name", help="Override report service/workload filter.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    report_date = date.fromisoformat(args.report_date) if args.report_date else None
    mode: OpsReportJobMode = "DAILY" if args.mode == "daily" else "WEEKLY"
    try:
        run_ops_report_job(
            mode,
            report_date=report_date,
            namespace=args.namespace,
            service_name=args.service_name,
        )
    except Exception:
        logger.exception("Ops report job failed.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
