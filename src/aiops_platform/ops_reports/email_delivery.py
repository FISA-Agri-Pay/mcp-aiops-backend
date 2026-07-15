from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from aiops_platform.core.config import Settings, settings


class EmailDeliveryError(RuntimeError):
    pass


class EmailSender(Protocol):
    def send_html(self, *, recipient: str, subject: str, html_body: str) -> None:
        pass


class SmtpEmailSender:
    def __init__(self, app_settings: Settings = settings) -> None:
        self._settings = app_settings

    def send_html(self, *, recipient: str, subject: str, html_body: str) -> None:
        if self._settings.email_provider.strip().lower() != "smtp":
            raise EmailDeliveryError("email provider is not smtp.")
        if not self._settings.smtp_host.strip():
            raise EmailDeliveryError("SMTP_HOST is required.")
        if not self._settings.smtp_username.strip():
            raise EmailDeliveryError("SMTP_USERNAME is required.")
        if not self._settings.smtp_password:
            raise EmailDeliveryError("SMTP_PASSWORD is required.")

        sender = sanitize_header_value(
            self._settings.smtp_from.strip() or self._settings.smtp_username.strip()
        )
        safe_recipient = sanitize_header_value(recipient)
        safe_subject = sanitize_header_value(subject)
        message = EmailMessage()
        message["Subject"] = safe_subject
        message["From"] = sender
        message["To"] = safe_recipient
        message.set_content(
            "이 리포트는 HTML 이메일 본문으로 제공됩니다.",
            charset="utf-8",
        )
        message.add_alternative(html_body, subtype="html", charset="utf-8")

        try:
            with smtplib.SMTP(
                self._settings.smtp_host,
                self._settings.smtp_port,
                timeout=30,
            ) as smtp:
                if self._settings.smtp_use_tls:
                    smtp.starttls()
                smtp.login(self._settings.smtp_username, self._settings.smtp_password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(str(exc)) from exc


def sanitize_header_value(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())
