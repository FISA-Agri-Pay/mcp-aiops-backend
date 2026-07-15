from __future__ import annotations

import logging
from threading import Event, Thread
from typing import Literal

from aiops_platform.alertmanager_agent.schemas import (
    AlertmanagerSreInspectionRequest,
    AlertmanagerSrePlanResult,
)
from aiops_platform.alertmanager_agent.service import (
    AlertmanagerSreAgentService,
    format_alert_target,
    format_boundary_summary,
    notification_boundaries,
    summarize_tool_execution,
)
from aiops_platform.alertmanager_agent.slack_delivery import (
    SlackDeliveryError,
    SlackSender,
    SlackWebhookSender,
)
from aiops_platform.core.config import Settings, settings

LOGGER = logging.getLogger(__name__)

InspectionStatus = Literal["healthy", "warning", "degraded"]
STATUS_ORDER: dict[str, int] = {"healthy": 0, "warning": 1, "degraded": 2}


class SreInspectionWatcher:
    def __init__(
        self,
        *,
        agent_service: AlertmanagerSreAgentService,
        interval_seconds: int,
        inspection_request: AlertmanagerSreInspectionRequest,
        notify_healthy: bool = True,
        llm_min_status: str = "degraded",
        slack_sender: SlackSender | None = None,
        app_settings: Settings = settings,
    ) -> None:
        self._agent_service = agent_service
        self._interval_seconds = interval_seconds
        self._inspection_request = inspection_request
        self._notify_healthy = notify_healthy
        self._llm_min_status = normalize_inspection_status(llm_min_status)
        self._slack_sender = slack_sender or SlackWebhookSender(app_settings)
        self._settings = app_settings
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run_loop,
            name="sre-inspection-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def run_once(self) -> AlertmanagerSrePlanResult:
        collected = self._agent_service.handle_manual_inspection(
            self._inspection_request,
            actor="sre-inspection-watcher",
            execute=True,
            notify=False,
        )
        observation_status = evaluate_inspection_status(collected)
        should_notify_summary = (
            observation_status != "healthy" or self._notify_healthy
        )
        will_run_llm = should_run_llm_analysis(
            observation_status,
            min_status=self._llm_min_status,
        )
        if should_notify_summary:
            self._send_summary_notification(
                build_inspection_summary_text(
                    collected,
                    observation_status=observation_status,
                    will_run_llm=will_run_llm,
                )
            )
        if will_run_llm:
            return self._agent_service.analyze_collected_result(
                collected,
                notify=True,
            )
        return collected

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self.run_once()
                LOGGER.info(
                    "SRE inspection watcher completed status=%s incident=%s",
                    result.status,
                    result.incident_key,
                )
            except Exception:
                LOGGER.exception("SRE inspection watcher failed")
            self._stop_event.wait(self._interval_seconds)

    def _send_summary_notification(self, text: str) -> None:
        webhook_url = self._settings.rca_slack_webhook_url.strip()
        if not webhook_url:
            LOGGER.info("SRE inspection watcher skipped Slack: webhook URL is empty")
            return
        try:
            self._slack_sender.send_text(
                webhook_url=webhook_url,
                text=text,
                channel=self._settings.rca_slack_channel.strip() or None,
            )
        except SlackDeliveryError:
            LOGGER.exception("SRE inspection watcher Slack delivery failed")


def build_sre_inspection_watcher(
    *,
    agent_service: AlertmanagerSreAgentService,
    app_settings: Settings = settings,
) -> SreInspectionWatcher | None:
    if not app_settings.sre_inspection_watcher_enabled:
        return None
    inspection_request = AlertmanagerSreInspectionRequest(
        inspection_type=normalize_inspection_type(
            app_settings.sre_inspection_watcher_type
        ),
        cluster=app_settings.sre_inspection_watcher_cluster,
        namespace=app_settings.sre_inspection_watcher_namespace,
        service=app_settings.sre_inspection_watcher_service or None,
    )
    return SreInspectionWatcher(
        agent_service=agent_service,
        interval_seconds=app_settings.sre_inspection_watcher_interval_seconds,
        inspection_request=inspection_request,
        notify_healthy=app_settings.sre_inspection_watcher_notify_healthy,
        llm_min_status=app_settings.sre_inspection_watcher_llm_min_status,
        app_settings=app_settings,
    )


def evaluate_inspection_status(result: AlertmanagerSrePlanResult) -> InspectionStatus:
    stats = summarize_tool_execution(result)
    boundaries = notification_boundaries(result, summary={})
    statuses = {
        str(boundary.get("status") or "").strip().lower()
        for boundary in boundaries
        if isinstance(boundary, dict)
    }
    if statuses.intersection({"degraded", "failed", "unhealthy", "down"}):
        return "degraded"
    if stats.get("failed_tools") or statuses.intersection({"unknown", ""}):
        return "warning"
    return "healthy"


def should_run_llm_analysis(
    observation_status: InspectionStatus,
    *,
    min_status: InspectionStatus,
) -> bool:
    return STATUS_ORDER[observation_status] >= STATUS_ORDER[min_status]


def build_inspection_summary_text(
    result: AlertmanagerSrePlanResult,
    *,
    observation_status: InspectionStatus,
    will_run_llm: bool,
) -> str:
    alert = result.alert
    stats = summarize_tool_execution(result)
    boundaries = notification_boundaries(result, summary={})
    boundary_summary = format_boundary_summary(boundaries) or "no boundary evidence"
    target = format_alert_target(alert)
    status_label = {
        "healthy": "정상",
        "warning": "주의",
        "degraded": "위험",
    }[observation_status]
    lines = [
        f"[AIOps] 정기 상태 점검: {status_label}",
        "",
        ":vertical_traffic_light: 1. 요약",
        f"- 대상: {target}",
        f"- 점검 유형: {alert.alert_name if alert is not None else 'manual inspection'}",
        f"- 관측 상태: {status_label}",
        f"- 수집 도구: {stats['successful_tools']}/{stats['total_tools']} succeeded",
        "",
        ":mag_right: 2. 관측값",
        f"- boundaries={boundary_summary}",
    ]
    failed_tools = stats.get("failed_tools") or []
    if failed_tools:
        lines.append(f"- failed_tools={', '.join(failed_tools[:8])}")
    lines.extend(
        [
            "",
            ":hammer_and_wrench: 3. 판단",
            build_inspection_decision_line(
                observation_status=observation_status,
                will_run_llm=will_run_llm,
            ),
            "",
            ":lock: note: 정기 점검은 READ-only로 수행되며 자동 조치는 실행하지 않습니다.",
        ]
    )
    return "\n".join(lines)


def build_inspection_decision_line(
    *,
    observation_status: InspectionStatus,
    will_run_llm: bool,
) -> str:
    if observation_status == "healthy":
        return "- 현재 확인된 즉시 조치 필요 항목은 없습니다."
    if will_run_llm:
        return "- 이상 신호가 감지되어 LLM RCA 분석을 자동 실행합니다."
    return "- 주의 신호가 감지되었습니다. 설정 기준상 LLM 분석은 실행하지 않습니다."


def normalize_inspection_status(value: str) -> InspectionStatus:
    normalized = value.strip().lower()
    if normalized in STATUS_ORDER:
        return normalized  # type: ignore[return-value]
    return "degraded"


def normalize_inspection_type(value: str) -> str:
    normalized = value.strip().lower()
    allowed = {
        "current_state",
        "routing",
        "kubernetes_pod",
        "postgresql",
        "sqs_publish",
        "sqs_consume",
        "application",
    }
    if normalized in allowed:
        return normalized
    return "current_state"
