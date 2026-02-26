from __future__ import annotations

import json
import urllib.parse
import re
from pathlib import Path
from uuid import uuid4

from autonomy.context_store import ContextStore, Lead
from autonomy.tools.twilio_inbox_sync import load_twilio_inbox_config, run_twilio_inbox_sync


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


def test_twilio_inbox_sync_classifies_and_auto_replies(monkeypatch) -> None:
    run_id = uuid4().hex
    sqlite_path = Path(f"autonomy/state/test_twilio_inbox_{run_id}.sqlite3")
    audit_log = Path(f"autonomy/state/test_twilio_inbox_{run_id}.jsonl")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        store.upsert_lead(
            Lead(
                id="interested@example.com",
                name="",
                company="Interested Dental",
                email="interested@example.com",
                phone="(954) 555-0111",
                service="Dentist",
                city="Coral Springs",
                state="FL",
                source="test",
                score=90,
                status="contacted",
                email_method="direct",
            )
        )
        store.upsert_lead(
            Lead(
                id="optout@example.com",
                name="",
                company="OptOut Dental",
                email="optout@example.com",
                phone="(954) 555-0112",
                service="Dentist",
                city="Coral Springs",
                state="FL",
                source="test",
                score=90,
                status="contacted",
                email_method="direct",
            )
        )
    finally:
        store.conn.close()

    messages_payload = {
        "messages": [
            {"sid": "MM1", "direction": "inbound", "from": "+19545550111", "body": "Yes, interested"},
            {"sid": "MM2", "direction": "inbound", "from": "+19545550112", "body": "STOP"},
            {"sid": "MM3", "direction": "outbound-api", "from": "+19545550000", "body": "ignore"},
        ]
    }
    posted: list[dict[str, str]] = []

    def fake_urlopen(req, timeout=20):  # noqa: ANN001
        if req.get_method() == "GET":
            return _FakeHTTPResponse(messages_payload)
        if req.get_method() == "POST":
            raw = (req.data or b"").decode("utf-8")
            parsed = urllib.parse.parse_qs(raw)
            posted.append({k: (v[0] if v else "") for k, v in parsed.items()})
            return _FakeHTTPResponse({"sid": f"SM{len(posted)}", "status": "queued"})
        raise AssertionError(f"Unexpected method: {req.get_method()}")

    monkeypatch.setattr("autonomy.tools.twilio_inbox_sync.urllib.request.urlopen", fake_urlopen)

    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19540000000",
        "AUTO_SMS_INBOUND_REPLY_ENABLED": "1",
    }
    first = run_twilio_inbox_sync(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
    )
    assert first.reason == "ok"
    assert first.fetched == 3
    assert first.processed == 2
    assert first.interested == 1
    assert first.opt_out == 1
    assert first.auto_replies_sent == 1
    assert len(posted) == 1
    assert posted[0]["To"] == "+19545550111"
    body = posted[0].get("Body", "")
    urls = re.findall(r"https?://[^] )>,]+", body)
    parsed = [urllib.parse.urlparse(u) for u in urls]
    assert any(p.scheme == "https" and p.netloc == "calendly.com" and p.path == "/example/audit" for p in parsed)
    assert any(p.scheme == "https" and p.netloc == "buy.stripe.com" for p in parsed)

    # Same inbound SID values should be deduped on subsequent sync runs.
    second = run_twilio_inbox_sync(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        env=env,
        booking_url="https://calendly.com/example/audit",
    )
    assert second.reason == "ok"
    assert second.processed == 0
    assert second.ignored >= 2
    assert second.auto_replies_sent == 0

    verify_store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    try:
        assert verify_store.get_lead_status("interested@example.com") == "replied"
        assert verify_store.get_lead_status("optout@example.com") == "opted_out"
        assert verify_store.is_opted_out("optout@example.com") is True
        intent_rows = verify_store.conn.execute(
            "SELECT COUNT(1) AS c FROM actions WHERE action_type='conversion.booking_intent'"
        ).fetchone()
        assert intent_rows is not None
        assert int(intent_rows["c"] or 0) == 1
    finally:
        verify_store.conn.close()


def test_load_twilio_inbox_config_kickoff_precedence() -> None:
    env = {
        "TWILIO_ACCOUNT_SID": "AC123",
        "TWILIO_AUTH_TOKEN": "token",
        "TWILIO_FROM_NUMBER": "+19540000000",
        "PRIORITY_KICKOFF_URL": "https://pay.example/env",
    }
    cfg = load_twilio_inbox_config(
        env,
        booking_url="https://calendly.com/example/audit",
        kickoff_url="https://pay.example/arg",
    )
    assert cfg is not None
    assert cfg.booking_url == "https://calendly.com/example/audit"
    assert cfg.kickoff_url == "https://pay.example/arg"
