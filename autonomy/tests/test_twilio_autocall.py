from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime as real_datetime
from pathlib import Path
from uuid import uuid4

import pytest

from autonomy.context_store import ContextStore, Lead
from autonomy.tools import live_job as live_job_mod
from autonomy.tools.call_list import CallListRow
from autonomy.tools.fastmail_inbox_sync import InboxSyncResult
from autonomy.tools.scoreboard import Scoreboard
from autonomy.tools.twilio_autocall import (
    AutoCallResult,
    _is_business_hours,
    _is_reasonable_email,
    _lead_called_recently,
    fetch_twilio_balance,
    load_twilio_config,
    map_twilio_call_to_outcome,
    normalize_us_phone_e164,
    run_auto_calls,
    wait_for_call_terminal_status,
)
from autonomy.utils import state_tz
from autonomy.tools.twilio_sms import SmsResult


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
        url="https://api.twilio.com/2010-04-01/Accounts/AC123/Calls.json",
        code=int(status),
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def test_normalize_us_phone_e164() -> None:
    assert normalize_us_phone_e164("") is None
    assert normalize_us_phone_e164("954-621-1439") == "+19546211439"
    assert normalize_us_phone_e164("(954) 621-1439") == "+19546211439"
    assert normalize_us_phone_e164("+1 (954) 621-1439") == "+19546211439"
    assert normalize_us_phone_e164("1 954 621 1439") == "+19546211439"
    assert normalize_us_phone_e164("9546211439") == "+19546211439"
    assert normalize_us_phone_e164("011 954 621 1439") is None


def test_map_twilio_call_to_outcome() -> None:
    assert map_twilio_call_to_outcome({"status": "no-answer"})[0] == "no_answer"
    assert map_twilio_call_to_outcome({"status": "busy"})[0] == "no_answer"
    assert map_twilio_call_to_outcome({"status": "failed", "error_code": 21211})[0] == "wrong_number"
    assert map_twilio_call_to_outcome({"status": "failed"})[0] == "no_answer"
    assert map_twilio_call_to_outcome({"status": "completed", "answered_by": "machine_start"})[0] == "voicemail"
    assert map_twilio_call_to_outcome({"status": "completed", "answered_by": "human"})[0] == "spoke"
    assert map_twilio_call_to_outcome({"status": "completed"})[0] == "spoke"
    assert map_twilio_call_to_outcome({"status": "something-else"})[0] == "no_answer"


def test_load_twilio_config_requires_e164_from_number() -> None:
    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "9546211439",  # invalid (missing +)
    }
    assert load_twilio_config(env) is None

    env["TWILIO_FROM_NUMBER"] = "+19546211439"
    cfg = load_twilio_config(env)
    assert cfg is not None
    assert cfg.from_number == "+19546211439"


def test_load_twilio_config_missing_env() -> None:
    assert load_twilio_config({}) is None
    assert load_twilio_config({"TWILIO_ACCOUNT_SID": "AC123"}) is None
    assert load_twilio_config({"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token"}) is None


def test_state_tz_defaults_and_known() -> None:
    assert state_tz("") == "America/New_York"
    assert state_tz("fl") == "America/New_York"
    assert state_tz("CA") == "America/Los_Angeles"


def test_is_reasonable_email_filters_scrape_artifacts() -> None:
    assert _is_reasonable_email("first.last@clinic.com") is True
    assert _is_reasonable_email("asset-1@3x.png") is False
    assert _is_reasonable_email("not-an-email") is False


