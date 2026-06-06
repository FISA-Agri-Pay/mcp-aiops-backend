from __future__ import annotations

from email import policy
from email.parser import BytesParser

from aiops_platform.core.config import Settings
from aiops_platform.ops_reports import email_delivery
from aiops_platform.ops_reports.email_delivery import SmtpEmailSender


def test_smtp_email_sender_encodes_korean_subject(monkeypatch) -> None:
    sent_messages: list[bytes] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            assert host == "smtp.example.com"
            assert port == 587
            assert timeout == 30

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, username: str, password: str) -> None:
            assert username == "sender@example.com"
            assert password == "app-password"

        def send_message(self, message) -> None:
            sent_messages.append(message.as_bytes())

    monkeypatch.setattr(email_delivery.smtplib, "SMTP", FakeSmtp)
    sender = SmtpEmailSender(
        Settings(
            EMAIL_PROVIDER="smtp",
            SMTP_HOST="smtp.example.com",
            SMTP_PORT=587,
            SMTP_USERNAME="sender@example.com",
            SMTP_PASSWORD="app-password",
            SMTP_FROM="sender@example.com",
            SMTP_USE_TLS=True,
        )
    )

    sender.send_html(
        recipient="recipient@example.com",
        subject="[AIOps] 일일 운영 리포트 - 2026-06-06",
        html_body="<h1>일일 운영 리포트</h1>",
    )

    parsed = BytesParser(policy=policy.default).parsebytes(sent_messages[0])
    assert parsed["Subject"] == "[AIOps] 일일 운영 리포트 - 2026-06-06"
