from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime as real_datetime
from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.twilio_sms import (
    _is_business_hours,
    _lead_texted_recently,
    load_sms_config,
    normalize_phone,
    run_sms_followup,
    send_sms,
)


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, n: int | None = None) -> bytes:
        if n is None or n < 0:
            return self._body
        return self._body[:n]

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _build_http_error(*, status: int, payload: dict) -> urllib.error.HTTPError:
    body = json.dumps(payload).encode("utf-8")
    return urllib.error.HTTPError(
        url="https://api.twilio.com/2010-04-01/Accounts/AC123/Messages.json",
        code=int(status),
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(body),
    )


# --- normalize_phone ---


def test_normalize_phone_various_formats() -> None:
    assert normalize_phone("") == ""
    assert normalize_phone("954-621-1439") == "+19546211439"
    assert normalize_phone("(954) 621-1439") == "+19546211439"
    assert normalize_phone("+1 (954) 621-1439") == "+19546211439"
    assert normalize_phone("1 954 621 1439") == "+19546211439"
    assert normalize_phone("9546211439") == "+19546211439"
    assert normalize_phone("12345") == ""  # too short


# --- load_sms_config ---


def test_load_sms_config_disabled_by_default() -> None:
    assert load_sms_config({}) is None
    assert load_sms_config({"AUTO_SMS_ENABLED": "0"}) is None
    assert load_sms_config({"AUTO_SMS_ENABLED": "false"}) is None


def test_load_sms_config_missing_twilio_env() -> None:
    env = {"AUTO_SMS_ENABLED": "1"}
    assert load_sms_config(env) is None

    env["TWILIO_ACCOUNT_SID"] = "AC123"
    assert load_sms_config(env) is None

    env["TWILIO_AUTH_TOKEN"] = "token"
    assert load_sms_config(env) is None

    env["TWILIO_FROM_NUMBER"] = "9546211439"  # missing +
    assert load_sms_config(env) is None


def test_load_sms_config_valid() -> None:
    env = {
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }
    cfg = load_sms_config(env)
    assert cfg is not None
    assert cfg.account_sid == "AC123"
    assert cfg.from_number == "+19546211439"
    assert "CallCatcher Ops" in cfg.body
    assert "calendly" in cfg.body.lower()


def test_load_sms_config_custom_body() -> None:
    env = {
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
        "AUTO_SMS_BODY": "Custom message here",
    }
    cfg = load_sms_config(env)
    assert cfg is not None
    assert cfg.body == "Custom message here"


def test_load_sms_config_weekend_override() -> None:
    env = {
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
        "AUTO_SMS_ALLOW_WEEKENDS": "1",
    }
    cfg = load_sms_config(env)
    assert cfg is not None
    assert cfg.allow_weekends is True


def test_load_sms_config_second_nudge_override() -> None:
    env = {
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
        "AUTO_SMS_SECOND_NUDGE_ENABLED": "1",
        "AUTO_SMS_SECOND_NUDGE_MIN_HOURS": "8",
        "AUTO_SMS_SECOND_NUDGE_MAX_PER_RUN": "2",
    }
    cfg = load_sms_config(env)
    assert cfg is not None
    assert cfg.second_nudge_enabled is True
    assert cfg.second_nudge_min_hours == 8
    assert cfg.second_nudge_max_per_run == 2
    assert "Quick follow-up from CallCatcher Ops" in cfg.second_nudge_body


# --- _is_business_hours ---


def test_is_business_hours_weekday(monkeypatch) -> None:
    class FixedWeekday:
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 2, 16, 10, 0, 0, tzinfo=tz)  # Monday

    monkeypatch.setattr("autonomy.utils.datetime", FixedWeekday)
    assert _is_business_hours("FL", 9, 17) is True
    assert _is_business_hours("FL", 11, 17) is False  # 10 AM < 11 start


def test_is_business_hours_weekend(monkeypatch) -> None:
    class FixedWeekend:
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 2, 14, 10, 0, 0, tzinfo=tz)  # Saturday

    monkeypatch.setattr("autonomy.utils.datetime", FixedWeekend)
    assert _is_business_hours("FL", 9, 17) is False
    assert _is_business_hours("FL", 9, 17, allow_weekends=True) is True


# --- _lead_texted_recently ---


def test_lead_texted_recently_cooldown() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_sms_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_sms_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        # No SMS logged yet
        assert _lead_texted_recently(store, lead_id="new@example.com", cooldown_days=7) is False

        # Log an SMS attempt
        store.log_action(
            agent_id="test",
            action_type="sms.attempt",
            trace_id="sms-1",
            payload={"lead_id": "texted@example.com"},
        )
        assert _lead_texted_recently(store, lead_id="texted@example.com", cooldown_days=7) is True
        assert _lead_texted_recently(store, lead_id="other@example.com", cooldown_days=7) is False
    finally:
        store.conn.close()