def test_is_business_hours_weekday_and_weekend(monkeypatch) -> None:
    # Monday, Feb 16 2026 at 10:00 local time.
    class FixedWeekdayDateTime:
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 2, 16, 10, 0, 0, tzinfo=tz)

    monkeypatch.setattr("autonomy.utils.datetime", FixedWeekdayDateTime)
    assert _is_business_hours(state="FL", start_hour=9, end_hour=17) is True
    assert _is_business_hours(state="FL", start_hour=11, end_hour=17) is False

    # Saturday, Feb 14 2026 at 10:00 local time.
    class FixedWeekendDateTime:
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 2, 14, 10, 0, 0, tzinfo=tz)

    monkeypatch.setattr("autonomy.utils.datetime", FixedWeekendDateTime)
    assert _is_business_hours(state="FL", start_hour=9, end_hour=17) is False
    assert _is_business_hours(state="FL", start_hour=9, end_hour=17, allow_weekends=True) is True


def test_lead_called_recently_ignores_failed_attempts() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="failed-1",
            payload={"lead_id": "failed@example.com", "outcome": "failed"},
        )
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="spoke-1",
            payload={"lead_id": "spoke@example.com", "outcome": "spoke"},
        )

        assert _lead_called_recently(store, lead_id="failed@example.com", cooldown_days=7) is False
        assert _lead_called_recently(store, lead_id="spoke@example.com", cooldown_days=7) is True
    finally:
        store.conn.close()


