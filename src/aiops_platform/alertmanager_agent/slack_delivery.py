from __future__ import annotations

import json
from typing import Protocol
from urllib import error, request

from aiops_platform.core.config import Settings, settings


class SlackDeliveryError(RuntimeError):
    pass


class SlackSender(Protocol):
    def send_text(
        self,
        *,
        webhook_url: str,
        text: str,
        channel: str | None = None,
    ) -> None:
        pass


class SlackWebhookSender:
    def __init__(self, app_settings: Settings = settings) -> None:
        self._settings = app_settings

    def send_text(
        self,
        *,
        webhook_url: str,
        text: str,
        channel: str | None = None,
    ) -> None:
        safe_webhook_url = webhook_url.strip()
        if not safe_webhook_url:
            raise SlackDeliveryError("RCA_SLACK_WEBHOOK_URL is required.")
        payload: dict[str, str] = {"text": text}
        safe_channel = normalize_optional_channel(channel)
        if safe_channel is not None:
            payload["channel"] = safe_channel
        encoded = json.dumps(payload).encode("utf-8")
        slack_request = request.Request(
            safe_webhook_url,
            data=encoded,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(
                slack_request,
                timeout=self._settings.rca_slack_timeout_seconds,
            ) as response:
                status = getattr(response, "status", 200)
                if status >= 400:
                    raise SlackDeliveryError(
                        f"Slack webhook returned HTTP {status}."
                    )
        except SlackDeliveryError:
            raise
        except (OSError, error.HTTPError, error.URLError) as exc:
            raise SlackDeliveryError(str(exc)) from exc


def normalize_optional_channel(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.replace("\r", " ").replace("\n", " ").split())
    return normalized or None