# --- send_sms ---


def test_send_sms_success(monkeypatch) -> None:
    cfg = load_sms_config({
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    })
    assert cfg is not None

    def fake_urlopen(req, timeout=20):
        assert req.get_method() == "POST"
        assert "Messages.json" in req.full_url
        return _FakeHTTPResponse({"sid": "SM123", "status": "queued"})

    monkeypatch.setattr("autonomy.tools.twilio_sms.urllib.request.urlopen", fake_urlopen)

    resp = send_sms(cfg, to_number="+19549736161")
    assert resp["sid"] == "SM123"
    assert resp["status"] == "queued"


def test_send_sms_http_error(monkeypatch) -> None:
    cfg = load_sms_config({
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    })
    assert cfg is not None

    def fake_urlopen(req, timeout=20):
        raise _build_http_error(
            status=400,
            payload={"code": 21610, "message": "Attempt to send to unsubscribed recipient"},
        )

    monkeypatch.setattr("autonomy.tools.twilio_sms.urllib.request.urlopen", fake_urlopen)

    try:
        send_sms(cfg, to_number="+19549736161")
        raise AssertionError("Should have raised")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400


# --- run_sms_followup (end-to-end) ---


def test_run_sms_followup_disabled() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_sms_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_sms_{run_id}.jsonl")

    result = run_sms_followup(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env={},
    )
    assert result.reason == "disabled"
    assert result.attempted == 0


