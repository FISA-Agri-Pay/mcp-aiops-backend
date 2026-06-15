from __future__ import annotations

from fastapi.testclient import TestClient

from aiops_platform.core.config import Settings
from aiops_platform.main import create_app
from aiops_platform.prediction_scaling.agent import PredictiveScalingSlackAgentService
from aiops_platform.prediction_scaling.schemas import (
    PredictiveScalingSlackAgentResult,
    PredictiveScalingStatusItem,
    PredictiveScalingStatusResult,
)
from aiops_platform.prediction_scaling.watcher import build_predictive_scaling_slack_watcher


class FakeStatusReader:
    def __init__(
        self,
        *,
        risk_level: str = "high",
        scale_gap: float | None = 3.0,
    ) -> None:
        self.risk_level = risk_level
        self.scale_gap = scale_gap

    def get_predictive_scaling_status(self, **kwargs) -> PredictiveScalingStatusResult:
        item = build_status_item(risk_level=self.risk_level, scale_gap=self.scale_gap)
        return PredictiveScalingStatusResult(
            namespace=kwargs.get("namespace") or "kkpp",
            service=kwargs.get("service"),
            horizon_minutes=kwargs.get("horizon_minutes") or 180,
            generated_at="2026-06-15T00:00:00+00:00",
            items=[item],
            summary="1 service(s) show high predictive scaling risk."
            if item.risk_level == "high"
            else "All evaluated services show low predictive scaling risk.",
        )


class FakeSlackSender:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, str | None]] = []

    def send_text(
        self,
        *,
        webhook_url: str,
        text: str,
        channel: str | None = None,
    ) -> None:
        self.sent_messages.append(
            {
                "webhook_url": webhook_url,
                "text": text,
                "channel": channel,
            }
        )


class FakeEndpointAgent:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_once(self, **kwargs) -> PredictiveScalingSlackAgentResult:
        self.calls.append(kwargs)
        status_result = PredictiveScalingStatusResult(
            namespace=kwargs.get("namespace") or "kkpp",
            service=kwargs.get("service"),
            horizon_minutes=kwargs.get("horizon_minutes") or 180,
            generated_at="2026-06-15T00:00:00+00:00",
            items=[build_status_item()],
            summary="1 service(s) show high predictive scaling risk.",
        )
        return PredictiveScalingSlackAgentResult(
            status="DRY_RUN",
            namespace=status_result.namespace,
            service=status_result.service,
            horizon_minutes=status_result.horizon_minutes,
            generated_at="2026-06-15T00:00:01+00:00",
            min_risk="high",
            evaluated_services=["service-payment"],
            notifiable_services=["service-payment"],
            notification_sent=False,
            channel="#aiops-alerts",
            message="dry-run",
            predictive_status=status_result,
        )


def build_status_item(
    *,
    risk_level: str = "high",
    scale_gap: float | None = 3.0,
) -> PredictiveScalingStatusItem:
    return PredictiveScalingStatusItem(
        namespace="kkpp",
        service="service-payment",
        short_service="payment",
        deployment="service-payment",
        scaled_object="service-payment-gru",
        hpa="keda-hpa-service-payment-gru",
        model_version="service_gru_annual_2026_20260614082519",
        target_time="2026-06-15T00:05:00+00:00",
        created_at="2026-06-15T00:00:00+00:00",
        predicted_rps=250.0,
        predicted_pods=4.0,
        base_pods=1.0,
        extra_demand=8.0,
        allocation_score=8.0,
        onprem_adjusted_pods=4.0,
        current_replicas=1 if risk_level == "high" else 4,
        desired_replicas=1 if risk_level == "high" else 4,
        max_replicas=8,
        scale_gap=scale_gap,
        scaling_active=True,
        scaling_limited=False,
        prediction_freshness="fresh",
        actual_rps=380.0 if risk_level == "high" else 260.0,
        rps_deviation=130.0 if risk_level == "high" else 10.0,
        rps_deviation_percent=52.0 if risk_level == "high" else 4.0,
        prediction_match_status="under_predicted" if risk_level == "high" else "matched",
        scaling_track_status="lagging" if risk_level == "high" else "tracking",
        risk_level=risk_level,
        summary="service-payment: predictive scale gap is high.",
    )


def build_settings() -> Settings:
    return Settings(
        PREDICTION_SCALING_SLACK_WEBHOOK_URL="https://hooks.slack.com/services/test",
        PREDICTION_SCALING_SLACK_CHANNEL="#aiops-alerts",
    )


