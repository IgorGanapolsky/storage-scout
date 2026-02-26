from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from uuid import uuid4

import pytest

from autonomy.tools.agent_commerce import request_json
from autonomy.tools.twilio_sms import load_sms_config, send_sms


class _FakeHTTPResponse:
    def __init__(self, payload: dict, *, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = int(status)

    def read(self, n: int | None = None) -> bytes:
        if n is None or n < 0:
            return self._body
        return self._body[:n]

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_request_json_writes_meter_file(tmp_path: Path) -> None:
    meter_path = Path(f"autonomy/state/test_agent_meter_{uuid4().hex}.jsonl")
    captured = {"seen": False}

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        captured["seen"] = True
        return _FakeHTTPResponse({"ok": True})

    out = request_json(
        method="GET",
        url="https://api.example.com/v1/ping",
        headers={"Authorization": "Bearer test"},
        payload=None,
        timeout_secs=20,
        agent_id="agent.test.v1",
        env={"AGENT_API_METER_FILE": str(meter_path), "AGENT_COMMERCE_METERING_ENABLED": "1"},
        urlopen_func=fake_urlopen,
    )
    assert captured["seen"] is True
    assert out["ok"] is True
    assert meter_path.exists() is True
    row = json.loads(meter_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["ok"] is True
    assert int(row["status_code"]) == 200
    assert row["agent_id"] == "agent.test.v1"


def test_request_json_writes_failure_meter_on_http_error(tmp_path: Path) -> None:
    meter_path = Path(f"autonomy/state/test_agent_meter_{uuid4().hex}.jsonl")

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        raise urllib.error.HTTPError(
            url=req.full_url,
            code=429,
            msg="rate limited",
            hdrs=None,
            fp=io.BytesIO(b'{"code":429}'),
        )

    with pytest.raises(urllib.error.HTTPError):
        request_json(
            method="POST",
            url="https://api.example.com/v1/pay",
            headers={"Authorization": "Bearer test"},
            payload=b"a=1",
            timeout_secs=20,
            agent_id="agent.test.v1",
            env={"AGENT_API_METER_FILE": str(meter_path), "AGENT_COMMERCE_METERING_ENABLED": "1"},
            urlopen_func=fake_urlopen,
        )

    row = json.loads(meter_path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["ok"] is False
    assert int(row["status_code"]) == 429
    assert row["error_type"] == "HTTPError"


def test_send_sms_includes_agent_headers_and_signature(monkeypatch) -> None:
    cfg = load_sms_config(
        {
            "AUTO_SMS_ENABLED": "1",
            "TWILIO_ACCOUNT_SID": "AC123",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_FROM_NUMBER": "+19546211439",
        }
    )
    assert cfg is not None
    captured: dict[str, str] = {}

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        hdrs = {str(k).lower(): str(v) for k, v in req.header_items()}
        captured["agent_id"] = str(hdrs.get("x-agent-id") or "")
        captured["protocol"] = str(hdrs.get("x-agent-protocol") or "")
        captured["signature"] = str(hdrs.get("x-agent-signature") or "")
        captured["request_id"] = str(hdrs.get("x-agent-request-id") or "")
        return _FakeHTTPResponse({"sid": "SM123", "status": "queued"})

    monkeypatch.setattr("autonomy.tools.twilio_sms.urllib.request.urlopen", fake_urlopen)
    resp = send_sms(
        cfg,
        to_number="+19549736161",
        env={"AGENT_COMMERCE_SIGNING_KEY": "test-signing-key", "AGENT_COMMERCE_AGENT_ID": "agent.sms.twilio.v1"},
    )
    assert resp["sid"] == "SM123"
    assert captured["agent_id"] == "agent.sms.twilio.v1"
    assert captured["protocol"] == "acp-lite/2026-02"
    assert len(captured["request_id"]) >= 8
    assert len(captured["signature"]) == 64
