from __future__ import annotations

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