def test_predictive_scaling_slack_agent_sends_high_risk_notification() -> None:
    slack_sender = FakeSlackSender()
    service = PredictiveScalingSlackAgentService(
        status_reader=FakeStatusReader(risk_level="high"),
        slack_sender=slack_sender,
        app_settings=build_settings(),
    )

    result = service.run_once()

    assert result.status == "NOTIFIED"
    assert result.notification_sent is True
    assert result.notifiable_services == ["service-payment"]
    assert slack_sender.sent_messages[0]["channel"] == "#aiops-alerts"
    assert "Predictive scaling risk: HIGH" in slack_sender.sent_messages[0]["text"]
    assert "service-payment" in slack_sender.sent_messages[0]["text"]
    assert "prediction_match=under_predicted" in slack_sender.sent_messages[0]["text"]
    assert "hooks.slack.com" not in result.model_dump_json()


def test_predictive_scaling_slack_agent_skips_low_risk_status() -> None:
    slack_sender = FakeSlackSender()
    service = PredictiveScalingSlackAgentService(
        status_reader=FakeStatusReader(risk_level="low", scale_gap=0),
        slack_sender=slack_sender,
        app_settings=build_settings(),
    )

    result = service.run_once()

    assert result.status == "SKIPPED"
    assert result.notifiable_services == []
    assert slack_sender.sent_messages == []


def test_predictive_scaling_slack_agent_skips_when_webhook_is_missing() -> None:
    slack_sender = FakeSlackSender()
    service = PredictiveScalingSlackAgentService(
        status_reader=FakeStatusReader(risk_level="high"),
        slack_sender=slack_sender,
        app_settings=Settings(
            PREDICTION_SCALING_SLACK_WEBHOOK_URL="",
            RCA_SLACK_WEBHOOK_URL="",
            PREDICTION_SCALING_SLACK_CHANNEL="#aiops-alerts",
        ),
    )

    result = service.run_once()

    assert result.status == "SKIPPED"
    assert result.notification_sent is False
    assert "WEBHOOK_URL" in (result.skipped_reason or "")
    assert slack_sender.sent_messages == []


def test_predictive_scaling_slack_agent_dedupes_same_risk_fingerprint() -> None:
    slack_sender = FakeSlackSender()
    service = PredictiveScalingSlackAgentService(
        status_reader=FakeStatusReader(risk_level="high"),
        slack_sender=slack_sender,
        app_settings=build_settings(),
    )

    first = service.run_once()
    second = service.run_once()

    assert first.status == "NOTIFIED"
    assert second.status == "SKIPPED"
    assert second.skipped_reason == "Current predictive scaling risk was already notified."
    assert len(slack_sender.sent_messages) == 1


def test_predictive_scaling_slack_agent_dry_run_builds_message_without_sending() -> None:
    slack_sender = FakeSlackSender()
    service = PredictiveScalingSlackAgentService(
        status_reader=FakeStatusReader(risk_level="high"),
        slack_sender=slack_sender,
        app_settings=build_settings(),
    )

    result = service.run_once(notify=False)

    assert result.status == "DRY_RUN"
    assert result.notification_sent is False
    assert result.message is not None
    assert "scale" in result.message.lower()
    assert slack_sender.sent_messages == []


def test_predictive_scaling_slack_agent_api_runs_configured_service() -> None:
    app = create_app()
    fake_service = FakeEndpointAgent()
    app.state.predictive_scaling_slack_agent_service = fake_service
    client = TestClient(app)

    response = client.post(
        "/prediction-scaling/slack-agent/run?notify=false&service=service-payment",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "DRY_RUN"
    assert fake_service.calls[0]["notify"] is False
    assert fake_service.calls[0]["service"] == "service-payment"


def test_predictive_scaling_slack_watcher_factory_respects_enabled_flag() -> None:
    agent_service = PredictiveScalingSlackAgentService(
        status_reader=FakeStatusReader(),
        slack_sender=FakeSlackSender(),
        app_settings=build_settings(),
    )

    disabled = build_predictive_scaling_slack_watcher(
        agent_service=agent_service,
        app_settings=Settings(PREDICTION_SCALING_WATCHER_ENABLED=False),
    )
    enabled = build_predictive_scaling_slack_watcher(
        agent_service=agent_service,
        app_settings=Settings(
            PREDICTION_SCALING_WATCHER_ENABLED=True,
            PREDICTION_SCALING_WATCHER_INTERVAL_SECONDS=30,
        ),
    )

    assert disabled is None
    assert enabled is not None
