from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock
from typing import Literal, Protocol, cast

from aiops_platform.alertmanager_agent.slack_delivery import (
    SlackDeliveryError,
    SlackSender,
    SlackWebhookSender,
)
from aiops_platform.core.config import Settings, settings
from aiops_platform.prediction_scaling.schemas import (
    PredictiveScalingSlackAgentResult,
    PredictiveScalingStatusItem,
    PredictiveScalingStatusResult,
)
from aiops_platform.prediction_scaling.service import (
    PredictionScalingService,
    PredictionScalingValidationError,
)

PredictiveScalingRiskLevel = Literal["low", "medium", "high"]

RISK_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


class PredictiveScalingStatusReader(Protocol):
    def get_predictive_scaling_status(
        self,
        *,
        namespace: str | None = None,
        service: str | None = None,
        horizon_minutes: int = 180,
        include_keda: bool = True,
        include_hpa: bool = True,
    ) -> PredictiveScalingStatusResult:
        pass


class PredictiveScalingSlackAgentService:
    def __init__(
        self,
        *,
        status_reader: PredictiveScalingStatusReader | None = None,
        slack_sender: SlackSender | None = None,
        app_settings: Settings = settings,
    ) -> None:
        self._status_reader = status_reader or PredictionScalingService()
        self._settings = app_settings
        self._slack_sender = slack_sender or SlackWebhookSender(app_settings)
        self._lock = Lock()
        self._sent_notification_keys: set[str] = set()

    def run_once(
        self,
        *,
        namespace: str | None = None,
        service: str | None = None,
        horizon_minutes: int = 180,
        include_keda: bool = True,
        include_hpa: bool = True,
        notify: bool = True,
        min_risk: str | None = None,
        dedupe: bool | None = None,
    ) -> PredictiveScalingSlackAgentResult:
        risk_threshold = normalize_risk_threshold(
            min_risk or self._settings.prediction_scaling_slack_min_risk,
        )
        status_result = self._status_reader.get_predictive_scaling_status(
            namespace=namespace,
            service=service,
            horizon_minutes=horizon_minutes,
            include_keda=include_keda,
            include_hpa=include_hpa,
        )
        candidates = select_notifiable_items(status_result.items, min_risk=risk_threshold)
        evaluated_services = [item.service for item in status_result.items]
        if not candidates:
            self._clear_notification_keys()
            return build_agent_result(
                status_result=status_result,
                status="SKIPPED",
                min_risk=risk_threshold,
                evaluated_services=evaluated_services,
                notifiable_items=[],
                notification_sent=False,
                skipped_reason="No service matched the predictive scaling Slack threshold.",
            )

        dedupe_enabled = (
            self._settings.prediction_scaling_slack_dedupe_enabled
            if dedupe is None
            else dedupe
        )
        keyed_candidates = [
            (item, build_notification_key(item)) for item in candidates
        ]
        if dedupe_enabled:
            keyed_candidates = self._filter_new_notification_keys(keyed_candidates)
            if not keyed_candidates:
                return build_agent_result(
                    status_result=status_result,
                    status="SKIPPED",
                    min_risk=risk_threshold,
                    evaluated_services=evaluated_services,
                    notifiable_items=candidates,
                    notification_sent=False,
                    skipped_reason="Current predictive scaling risk was already notified.",
                )

        notifiable_items = [item for item, _ in keyed_candidates]
        message = build_predictive_scaling_slack_text(
            status_result=status_result,
            notifiable_items=notifiable_items,
            min_risk=risk_threshold,
        )
        channel = resolve_slack_channel(self._settings)
        if not notify:
            return build_agent_result(
                status_result=status_result,
                status="DRY_RUN",
                min_risk=risk_threshold,
                evaluated_services=evaluated_services,
                notifiable_items=notifiable_items,
                notification_sent=False,
                channel=channel,
                message=message,
                skipped_reason="notify=false; Slack delivery was not attempted.",
            )

        webhook_url = resolve_slack_webhook_url(self._settings)
        if not webhook_url:
            return build_agent_result(
                status_result=status_result,
                status="SKIPPED",
                min_risk=risk_threshold,
                evaluated_services=evaluated_services,
                notifiable_items=notifiable_items,
                notification_sent=False,
                channel=channel,
                message=message,
                skipped_reason=(
                    "PREDICTION_SCALING_SLACK_WEBHOOK_URL or "
                    "RCA_SLACK_WEBHOOK_URL is required."
                ),
            )

        try:
            self._slack_sender.send_text(
                webhook_url=webhook_url,
                text=message,
                channel=channel,
            )
        except SlackDeliveryError as exc:
            return build_agent_result(
                status_result=status_result,
                status="FAILED",
                min_risk=risk_threshold,
                evaluated_services=evaluated_services,
                notifiable_items=notifiable_items,
                notification_sent=False,
                channel=channel,
                message=message,
                error_message=str(exc),
            )

        if dedupe_enabled:
            self._replace_notification_keys(
                {build_notification_key(item) for item in candidates},
            )
        return build_agent_result(
            status_result=status_result,
            status="NOTIFIED",
            min_risk=risk_threshold,
            evaluated_services=evaluated_services,
            notifiable_items=notifiable_items,
            notification_sent=True,
            channel=channel,
            message=message,
        )

    def _clear_notification_keys(self) -> None:
        with self._lock:
            self._sent_notification_keys.clear()

    def _replace_notification_keys(self, keys: set[str]) -> None:
        with self._lock:
            self._sent_notification_keys = keys

    def _filter_new_notification_keys(
        self,
        keyed_items: list[tuple[PredictiveScalingStatusItem, str]],
    ) -> list[tuple[PredictiveScalingStatusItem, str]]:
        with self._lock:
            return [
                (item, key)
                for item, key in keyed_items
                if key not in self._sent_notification_keys
            ]


