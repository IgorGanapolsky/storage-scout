from __future__ import annotations

import smtplib

from autonomy.providers import EmailConfig, EmailSender


def test_email_sender_preflight_requires_smtp_password() -> None:
    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env="SMTP_PASSWORD_DOES_NOT_EXIST",
        ),
        dry_run=False,
    )
    res = sender.preflight()
    assert res["ok"] is False
    assert res["reason"] == "missing-smtp-password"


def test_email_sender_preflight_blocks_fastmail_without_override(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_PASSWORD_TEST", "pw")
    monkeypatch.delenv("ALLOW_FASTMAIL_OUTREACH", raising=False)

    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host="smtp.fastmail.com",
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env="SMTP_PASSWORD_TEST",
        ),
        dry_run=False,
    )
    res = sender.preflight()
    assert res["ok"] is False
    assert res["reason"] == "blocked-fastmail-outreach"


def test_email_sender_preflight_allows_fastmail_with_override(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_PASSWORD_TEST", "pw")
    monkeypatch.setenv("ALLOW_FASTMAIL_OUTREACH", "1")

    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host="smtp.fastmail.com",
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env="SMTP_PASSWORD_TEST",
        ),
        dry_run=False,
    )
    res = sender.preflight()
    assert res["ok"] is True


def test_email_sender_preflight_does_not_match_lookalike_domains(monkeypatch) -> None:
    # Ensure we don't accidentally treat "evilfastmail.com" as Fastmail.
    monkeypatch.setenv("SMTP_PASSWORD_TEST", "pw")
    monkeypatch.delenv("ALLOW_FASTMAIL_OUTREACH", raising=False)

    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host="smtp.evilfastmail.com",
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env="SMTP_PASSWORD_TEST",
        ),
        dry_run=False,
    )
    res = sender.preflight()
    assert res["ok"] is True


def test_email_sender_preflight_checks_auth_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_PASSWORD_TEST", "pw")
    monkeypatch.setenv("SMTP_PREFLIGHT_AUTH_CHECK", "1")

    seen: dict[str, object] = {}

    class _SMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            seen["host"] = host
            seen["port"] = port
            seen["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def starttls(self) -> None:
            seen["starttls"] = True

        def login(self, user: str, password: str) -> None:
            seen["user"] = user
            seen["password"] = password

    monkeypatch.setattr("autonomy.providers.smtplib.SMTP", _SMTP)

    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env="SMTP_PASSWORD_TEST",
        ),
        dry_run=False,
    )
    res = sender.preflight()
    assert res["ok"] is True
    assert seen["host"] == "smtp.example.com"
    assert seen["user"] == "hello@example.com"


def test_email_sender_preflight_reports_auth_failure_when_login_fails(monkeypatch) -> None:
    monkeypatch.setenv("SMTP_PASSWORD_TEST", "pw")
    monkeypatch.setenv("SMTP_PREFLIGHT_AUTH_CHECK", "1")

    class _SMTPFail:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            self.host = host

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def starttls(self) -> None:
            return None

        def login(self, user: str, password: str) -> None:
            raise smtplib.SMTPAuthenticationError(535, b"auth failed")

    monkeypatch.setattr("autonomy.providers.smtplib.SMTP", _SMTPFail)

    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env="SMTP_PASSWORD_TEST",
        ),
        dry_run=False,
    )
    res = sender.preflight()
    assert res["ok"] is False
    assert res["reason"] == "smtp-auth-failed"
    assert res["error_type"] == "SMTPAuthenticationError"
