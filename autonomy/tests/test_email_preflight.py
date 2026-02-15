from __future__ import annotations

import pytest

from autonomy.providers import EmailConfig, EmailSender


@pytest.mark.parametrize(
    "smtp_host,password_set,allow_fastmail_override,expected_ok,expected_reason",
    [
        ("smtp.example.com", False, None, False, "missing-smtp-password"),
        ("smtp.fastmail.com", True, None, False, "blocked-fastmail-outreach"),
        ("smtp.fastmail.com", True, "1", True, None),
        ("smtp.evilfastmail.com", True, None, True, None),
    ],
)
def test_email_sender_preflight_cases(
    monkeypatch,
    smtp_host: str,
    password_set: bool,
    allow_fastmail_override: str | None,
    expected_ok: bool,
    expected_reason: str | None,
) -> None:
    # Shared config to keep duplication low for SonarCloud's "new code duplication" gate.
    pw_env = "SMTP_PASSWORD_TEST"
    if password_set:
        monkeypatch.setenv(pw_env, "pw")
    else:
        monkeypatch.delenv(pw_env, raising=False)

    if allow_fastmail_override is None:
        monkeypatch.delenv("ALLOW_FASTMAIL_OUTREACH", raising=False)
    else:
        monkeypatch.setenv("ALLOW_FASTMAIL_OUTREACH", allow_fastmail_override)

    sender = EmailSender(
        EmailConfig(
            provider="smtp",
            smtp_host=smtp_host,
            smtp_port=587,
            smtp_user="hello@example.com",
            smtp_password_env=pw_env,
        ),
        dry_run=False,
    )

    res = sender.preflight()
    assert res["ok"] is expected_ok
    if expected_reason is not None:
        assert res["reason"] == expected_reason
