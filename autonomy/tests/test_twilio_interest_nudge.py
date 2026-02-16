from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.twilio_interest_nudge import run_interest_nudges
from autonomy.utils import UTC


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


def test_interest_nudge_sends_and_respects_cooldown(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_interest_nudge_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_interest_nudge_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        store.upsert_lead(
            Lead(
                id="interested@example.com",
                name="",
                company="Interested Co",
                email="interested@example.com",
                phone="(954) 555-0111",
                service="Dentist",
                city="Coral Springs",
                state="FL",
                source="test",
                score=90,
                status="replied",
                email_method="direct",
            )
        )
        ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        payload = {
            "lead_id": "interested@example.com",
            "from_phone_e164": "+19545550111",
            "from_phone": "+19545550111",
            "inbound_sid": "MM_IN_1",
            "classification": "interested",
            "body": "yes interested",
        }
        store.conn.execute(
            "INSERT INTO actions (ts, agent_id, action_type, trace_id, payload_json) VALUES (?, ?, ?, ?, ?)",
            (ts, "agent.sms.twilio.inbox.v1", "sms.inbound", "twilio_inbound:MM_IN_1", json.dumps(payload)),
        )
        store.conn.commit()
    finally:
        store.conn.close()

    posted: list[dict[str, str]] = []

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        raw = (req.data or b"").decode("utf-8")
        parsed = urllib.parse.parse_qs(raw)
        posted.append({k: (v[0] if v else "") for k, v in parsed.items()})
        return _FakeHTTPResponse({"sid": f"SM{len(posted)}", "status": "queued"})

    monkeypatch.setattr("autonomy.tools.twilio_interest_nudge.urllib.request.urlopen", fake_urlopen)

    env = {
        "AUTO_INTEREST_NUDGE_ENABLED": "1",
        "AUTO_INTEREST_NUDGE_MAX_PER_RUN": "3",
        "AUTO_INTEREST_NUDGE_MIN_AGE_MINUTES": "0",
        "AUTO_INTEREST_NUDGE_COOLDOWN_HOURS": "24",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19540000000",
    }

    first = run_interest_nudges(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
        kickoff_url="https://pay.example/kickoff",
    )
    assert first.reason == "ok"
    assert first.candidates == 1
    assert first.attempted == 1
    assert first.nudged == 1
    assert first.failed == 0
    assert len(posted) == 1
    assert posted[0]["To"] == "+19545550111"
    assert "calendly.com/example/audit" in posted[0]["Body"]
    assert "pay.example/kickoff" in posted[0]["Body"]

    second = run_interest_nudges(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
        kickoff_url="https://pay.example/kickoff",
    )
    assert second.reason == "ok"
    assert second.nudged == 0
    assert second.skipped >= 1
    assert len(posted) == 1


def test_interest_nudge_disabled() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_interest_nudge_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_interest_nudge_{run_id}.jsonl")

    result = run_interest_nudges(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env={"AUTO_INTEREST_NUDGE_ENABLED": "0"},
    )
    assert result.reason == "disabled"


def test_interest_nudge_missing_twilio_env_when_enabled() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_interest_nudge_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_interest_nudge_{run_id}.jsonl")

    result = run_interest_nudges(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env={"AUTO_INTEREST_NUDGE_ENABLED": "1"},
    )
    assert result.reason == "missing_twilio_env"

