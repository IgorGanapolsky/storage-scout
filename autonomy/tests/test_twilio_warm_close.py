from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.twilio_warm_close import run_warm_close_loop
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


def _seed_warm_lead(*, sqlite_path: Path, audit_log: Path, lead_id: str, phone: str, status: str) -> None:
    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        store.upsert_lead(
            Lead(
                id=lead_id,
                name="",
                company="Warm Co",
                email=lead_id,
                phone=phone,
                service="Dentist",
                city="Coral Springs",
                state="FL",
                source="test",
                score=90,
                status=status,
                email_method="direct",
            )
        )
    finally:
        store.close()


def test_warm_close_sends_and_respects_cooldown(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_warm_close_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_warm_close_{run_id}.jsonl")
    _seed_warm_lead(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        lead_id="warm@example.com",
        phone="(954) 555-0111",
        status="replied",
    )

    posted: list[dict[str, str]] = []

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        parsed = urllib.parse.parse_qs((req.data or b"").decode("utf-8"))
        posted.append({k: (v[0] if v else "") for k, v in parsed.items()})
        return _FakeHTTPResponse({"sid": f"SM{len(posted)}", "status": "queued"})

    monkeypatch.setattr("autonomy.tools.twilio_warm_close.urllib.request.urlopen", fake_urlopen)

    env = {
        "AUTO_WARM_CLOSE_ENABLED": "1",
        "AUTO_WARM_CLOSE_MAX_PER_RUN": "2",
        "AUTO_WARM_CLOSE_COOLDOWN_HOURS": "24",
        "AUTO_WARM_CLOSE_MIN_SCORE": "70",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19540000000",
    }

    first = run_warm_close_loop(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
        kickoff_url="https://pay.example/kickoff",
    )
    assert first.reason == "ok"
    assert first.candidates == 1
    assert first.attempted == 1
    assert first.sent == 1
    assert first.failed == 0
    assert first.converted_skipped == 0
    assert len(posted) == 1
    assert posted[0]["To"] == "+19545550111"
    assert "calendly.com/example/audit" in posted[0]["Body"]
    assert "pay.example/kickoff" in posted[0]["Body"]

    second = run_warm_close_loop(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
        kickoff_url="https://pay.example/kickoff",
    )
    assert second.reason == "ok"
    assert second.sent == 0
    assert second.skipped >= 1
    assert len(posted) == 1


def test_warm_close_skips_leads_with_recent_conversion() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_warm_close_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_warm_close_{run_id}.jsonl")
    _seed_warm_lead(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        lead_id="converted@example.com",
        phone="(954) 555-0222",
        status="interested",
    )

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        ts = (datetime.now(UTC) + timedelta(seconds=1)).isoformat()
        store.conn.execute(
            "INSERT INTO actions (ts, agent_id, action_type, trace_id, payload_json) VALUES (?, ?, ?, ?, ?)",
            (
                ts,
                "agent.autocall.twilio.v1",
                "call.attempt",
                "twilio:CA_booked_1",
                json.dumps({"lead_id": "converted@example.com", "outcome": "booked"}),
            ),
        )
        store.conn.commit()
    finally:
        store.close()

    env = {
        "AUTO_WARM_CLOSE_ENABLED": "1",
        "AUTO_WARM_CLOSE_MAX_PER_RUN": "2",
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19540000000",
    }
    result = run_warm_close_loop(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
        kickoff_url="https://pay.example/kickoff",
    )
    assert result.reason == "ok"
    assert result.sent == 0
    assert result.converted_skipped == 1
    assert result.skipped >= 1


def test_warm_close_disabled_and_missing_env() -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_warm_close_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_warm_close_{run_id}.jsonl")

    disabled = run_warm_close_loop(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env={"AUTO_WARM_CLOSE_ENABLED": "0"},
    )
    assert disabled.reason == "disabled"

    missing = run_warm_close_loop(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env={"AUTO_WARM_CLOSE_ENABLED": "1"},
    )
    assert missing.reason == "missing_twilio_env"

