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

        sender = self._settings.smtp_from.strip() or self._settings.smtp_username.strip()
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = recipient
        message.set_content("This report is available as an HTML email.")
        message.add_alternative(html_body, subtype="html")

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