def build_agent_result(
    *,
    status_result: PredictiveScalingStatusResult,
    status: Literal["NOTIFIED", "SKIPPED", "DRY_RUN", "FAILED"],
    min_risk: PredictiveScalingRiskLevel,
    evaluated_services: list[str],
    notifiable_items: list[PredictiveScalingStatusItem],
    notification_sent: bool,
    channel: str | None = None,
    message: str | None = None,
    skipped_reason: str | None = None,
    error_message: str | None = None,
) -> PredictiveScalingSlackAgentResult:
    return PredictiveScalingSlackAgentResult(
        status=status,
        namespace=status_result.namespace,
        service=status_result.service,
        horizon_minutes=status_result.horizon_minutes,
        generated_at=datetime.now(UTC).isoformat(),
        min_risk=min_risk,
        evaluated_services=evaluated_services,
        notifiable_services=[item.service for item in notifiable_items],
        notification_sent=notification_sent,
        channel=channel,
        message=message,
        skipped_reason=skipped_reason,
        error_message=error_message,
        predictive_status=status_result,
    )


def normalize_risk_threshold(value: str) -> PredictiveScalingRiskLevel:
    normalized = value.strip().lower()
    if normalized not in RISK_ORDER:
        raise PredictionScalingValidationError(
            "min_risk must be one of: low, medium, high."
        )
    return cast(PredictiveScalingRiskLevel, normalized)


def select_notifiable_items(
    items: list[PredictiveScalingStatusItem],
    *,
    min_risk: PredictiveScalingRiskLevel,
) -> list[PredictiveScalingStatusItem]:
    threshold = RISK_ORDER[min_risk]
    return [item for item in items if RISK_ORDER[item.risk_level] >= threshold]


def resolve_slack_webhook_url(app_settings: Settings) -> str:
    return (
        app_settings.prediction_scaling_slack_webhook_url.strip()
        or app_settings.rca_slack_webhook_url.strip()
    )


def resolve_slack_channel(app_settings: Settings) -> str | None:
    channel = (
        app_settings.prediction_scaling_slack_channel.strip()
        or app_settings.rca_slack_channel.strip()
    )
    return channel or None


def build_predictive_scaling_slack_text(
    *,
    status_result: PredictiveScalingStatusResult,
    notifiable_items: list[PredictiveScalingStatusItem],
    min_risk: PredictiveScalingRiskLevel,
) -> str:
    risk_label = max(
        (item.risk_level for item in notifiable_items),
        key=lambda risk: RISK_ORDER[risk],
    )
    lines = [
        f"[AIOps] 예측형 스케일링 점검: {format_risk_label(risk_label)}",
        "",
        ":vertical_traffic_light: 1. 요약",
        f"- namespace: {status_result.namespace}",
        f"- 예측 범위: 향후 {status_result.horizon_minutes}분",
        f"- 알림 기준: {format_risk_label(min_risk)} 이상",
        f"- 점검 결과: {status_result.summary}",
        "",
        ":mag_right: 2. 예측/스케일링 상세",
    ]
    lines.extend(format_slack_item(item) for item in notifiable_items)
    lines.extend(
        [
            "",
            ":lock: note: 예측값 확인만 수행했으며, 자동 scale 변경은 실행하지 않았습니다.",
        ]
    )
    return "\n".join(lines)