def test_run_sms_followup_end_to_end(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_sms_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_sms_{run_id}.jsonl")

    # Seed store with leads and call.attempt actions
    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        spoke_email = "spoke@clinic.com"
        vm_email = "voicemail@clinic.com"
        opted_email = "opted@clinic.com"

        for email in (spoke_email, vm_email, opted_email):
            store.upsert_lead(
                Lead(
                    id=email,
                    name="Test",
                    company="Test Dental",
                    email=email,
                    phone="9546211439",
                    service="Dentist",
                    city="Margate",
                    state="FL",
                    source="test",
                    score=100,
                    status="contacted",
                    email_method="direct",
                )
            )

        # Log call attempts (spoke + voicemail + opted-out)
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="call-spoke",
            payload={
                "lead_id": spoke_email,
                "phone": "(954) 621-1439",
                "company": "Spoke Dental",
                "service": "Dentist",
                "city": "Margate",
                "state": "FL",
                "outcome": "spoke",
            },
        )
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="call-vm",
            payload={
                "lead_id": vm_email,
                "phone": "(954) 621-1439",
                "company": "VM Dental",
                "service": "Dentist",
                "city": "Margate",
                "state": "FL",
                "outcome": "voicemail",
            },
        )
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="call-opted",
            payload={
                "lead_id": opted_email,
                "phone": "(954) 621-1439",
                "company": "Opted Dental",
                "service": "Dentist",
                "city": "Margate",
                "state": "FL",
                "outcome": "spoke",
            },
        )
        store.add_opt_out(opted_email)
    finally:
        store.conn.close()

    env = {
        "AUTO_SMS_ENABLED": "1",
        "AUTO_SMS_MAX_PER_RUN": "10",
        "AUTO_SMS_COOLDOWN_DAYS": "7",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    # Mock business hours to always be True
    monkeypatch.setattr(
        "autonomy.tools.twilio_sms._is_business_hours",
        lambda state, start_hour, end_hour, allow_weekends=False: True,
    )

    sms_sent = {"n": 0}

    def fake_urlopen(req, timeout=20):
        sms_sent["n"] += 1
        return _FakeHTTPResponse({"sid": f"SM{sms_sent['n']}", "status": "queued"})

    monkeypatch.setattr("autonomy.tools.twilio_sms.urllib.request.urlopen", fake_urlopen)

    result = run_sms_followup(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
    )
    assert result.reason == "ok"
    assert result.attempted == 2  # spoke + voicemail (opted-out skipped)
    assert result.delivered == 2
    assert result.failed == 0
    assert result.skipped == 1  # opted-out lead

    # Verify sms.attempt actions logged
    store_check = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        rows = store_check.conn.execute(
            "SELECT COUNT(*) FROM actions WHERE action_type='sms.attempt'"
        ).fetchone()
        assert rows[0] == 2
    finally:
        store_check.conn.close()


def test_run_sms_followup_handles_http_error(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_sms_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_sms_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        store.upsert_lead(
            Lead(
                id="fail@clinic.com",
                name="Test",
                company="Fail Dental",
                email="fail@clinic.com",
                phone="9546211439",
                service="Dentist",
                city="Margate",
                state="FL",
                source="test",
                score=100,
                status="contacted",
                email_method="direct",
            )
        )
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="call-fail",
            payload={
                "lead_id": "fail@clinic.com",
                "phone": "(954) 621-1439",
                "company": "Fail Dental",
                "service": "Dentist",
                "city": "Margate",
                "state": "FL",
                "outcome": "spoke",
            },
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    monkeypatch.setattr(
        "autonomy.tools.twilio_sms._is_business_hours",
        lambda state, start_hour, end_hour, allow_weekends=False: True,
    )

    def fake_urlopen(req, timeout=20):
        raise _build_http_error(
            status=400,
            payload={"code": 21610, "message": "Unsubscribed recipient"},
        )

    monkeypatch.setattr("autonomy.tools.twilio_sms.urllib.request.urlopen", fake_urlopen)

    result = run_sms_followup(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
    )
    assert result.attempted == 1
    assert result.failed == 1
    assert result.delivered == 0

    # Verify error details captured in DB
    store_check = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        row = store_check.conn.execute(
            """
            SELECT
              json_extract(payload_json, '$.outcome') AS outcome,
              json_extract(payload_json, '$.twilio.error_code') AS error_code,
              json_extract(payload_json, '$.twilio.http_status') AS http_status
            FROM actions
            WHERE action_type='sms.attempt'
            ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        assert row is not None
        assert row["outcome"] == "failed"
        assert int(row["error_code"] or 0) == 21610
        assert int(row["http_status"] or 0) == 400
    finally:
        store_check.conn.close()


def test_run_sms_followup_respects_cooldown(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_sms_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_sms_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        store.upsert_lead(
            Lead(
                id="cooldown@clinic.com",
                name="Test",
                company="CD Dental",
                email="cooldown@clinic.com",
                phone="9546211439",
                service="Dentist",
                city="Margate",
                state="FL",
                source="test",
                score=100,
                status="contacted",
                email_method="direct",
            )
        )
        # Log a call attempt
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="call-cd",
            payload={
                "lead_id": "cooldown@clinic.com",
                "phone": "(954) 621-1439",
                "company": "CD Dental",
                "service": "Dentist",
                "city": "Margate",
                "state": "FL",
                "outcome": "spoke",
            },
        )
        # Log a previous SMS attempt (should trigger cooldown)
        store.log_action(
            agent_id="test",
            action_type="sms.attempt",
            trace_id="sms-cd",
            payload={"lead_id": "cooldown@clinic.com"},
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_SMS_ENABLED": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    monkeypatch.setattr(
        "autonomy.tools.twilio_sms._is_business_hours",
        lambda state, start_hour, end_hour, allow_weekends=False: True,
    )

    result = run_sms_followup(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
    )
    assert result.attempted == 0
    assert result.skipped == 1  # cooldown triggered


def test_run_sms_followup_sends_second_nudge(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_sms_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_sms_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        lead_id = "nudge@clinic.com"
        store.upsert_lead(
            Lead(
                id=lead_id,
                name="Test",
                company="Nudge Dental",
                email=lead_id,
                phone="9546211439",
                service="Dentist",
                city="Margate",
                state="FL",
                source="test",
                score=100,
                status="contacted",
                email_method="direct",
            )
        )
        store.log_action(
            agent_id="agent.sms.twilio.v1",
            action_type="sms.attempt",
            trace_id="sms-init",
            payload={
                "lead_id": lead_id,
                "phone": "(954) 621-1439",
                "company": "Nudge Dental",
                "service": "Dentist",
                "city": "Margate",
                "state": "FL",
                "outcome": "delivered",
                "phase": "initial",
                "twilio": {"sid": "SM_INIT", "status": "delivered"},
            },
        )
        old_ts = (real_datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
        store.conn.execute("UPDATE actions SET ts=? WHERE trace_id='sms-init'", (old_ts,))
        store.conn.commit()
    finally:
        store.conn.close()

    env = {
        "AUTO_SMS_ENABLED": "1",
        "AUTO_SMS_SECOND_NUDGE_ENABLED": "1",
        "AUTO_SMS_SECOND_NUDGE_MIN_HOURS": "6",
        "AUTO_SMS_SECOND_NUDGE_MAX_PER_RUN": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    monkeypatch.setattr(
        "autonomy.tools.twilio_sms._is_business_hours",
        lambda state, start_hour, end_hour, allow_weekends=False: True,
    )
    monkeypatch.setattr(
        "autonomy.tools.twilio_sms.urllib.request.urlopen",
        lambda req, timeout=20: _FakeHTTPResponse({"sid": "SM_NUDGE", "status": "queued"}),
    )

    result = run_sms_followup(sqlite_path=sqlite_path, audit_log=audit_log, env=env)
    assert result.reason == "ok"
    assert result.attempted == 1
    assert result.delivered == 1

    store_check = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        row = store_check.conn.execute(
            """
            SELECT json_extract(payload_json, '$.phase') AS phase
            FROM actions
            WHERE action_type='sms.attempt'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        assert row is not None
        assert str(row["phase"] or "") == "second_nudge"
    finally:
        store_check.conn.close()