def test_wait_for_call_terminal_status_polls(monkeypatch) -> None:
    env = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token", "TWILIO_FROM_NUMBER": "+19546211439"}
    cfg = load_twilio_config(env)
    assert cfg is not None

    get_calls = {"n": 0}

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        if req.get_method() != "GET":
            raise AssertionError("expected GET")
        get_calls["n"] += 1
        if get_calls["n"] == 1:
            return _FakeHTTPResponse({"sid": "CA1", "status": "queued"})
        return _FakeHTTPResponse({"sid": "CA1", "status": "completed", "answered_by": "human"})

    monkeypatch.setattr("autonomy.tools.twilio_autocall.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("autonomy.tools.twilio_autocall.time.sleep", lambda _s: None)

    final = wait_for_call_terminal_status(cfg, call_sid="CA1")
    assert str(final.get("status")) == "completed"
    assert get_calls["n"] >= 2


def test_run_auto_calls_end_to_end(monkeypatch) -> None:
    # Create a unique sqlite/audit file under autonomy/state (ContextStore enforces this).
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    # Seed store with leads + opt-out + a recent call for cooldown skip.
    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        opted = "opted@example.com"
        recent = "recent@example.com"
        boom = "boom@example.com"
        good = "good@example.com"

        for email in (opted, recent, boom, good):
            store.upsert_lead(
                Lead(
                    id=email,
                    name="Test",
                    company="Co",
                    email=email,
                    phone="9546211439",
                    service="Dentist",
                    city="X",
                    state="FL",
                    source="test",
                    score=100,
                    status="new",
                    email_method="direct",
                )
            )

        store.add_opt_out(opted)
        store.log_action(
            agent_id="test",
            action_type="call.attempt",
            trace_id="t1",
            payload={"lead_id": recent},
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_CALLS_ENABLED": "1",
        "AUTO_CALLS_MAX_PER_RUN": "2",
        "AUTO_CALLS_COOLDOWN_DAYS": "7",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    def fake_is_business_hours(*, state: str, start_hour: int, end_hour: int, allow_weekends: bool = False) -> bool:
        return state != "TX"

    monkeypatch.setattr("autonomy.tools.twilio_autocall._is_business_hours", fake_is_business_hours)
    monkeypatch.setattr("autonomy.tools.twilio_autocall.fetch_twilio_balance", lambda env: 100.0)

    post_calls = {"n": 0}

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        method = req.get_method()
        if method == "POST":
            post_calls["n"] += 1
            if post_calls["n"] == 1:
                raise RuntimeError("boom")
            return _FakeHTTPResponse({"sid": "CA2", "status": "queued"})
        if method == "GET":
            return _FakeHTTPResponse({"sid": "CA2", "status": "completed", "answered_by": "human"})
        raise AssertionError(f"unexpected method: {method}")

    monkeypatch.setattr("autonomy.tools.twilio_autocall.urllib.request.urlopen", fake_urlopen)

    call_rows = [
        {"email": "not-an-email", "phone": "9546211439", "state": "FL"},
        {"email": opted, "phone": "9546211439", "state": "FL"},
        {"email": recent, "phone": "9546211439", "state": "FL"},
        {"email": "hours@example.com", "phone": "9546211439", "state": "TX"},
        {"email": "badphone@example.com", "phone": "011 954 621 1439", "state": "FL"},
        {"email": boom, "phone": "9546211439", "state": "FL"},
        {"email": good, "phone": "9546211439", "state": "FL"},
    ]

    result = run_auto_calls(sqlite_path=sqlite_path, audit_log=audit_log, env=env, call_rows=call_rows)
    assert result.reason == "ok"
    assert result.attempted == 2
    assert result.spoke == 1
    assert result.failed == 1
    assert result.skipped == 5


def test_run_auto_calls_accepts_call_list_row_dataclass(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        email = "dataclass@example.com"
        store.upsert_lead(
            Lead(
                id=email,
                name="Test",
                company="Co",
                email=email,
                phone="9546211439",
                service="Dentist",
                city="X",
                state="FL",
                source="test",
                score=100,
                status="new",
                email_method="direct",
            )
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_CALLS_ENABLED": "1",
        "AUTO_CALLS_MAX_PER_RUN": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    monkeypatch.setattr(
        "autonomy.tools.twilio_autocall.urllib.request.urlopen",
        lambda req, timeout=20: _FakeHTTPResponse(
            {"sid": "CA3", "status": "completed", "answered_by": "human"}
            if req.get_method() == "GET"
            else {"sid": "CA3", "status": "queued"}
        ),
    )
    monkeypatch.setattr("autonomy.tools.twilio_autocall.time.sleep", lambda _s: None)
    monkeypatch.setattr("autonomy.tools.twilio_autocall._is_business_hours", lambda **_kwargs: True)
    monkeypatch.setattr("autonomy.tools.twilio_autocall.fetch_twilio_balance", lambda env: 100.0)

    rows = [
        CallListRow(
            company="Co",
            service="Dentist",
            city="X",
            state="FL",
            phone="9546211439",
            website="",
            contact_name="Test",
            email="dataclass@example.com",
            email_method="direct",
            lead_status="new",
            score=100,
            source="test",
            role_inbox="no",
            last_email_ts="",
            email_sent_count=0,
            opted_out="no",
        )
    ]

    result = run_auto_calls(sqlite_path=sqlite_path, audit_log=audit_log, env=env, call_rows=rows)
    assert result.reason == "ok"
    assert result.attempted == 1
    assert result.spoke == 1


def test_run_auto_calls_records_twilio_http_error_details(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        email = "trial@example.com"
        store.upsert_lead(
            Lead(
                id=email,
                name="Trial",
                company="Co",
                email=email,
                phone="9549736161",
                service="Dentist",
                city="X",
                state="FL",
                source="test",
                score=100,
                status="new",
                email_method="direct",
            )
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_CALLS_ENABLED": "1",
        "AUTO_CALLS_MAX_PER_RUN": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        if req.get_method() == "POST":
            raise _build_http_error(
                status=400,
                payload={
                    "code": 21219,
                    "message": "The number +19549736161 is unverified. Trial accounts may only make calls to verified numbers.",
                    "more_info": "https://www.twilio.com/docs/errors/21219",
                },
            )
        raise AssertionError("GET should not be called when POST fails")

    monkeypatch.setattr("autonomy.tools.twilio_autocall.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("autonomy.tools.twilio_autocall._is_business_hours", lambda **_kwargs: True)
    monkeypatch.setattr("autonomy.tools.twilio_autocall.fetch_twilio_balance", lambda env: 100.0)

    result = run_auto_calls(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        call_rows=[{"email": "trial@example.com", "phone": "9549736161", "state": "FL"}],
    )
    assert result.reason == "ok"
    assert result.attempted == 1
    assert result.failed == 1

    store_check = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        row = store_check.conn.execute(
            """
            SELECT
              json_extract(payload_json, '$.notes') AS notes,
              json_extract(payload_json, '$.twilio.error_code') AS error_code,
              json_extract(payload_json, '$.twilio.http_status') AS http_status,
              json_extract(payload_json, '$.twilio.error_type') AS error_type
            FROM actions
            WHERE action_type='call.attempt'
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        assert row is not None
        assert "code=21219" in str(row["notes"] or "")
        assert int(row["error_code"] or 0) == 21219
        assert int(row["http_status"] or 0) == 400
        assert str(row["error_type"] or "") == "HTTPError"
    finally:
        store_check.conn.close()


def test_live_job_report_includes_auto_calls_section() -> None:
    report = live_job_mod._format_report(
        leadgen_new=0,
        call_list=None,
        auto_calls=AutoCallResult(
            attempted=1,
            completed=1,
            spoke=1,
            voicemail=0,
            no_answer=0,
            wrong_number=0,
            failed=0,
            skipped=0,
            reason="ok",
        ),
        sms_followup=SmsResult(
            attempted=1,
            delivered=1,
            failed=0,
            skipped=0,
            reason="ok",
        ),
        engine_result={"sent_initial": 0, "sent_followup": 0},
        inbox_result=InboxSyncResult(
            processed_messages=0,
            new_bounces=0,
            new_replies=0,
            new_opt_outs=0,
            intake_submissions=0,
            calendly_bookings=0,
            stripe_payments=0,
            last_uid=0,
        ),
        scoreboard=Scoreboard(
            leads_total=0,
            leads_new=0,
            leads_contacted=0,
            leads_replied=0,
            leads_bounced=0,
            leads_other=0,
            email_sent_total=0,
            email_sent_recent=0,
            emailed_leads_recent=0,
            bounced_leads_recent=0,
            bounce_rate_recent=0.0,
            opt_out_total=0,
            last_email_ts="",
            call_attempts_total=0,
            call_attempts_recent=0,
            call_booked_total=0,
            call_booked_recent=0,
            calendly_bookings_total=0,
            calendly_bookings_recent=0,
            stripe_payments_total=0,
            stripe_payments_recent=0,
            bookings_total=0,
            bookings_recent=0,
            last_call_ts="",
        ),
        scoreboard_days=30,
        funnel_result=None,
        goal_tasks=None,
    )
    assert "Auto calls (Twilio)" in report
    assert "- status: ok" in report
    assert "SMS follow-up (Twilio)" in report
    assert "- delivered: 1" in report


# ---------------------------------------------------------------------------
# Balance guard
# ---------------------------------------------------------------------------


def test_fetch_twilio_balance_success(monkeypatch) -> None:
    def fake_urlopen(req, timeout=10):  # noqa: ANN001
        return _FakeHTTPResponse({"balance": "4.97", "currency": "USD"})

    monkeypatch.setattr("autonomy.tools.twilio_autocall.urllib.request.urlopen", fake_urlopen)
    env = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token"}
    assert fetch_twilio_balance(env) == pytest.approx(4.97)


def test_fetch_twilio_balance_missing_creds() -> None:
    assert fetch_twilio_balance({}) is None
    assert fetch_twilio_balance({"TWILIO_ACCOUNT_SID": "AC123"}) is None


def test_fetch_twilio_balance_api_error(monkeypatch) -> None:
    def fake_urlopen(req, timeout=10):  # noqa: ANN001
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("autonomy.tools.twilio_autocall.urllib.request.urlopen", fake_urlopen)
    env = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "token"}
    assert fetch_twilio_balance(env) is None


def test_run_auto_calls_low_balance_blocks(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    env = {
        "AUTO_CALLS_ENABLED": "1",
        "AUTO_CALLS_MAX_PER_RUN": "5",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
        "TWILIO_MIN_BALANCE": "5.00",
    }

    # Balance is $1.45 — below $5.00 threshold
    monkeypatch.setattr(
        "autonomy.tools.twilio_autocall.fetch_twilio_balance",
        lambda env: 1.45,
    )

    call_rows = [{"email": "test@example.com", "phone": "9546211439", "state": "FL"}]
    result = run_auto_calls(sqlite_path=sqlite_path, audit_log=audit_log, env=env, call_rows=call_rows)
    assert result.attempted == 0
    assert result.skipped == 1
    assert "low_balance" in result.reason
    assert "$1.45" in result.reason


def test_run_auto_calls_balance_ok_proceeds(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        email = "balok@example.com"
        store.upsert_lead(
            Lead(
                id=email, name="Test", company="Co", email=email,
                phone="9546211439", service="Dentist", city="X", state="FL",
                source="test", score=100, status="new", email_method="direct",
            )
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_CALLS_ENABLED": "1",
        "AUTO_CALLS_MAX_PER_RUN": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
        "TWILIO_MIN_BALANCE": "5.00",
    }

    # Balance is $20.00 — above threshold, should proceed
    monkeypatch.setattr(
        "autonomy.tools.twilio_autocall.fetch_twilio_balance",
        lambda env: 20.00,
    )
    monkeypatch.setattr("autonomy.tools.twilio_autocall._is_business_hours", lambda **_kwargs: True)
    monkeypatch.setattr(
        "autonomy.tools.twilio_autocall.urllib.request.urlopen",
        lambda req, timeout=20: _FakeHTTPResponse(
            {"sid": "CA5", "status": "completed", "answered_by": "human"}
            if req.get_method() == "GET"
            else {"sid": "CA5", "status": "queued"}
        ),
    )
    monkeypatch.setattr("autonomy.tools.twilio_autocall.time.sleep", lambda _s: None)

    call_rows = [{"email": "balok@example.com", "phone": "9546211439", "state": "FL"}]
    result = run_auto_calls(sqlite_path=sqlite_path, audit_log=audit_log, env=env, call_rows=call_rows)
    assert result.reason == "ok"
    assert result.attempted == 1


def test_run_auto_calls_balance_check_failure_allows_calls(monkeypatch) -> None:
    """If the balance API fails, we should still allow calls (fail-open)."""
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_autocall_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_autocall_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        email = "failopen@example.com"
        store.upsert_lead(
            Lead(
                id=email, name="Test", company="Co", email=email,
                phone="9546211439", service="Dentist", city="X", state="FL",
                source="test", score=100, status="new", email_method="direct",
            )
        )
    finally:
        store.conn.close()

    env = {
        "AUTO_CALLS_ENABLED": "1",
        "AUTO_CALLS_MAX_PER_RUN": "1",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19546211439",
    }

    # Balance API returns None (failure) — should proceed
    monkeypatch.setattr(
        "autonomy.tools.twilio_autocall.fetch_twilio_balance",
        lambda env: None,
    )
    monkeypatch.setattr("autonomy.tools.twilio_autocall._is_business_hours", lambda **_kwargs: True)
    monkeypatch.setattr(
        "autonomy.tools.twilio_autocall.urllib.request.urlopen",
        lambda req, timeout=20: _FakeHTTPResponse(
            {"sid": "CA6", "status": "completed", "answered_by": "human"}
            if req.get_method() == "GET"
            else {"sid": "CA6", "status": "queued"}
        ),
    )
    monkeypatch.setattr("autonomy.tools.twilio_autocall.time.sleep", lambda _s: None)

    call_rows = [{"email": "failopen@example.com", "phone": "9546211439", "state": "FL"}]
    result = run_auto_calls(sqlite_path=sqlite_path, audit_log=audit_log, env=env, call_rows=call_rows)
    assert result.reason == "ok"
    assert result.attempted == 1