def format_slack_item(item: PredictiveScalingStatusItem) -> str:
    lines = [
        "",
        f"*{item.service}*",
        f"- 위험도: {format_risk_label(item.risk_level)}",
        f"- 예측 일치 상태: {format_prediction_match(item.prediction_match_status)}",
        (
            "- 트래픽: "
            f"예측 RPS {format_number(item.predicted_rps)}, "
            f"현재 RPS {format_number(item.actual_rps)}, "
            f"편차 {format_percent(item.rps_deviation_percent)}"
        ),
        (
            "- Pod 수: "
            f"현재 {format_number(item.current_replicas)}, "
            f"목표 {format_number(item.desired_replicas)}, "
            f"KEDA 적용값 {format_number(item.onprem_adjusted_pods)}, "
            f"차이 {format_signed_number(item.scale_gap)}, "
            f"최대 {format_number(item.max_replicas)}"
        ),
        f"- 스케일링 추적 상태: {format_scaling_status(item.scaling_track_status)}",
        f"- 예측 freshness: {format_freshness(item.prediction_freshness)}",
        (
            "- KEDA/HPA 상태: "
            f"ScalingActive={format_bool(item.scaling_active)}, "
            f"ScalingLimited={format_bool(item.scaling_limited)}"
        ),
    ]
    if item.target_time is not None:
        lines.append(f"- 예측 대상 시각: {item.target_time}")
    if item.model_version is not None:
        lines.append(f"- 모델 버전: {item.model_version}")
    lines.append(f"- 판단: {item.summary}")
    return "\n".join(lines)


def format_optional(value: object) -> str:
    return "unknown" if value is None else str(value)


def format_risk_label(value: str) -> str:
    labels = {
        "low": "낮음",
        "medium": "중간",
        "high": "높음",
    }
    return labels.get(value, value)


def format_prediction_match(value: object) -> str:
    labels = {
        "matched": "예측과 실제가 대체로 일치",
        "under_predicted": "실제 트래픽이 예측보다 큼",
        "over_predicted": "예측이 실제보다 큼",
        "missing_prediction": "예측값 없음",
        "unknown": "확인 불가",
    }
    return labels.get(str(value), str(value))


def format_scaling_status(value: object) -> str:
    labels = {
        "tracking": "예측값을 정상 추적 중",
        "lagging": "예측 대비 Pod 반영 지연",
        "limited": "maxReplica 또는 제한에 걸림",
        "unknown": "확인 불가",
    }
    return labels.get(str(value), str(value))


def format_freshness(value: object) -> str:
    labels = {
        "fresh": "최신",
        "stale": "오래됨",
        "missing": "없음",
        "unknown": "확인 불가",
    }
    return labels.get(str(value), str(value))


def format_bool(value: object) -> str:
    if value is True:
        return "정상"
    if value is False:
        return "아니오"
    return "확인 불가"


def format_number(value: object) -> str:
    if value is None:
        return "확인 불가"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def format_signed_number(value: object) -> str:
    if value is None:
        return "확인 불가"
    if isinstance(value, (float, int)):
        return f"{value:+.2f}".rstrip("0").rstrip(".")
    return str(value)


def format_percent(value: object) -> str:
    if value is None:
        return "확인 불가"
    if isinstance(value, (float, int)):
        return f"{value:.1f}%"
    return str(value)


def build_notification_key(item: PredictiveScalingStatusItem) -> str:
    return "|".join(
        [
            item.namespace,
            item.service,
            item.risk_level,
            str(item.prediction_match_status),
            str(item.actual_rps),
            str(item.predicted_rps),
            str(item.rps_deviation_percent),
            str(item.scaling_track_status),
            str(item.target_time),
            str(item.created_at),
            str(item.scale_gap),
            str(item.current_replicas),
            str(item.desired_replicas),
            str(item.max_replicas),
            str(item.scaling_active),
            str(item.scaling_limited),
            str(item.onprem_adjusted_pods),
        ]
    )
