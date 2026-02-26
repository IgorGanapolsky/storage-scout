"""Tests for Retell AI caller module.

Tests config loading, outcome mapping, and HTTP call mocking.
No real API calls are made.
"""

from __future__ import annotations

import json
from typing import Any

from autonomy.tools.retell_caller import (
    RetellCallerConfig,
    get_retell_call,
    load_retell_config,
    map_retell_to_outcome,
    place_retell_call,
)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def test_load_retell_config_all_vars() -> None:
    env = {
        "RETELL_API_KEY": "key_abc123",
        "RETELL_OUTBOUND_AGENT_ID": "agent_f07d03d4a2a96937445d1688cc",
        "TWILIO_FROM_NUMBER": "+19547375197",
    }
    cfg = load_retell_config(env)
    assert cfg is not None
    assert cfg.api_key == "key_abc123"
    assert cfg.outbound_agent_id == "agent_f07d03d4a2a96937445d1688cc"
    assert cfg.from_number == "+19547375197"
    assert cfg.poll_interval_secs == 3.0
    assert cfg.poll_timeout_secs == 300


def test_load_retell_config_missing_api_key() -> None:
    env = {
        "RETELL_OUTBOUND_AGENT_ID": "agent_123",
        "TWILIO_FROM_NUMBER": "+19547375197",
    }
    assert load_retell_config(env) is None


def test_load_retell_config_missing_agent_id() -> None:
    env = {
        "RETELL_API_KEY": "key_abc",
        "TWILIO_FROM_NUMBER": "+19547375197",
    }
    assert load_retell_config(env) is None


def test_load_retell_config_missing_from_number() -> None:
    env = {
        "RETELL_API_KEY": "key_abc",
        "RETELL_OUTBOUND_AGENT_ID": "agent_123",
    }
    assert load_retell_config(env) is None


def test_load_retell_config_non_e164_from_number() -> None:
    env = {
        "RETELL_API_KEY": "key_abc",
        "RETELL_OUTBOUND_AGENT_ID": "agent_123",
        "TWILIO_FROM_NUMBER": "9547375197",
    }
    assert load_retell_config(env) is None


def test_load_retell_config_empty_strings() -> None:
    env = {
        "RETELL_API_KEY": "",
        "RETELL_OUTBOUND_AGENT_ID": "",
        "TWILIO_FROM_NUMBER": "",
    }
    assert load_retell_config(env) is None


def test_load_retell_config_whitespace_trimmed() -> None:
    env = {
        "RETELL_API_KEY": "  key_abc  ",
        "RETELL_OUTBOUND_AGENT_ID": "  agent_123  ",
        "TWILIO_FROM_NUMBER": "  +19547375197  ",
    }
    cfg = load_retell_config(env)
    assert cfg is not None
    assert cfg.api_key == "key_abc"
    assert cfg.outbound_agent_id == "agent_123"
    assert cfg.from_number == "+19547375197"


# ---------------------------------------------------------------------------
# Outcome mapping
# ---------------------------------------------------------------------------


def test_map_retell_ended_spoke() -> None:
    data = {
        "call_status": "ended",
        "disconnection_reason": "agent_hangup",
        "call_analysis": {"in_voicemail": False, "call_successful": True},
    }
    outcome, notes = map_retell_to_outcome(data)
    assert outcome == "spoke"
    assert "ended" in notes


def test_map_retell_ended_voicemail() -> None:
    data = {
        "call_status": "ended",
        "disconnection_reason": "voicemail_reached",
        "call_analysis": {"in_voicemail": True, "call_successful": False},
    }
    outcome, notes = map_retell_to_outcome(data)
    assert outcome == "voicemail"
    assert "in_voicemail=true" in notes


def test_map_retell_not_connected() -> None:
    data = {
        "call_status": "not_connected",
        "disconnection_reason": "no_answer",
    }
    outcome, notes = map_retell_to_outcome(data)
    assert outcome == "no_answer"
    assert "not_connected" in notes


