from __future__ import annotations

import logging
from threading import Event, Thread

from aiops_platform.core.config import Settings, settings
from aiops_platform.prediction_scaling.agent import PredictiveScalingSlackAgentService

LOGGER = logging.getLogger(__name__)


class PredictiveScalingSlackWatcher:
    def __init__(
        self,
        *,
        agent_service: PredictiveScalingSlackAgentService,
        interval_seconds: int,
        namespace: str,
        service: str | None = None,
        horizon_minutes: int = 180,
    ) -> None:
        self._agent_service = agent_service
        self._interval_seconds = interval_seconds
        self._namespace = namespace
        normalized_service = service.strip() if service is not None else ""
        self._service = normalized_service or None
        self._horizon_minutes = horizon_minutes
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(
            target=self._run_loop,
            name="predictive-scaling-slack-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_seconds: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_seconds)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                result = self._agent_service.run_once(
                    namespace=self._namespace,
                    service=self._service,
                    horizon_minutes=self._horizon_minutes,
                    notify=True,
                    dedupe=True,
                )
                LOGGER.info(
                    "predictive scaling watcher completed status=%s services=%s",
                    result.status,
                    ",".join(result.notifiable_services) or "-",
                )
            except Exception:
                LOGGER.exception("predictive scaling watcher failed")
            self._stop_event.wait(self._interval_seconds)


def build_predictive_scaling_slack_watcher(
    *,
    agent_service: PredictiveScalingSlackAgentService,
    app_settings: Settings = settings,
) -> PredictiveScalingSlackWatcher | None:
    if not app_settings.prediction_scaling_watcher_enabled:
        return None
    return PredictiveScalingSlackWatcher(
        agent_service=agent_service,
        interval_seconds=app_settings.prediction_scaling_watcher_interval_seconds,
        namespace=app_settings.prediction_scaling_watcher_namespace,
        service=app_settings.prediction_scaling_watcher_service,
        horizon_minutes=app_settings.prediction_scaling_watcher_horizon_minutes,
    )
