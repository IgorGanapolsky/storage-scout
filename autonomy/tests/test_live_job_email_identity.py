from __future__ import annotations

from autonomy.engine import EngineConfig
from autonomy.tools.live_job import _apply_runtime_email_identity


def _cfg(*, smtp_user: str, reply_to: str) -> EngineConfig:
    return EngineConfig(
        mode="live",
        company={"name": "AEO", "reply_to": reply_to},
        agents={},
        lead_sources=[],
        email={
            "provider": "smtp",
            "smtp_host": "smtp.fastmail.com",
            "smtp_port": 587,
            "smtp_user": smtp_user,
            "smtp_password_env": "SMTP_PASSWORD",
        },
        compliance={},
        storage={"sqlite_path": "autonomy/state/autonomy_live.sqlite3", "audit_log": "autonomy/state/audit.jsonl"},
    )


def test_apply_runtime_email_identity_prefers_smtp_user_env() -> None:
    cfg = _cfg(smtp_user="hello@aiseoautopilot.com", reply_to="hello@aiseoautopilot.com")
    meta = _apply_runtime_email_identity(
        cfg=cfg,
        env={"SMTP_USER": "ops@aiseoautopilot.com", "FASTMAIL_USER": "legacy@callcatcherops.com"},
    )

    assert cfg.email["smtp_user"] == "ops@aiseoautopilot.com"
    assert cfg.company["reply_to"] == "ops@aiseoautopilot.com"
    assert meta["smtp_source"] == "env.smtp_user"
    assert meta["reply_to_source"] == "auto.smtp_user"


def test_apply_runtime_email_identity_uses_explicit_reply_to_override() -> None:
    cfg = _cfg(smtp_user="hello@aiseoautopilot.com", reply_to="hello@aiseoautopilot.com")
    meta = _apply_runtime_email_identity(
        cfg=cfg,
        env={"FASTMAIL_USER": "hello@callcatcherops.com", "REPLY_TO_EMAIL": "hello@aiseoautopilot.com"},
    )

    assert cfg.email["smtp_user"] == "hello@callcatcherops.com"
    assert cfg.company["reply_to"] == "hello@aiseoautopilot.com"
    assert meta["smtp_source"] == "env.fastmail_user"
    assert meta["reply_to_source"] == "env.reply_to"