def test_map_retell_error() -> None:
    data = {
        "call_status": "error",
        "disconnection_reason": "dial_failed",
    }
    outcome, notes = map_retell_to_outcome(data)
    assert outcome == "failed"
    assert "error" in notes


def test_map_retell_unknown_status() -> None:
    data = {"call_status": "in_progress"}
    outcome, notes = map_retell_to_outcome(data)
    assert outcome == "no_answer"
    assert "in_progress" in notes


def test_map_retell_empty_data() -> None:
    outcome, notes = map_retell_to_outcome({})
    assert outcome == "no_answer"


def test_map_retell_no_analysis() -> None:
    data = {
        "call_status": "ended",
        "disconnection_reason": "user_hangup",
    }
    outcome, notes = map_retell_to_outcome(data)
    assert outcome == "spoke"


# ---------------------------------------------------------------------------
# HTTP call mocking
# ---------------------------------------------------------------------------


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def read(self, n: int | None = None) -> bytes:
        return self._body if n is None else self._body[:n]

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def test_place_retell_call(monkeypatch) -> None:
    cfg = RetellCallerConfig(
        api_key="key_test",
        outbound_agent_id="agent_test",
        from_number="+19547375197",
    )

    captured: dict[str, Any] = {}

    def fake_urlopen(req, timeout=30):  # noqa: ANN001
        captured["method"] = req.get_method()
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8")) if req.data else None
        captured["auth"] = req.get_header("Authorization")
        return _FakeHTTPResponse({
            "call_id": "call_abc123",
            "call_status": "registered",
        })

    monkeypatch.setattr("autonomy.tools.retell_caller.urllib.request.urlopen", fake_urlopen)

    result = place_retell_call(cfg, "+15551234567", {"lead_id": "test@example.com"})

    assert result["call_id"] == "call_abc123"
    assert captured["method"] == "POST"
    assert "/v2/create-phone-call" in captured["url"]
    assert captured["data"]["from_number"] == "+19547375197"
    assert captured["data"]["to_number"] == "+15551234567"
    assert captured["data"]["override_agent_id"] == "agent_test"
    assert captured["data"]["metadata"]["lead_id"] == "test@example.com"
    assert captured["auth"] == "Bearer key_test"


def test_get_retell_call_polls_until_terminal(monkeypatch) -> None:
    cfg = RetellCallerConfig(
        api_key="key_test",
        outbound_agent_id="agent_test",
        from_number="+19547375197",
    )

    poll_count = {"n": 0}

    def fake_urlopen(req, timeout=30):  # noqa: ANN001
        poll_count["n"] += 1
        if poll_count["n"] < 3:
            return _FakeHTTPResponse({"call_id": "call_abc", "call_status": "in_progress"})
        return _FakeHTTPResponse({
            "call_id": "call_abc",
            "call_status": "ended",
            "disconnection_reason": "agent_hangup",
            "transcript": "Hello, this is a test.",
            "call_analysis": {
                "in_voicemail": False,
                "call_successful": True,
                "user_sentiment": "positive",
                "call_summary": "Discussed services",
            },
        })

    monkeypatch.setattr("autonomy.tools.retell_caller.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("autonomy.tools.retell_caller.time.sleep", lambda _s: None)

    result = get_retell_call(cfg, "call_abc")
    assert result["call_status"] == "ended"
    assert poll_count["n"] == 3
    assert result["transcript"] == "Hello, this is a test."
    assert result["call_analysis"]["call_successful"] is True


def test_get_retell_call_timeout(monkeypatch) -> None:
    cfg = RetellCallerConfig(
        api_key="key_test",
        outbound_agent_id="agent_test",
        from_number="+19547375197",
        poll_timeout_secs=0,  # Immediate timeout
    )

    def fake_urlopen(req, timeout=30):  # noqa: ANN001
        return _FakeHTTPResponse({"call_id": "call_abc", "call_status": "in_progress"})

    monkeypatch.setattr("autonomy.tools.retell_caller.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("autonomy.tools.retell_caller.time.sleep", lambda _s: None)

    result = get_retell_call(cfg, "call_abc")
    # Timeout returns last known status
    assert result.get("call_status") == "in_progress" or result == {}
