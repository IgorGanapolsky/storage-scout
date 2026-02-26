from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from autonomy.utils import UTC
from autonomy.tools.twilio_tollfree_watchdog import _resolve_path, run_twilio_tollfree_watchdog


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


def test_watchdog_returns_missing_env_when_twilio_not_configured() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_tf_watchdog_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_tf_watchdog_{run_id}.jsonl")
    state_path = Path(f"autonomy/state/test_tf_watchdog_state_{run_id}.json")
    result = run_twilio_tollfree_watchdog(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env={},
        company_name="CallCatcher Ops",
        state_path=state_path,
    )
    assert result.reason == "missing_twilio_env"
    assert result.should_alert is True
    assert result.alert_reason == "missing_twilio_env"


def test_watchdog_auto_fixes_30485_and_moves_to_review(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_tf_watchdog_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_tf_watchdog_{run_id}.jsonl")
    state_path = Path(f"autonomy/state/test_tf_watchdog_state_{run_id}.json")
    posted: list[dict[str, str]] = []
    fresh_review_ts = (datetime.now(UTC) - timedelta(hours=1)).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        url = req.full_url
        method = req.get_method()
        if method == "GET" and "IncomingPhoneNumbers.json" in url:
            return _FakeHTTPResponse(
                {
                    "incoming_phone_numbers": [
                        {"sid": "PN123", "phone_number": "+18446480144"},
                    ]
                }
            )
        if method == "GET" and "messaging.twilio.com/v1/Tollfree/Verifications" in url:
            return _FakeHTTPResponse(
                {
                    "verifications": [
                        {
                            "sid": "HH123",
                            "status": "TWILIO_REJECTED",
                            "error_code": 30485,
                            "rejection_reason": "Entity Misclassification",
                            "business_name": "CallCatcher Ops",
                            "doing_business_as": "",
                            "business_type": "SOLE_PROPRIETOR",
                            "edit_allowed": True,
                            "date_updated": "2026-02-24T06:37:26Z",
                            "url": "https://messaging.twilio.com/v1/Tollfree/Verifications/HH123",
                        }
                    ]
                }
            )
        if method == "POST" and "messaging.twilio.com/v1/Tollfree/Verifications/HH123" in url:
            raw = (req.data or b"").decode("utf-8")
            parsed = urllib.parse.parse_qs(raw)
            posted.append({k: (v[0] if v else "") for k, v in parsed.items()})
            return _FakeHTTPResponse(
                {
                    "sid": "HH123",
                    "status": "IN_REVIEW",
                    "error_code": None,
                    "rejection_reason": None,
                    "business_name": "Igor Ganapolsky",
                    "doing_business_as": "CallCatcher Ops",
                    "business_type": "SOLE_PROPRIETOR",
                    "edit_allowed": None,
                    "date_updated": fresh_review_ts,
                    "url": "https://messaging.twilio.com/v1/Tollfree/Verifications/HH123",
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("autonomy.tools.twilio_tollfree_watchdog.urllib.request.urlopen", fake_urlopen)

    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_SMS_FROM_NUMBER": "+18446480144",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "1",
        "TWILIO_TOLLFREE_AUTOFIX_ENABLED": "1",
        "TWILIO_BUSINESS_LEGAL_NAME": "Igor Ganapolsky",
        "TWILIO_BUSINESS_DBA_NAME": "CallCatcher Ops",
    }
    result = run_twilio_tollfree_watchdog(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        company_name="CallCatcher Ops",
        state_path=state_path,
    )
    assert result.reason == "auto_fix_applied"
    assert result.status == "IN_REVIEW"
    assert result.error_code is None
    assert result.auto_fix_attempted is True
    assert result.auto_fix_applied is True
    assert result.should_alert is False
    assert posted, "Expected remediation POST call"
    assert posted[0]["BusinessName"] == "Igor Ganapolsky"
    assert posted[0]["DoingBusinessAs"] == "CallCatcher Ops"


def test_watchdog_alerts_when_in_review_is_stale(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_tf_watchdog_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_tf_watchdog_{run_id}.jsonl")
    state_path = Path(f"autonomy/state/test_tf_watchdog_state_{run_id}.json")

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        url = req.full_url
        method = req.get_method()
        if method == "GET" and "IncomingPhoneNumbers.json" in url:
            return _FakeHTTPResponse(
                {
                    "incoming_phone_numbers": [
                        {"sid": "PN123", "phone_number": "+18446480144"},
                    ]
                }
            )
        if method == "GET" and "messaging.twilio.com/v1/Tollfree/Verifications" in url:
            return _FakeHTTPResponse(
                {
                    "verifications": [
                        {
                            "sid": "HH123",
                            "status": "IN_REVIEW",
                            "business_name": "Igor Ganapolsky",
                            "doing_business_as": "CallCatcher Ops",
                            "business_type": "SOLE_PROPRIETOR",
                            "date_updated": "2026-02-20T00:00:00Z",
                            "url": "https://messaging.twilio.com/v1/Tollfree/Verifications/HH123",
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("autonomy.tools.twilio_tollfree_watchdog.urllib.request.urlopen", fake_urlopen)
    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_SMS_FROM_NUMBER": "+18446480144",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "1",
        "TWILIO_TOLLFREE_STALE_REVIEW_HOURS": "24",
    }
    result = run_twilio_tollfree_watchdog(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        company_name="CallCatcher Ops",
        state_path=state_path,
    )
    assert result.status == "IN_REVIEW"
    assert result.should_alert is True
    assert result.alert_reason == "stale_in_review"


def test_watchdog_alerts_on_transition_to_approved(monkeypatch, tmp_path: Path) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_tf_watchdog_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_tf_watchdog_{run_id}.jsonl")
    state_path = tmp_path / "watchdog_state.json"
    state_path.write_text(
        json.dumps(
            {
                "last_status": "IN_REVIEW",
                "last_alert_reason": "",
                "last_alert_utc": "",
            }
        ),
        encoding="utf-8",
    )

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        url = req.full_url
        method = req.get_method()
        if method == "GET" and "IncomingPhoneNumbers.json" in url:
            return _FakeHTTPResponse({"incoming_phone_numbers": [{"sid": "PN123", "phone_number": "+18446480144"}]})
        if method == "GET" and "messaging.twilio.com/v1/Tollfree/Verifications" in url:
            return _FakeHTTPResponse(
                {
                    "verifications": [
                        {
                            "sid": "HH123",
                            "status": "TWILIO_APPROVED",
                            "error_code": None,
                            "rejection_reason": None,
                            "business_name": "Igor Ganapolsky",
                            "doing_business_as": "CallCatcher Ops",
                            "business_type": "SOLE_PROPRIETOR",
                            "edit_allowed": None,
                            "date_updated": "2026-02-24T20:15:32Z",
                            "url": "https://messaging.twilio.com/v1/Tollfree/Verifications/HH123",
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("autonomy.tools.twilio_tollfree_watchdog.urllib.request.urlopen", fake_urlopen)
    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_SMS_FROM_NUMBER": "+18446480144",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "1",
        "TWILIO_TOLLFREE_NOTIFY_ON_STATUS_CHANGE": "1",
        "TWILIO_TOLLFREE_NOTIFY_ON_APPROVED": "1",
    }
    result = run_twilio_tollfree_watchdog(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        company_name="CallCatcher Ops",
        state_path=state_path,
    )
    assert result.status == "TWILIO_APPROVED"
    assert result.status_changed is True
    assert result.previous_status == "IN_REVIEW"
    assert result.should_alert is True
    assert result.alert_reason == "status_changed_approved"


def test_watchdog_suppresses_duplicate_stale_alert_within_cooldown(monkeypatch, tmp_path: Path) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_tf_watchdog_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_tf_watchdog_{run_id}.jsonl")
    state_path = tmp_path / "watchdog_state.json"
    last_alert = datetime.now(UTC).replace(microsecond=0).isoformat()
    state_path.write_text(
        json.dumps(
            {
                "last_status": "IN_REVIEW",
                "last_alert_reason": "stale_in_review",
                "last_alert_utc": last_alert,
            }
        ),
        encoding="utf-8",
    )

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        url = req.full_url
        method = req.get_method()
        if method == "GET" and "IncomingPhoneNumbers.json" in url:
            return _FakeHTTPResponse({"incoming_phone_numbers": [{"sid": "PN123", "phone_number": "+18446480144"}]})
        if method == "GET" and "messaging.twilio.com/v1/Tollfree/Verifications" in url:
            stale_dt = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0).isoformat()
            return _FakeHTTPResponse(
                {
                    "verifications": [
                        {
                            "sid": "HH123",
                            "status": "IN_REVIEW",
                            "business_name": "Igor Ganapolsky",
                            "doing_business_as": "CallCatcher Ops",
                            "business_type": "SOLE_PROPRIETOR",
                            "date_updated": stale_dt,
                            "url": "https://messaging.twilio.com/v1/Tollfree/Verifications/HH123",
                        }
                    ]
                }
            )
        raise AssertionError(f"Unexpected request: {method} {url}")

    monkeypatch.setattr("autonomy.tools.twilio_tollfree_watchdog.urllib.request.urlopen", fake_urlopen)
    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_SMS_FROM_NUMBER": "+18446480144",
        "TWILIO_TOLLFREE_WATCHDOG_ENABLED": "1",
        "TWILIO_TOLLFREE_STALE_REVIEW_HOURS": "24",
        "TWILIO_TOLLFREE_ALERT_COOLDOWN_HOURS": "99999",
    }
    result = run_twilio_tollfree_watchdog(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        company_name="CallCatcher Ops",
        state_path=state_path,
    )
    assert result.status == "IN_REVIEW"
    assert result.alert_reason == "stale_in_review"
    assert result.should_alert is False
    assert result.alert_suppressed is True


def test_resolve_path_keeps_paths_inside_repo(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    resolved = _resolve_path(repo_root, "autonomy/state/watchdog.json")
    assert resolved == (repo_root / "autonomy/state/watchdog.json").resolve()

    with pytest.raises(ValueError, match="path must stay inside repo root"):
        _resolve_path(repo_root, "../outside.json")

    outside = tmp_path / "outside.json"
    with pytest.raises(ValueError, match="path must stay inside repo root"):
        _resolve_path(repo_root, str(outside))
