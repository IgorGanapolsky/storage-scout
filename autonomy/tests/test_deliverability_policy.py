from __future__ import annotations

import contextlib
import csv
import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from autonomy.context_store import ContextStore, Lead
from autonomy.engine import Engine, EngineConfig
from autonomy.providers import LeadSourceCSV


def _tmp_state_paths(tmp_name: str) -> tuple[str, str]:
    db_path = f"autonomy/state/{tmp_name}.sqlite3"
    audit_path = f"autonomy/state/{tmp_name}.jsonl"
    return db_path, audit_path


def test_context_store_migrates_email_method_column_and_normalizes_unknown() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)

    # Seed a legacy leads table (no email_method column).
    Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
    Path(audit_log).parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
        conn.execute(
            """
            CREATE TABLE leads (
              id TEXT PRIMARY KEY,
              name TEXT,
              company TEXT,
              email TEXT,
              phone TEXT,
              service TEXT,
              city TEXT,
              state TEXT,
              source TEXT,
              score INTEGER,
              status TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO leads (id, name, company, email, phone, service, city, state, source, score, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "a@example.com",
                "",
                "A Co",
                "a@example.com",
                "",
                "med spa",
                "Miami",
                "FL",
                "manual",
                80,
                "new",
                "2026-02-01T00:00:00+00:00",
                "2026-02-01T00:00:00+00:00",
            ),
        )
        conn.commit()

    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)
    cur = store.conn.cursor()
    cols = {row[1] for row in cur.execute("PRAGMA table_info(leads)").fetchall()}
    assert "email_method" in cols

    method = cur.execute("SELECT email_method FROM leads WHERE id=?", ("a@example.com",)).fetchone()[0]
    assert method == "unknown"
    store.close()


def test_lead_source_csv_infers_email_method(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    rows = [
        {"company": "A", "email": "info@example.com"},
        {"company": "B", "email": "jane.doe@example.com"},
        {"company": "C", "email": "owner@example.com", "email_method": "Apollo"},
        {"company": "D", "email": "x@example.com", "notes": "source=google_places; email=scrape"},
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    leads = LeadSourceCSV(path=str(csv_path), source="t").load()
    by_email = {lead.email: lead for lead in leads}
    assert by_email["info@example.com"].email_method == "unknown"
    assert by_email["jane.doe@example.com"].email_method == "direct"
    assert by_email["owner@example.com"].email_method == "apollo"
    assert by_email["x@example.com"].email_method == "scrape"


def _make_engine(*, sqlite_path: str, audit_log: str, outreach_cfg: dict) -> Engine:
    # Preflight checks require a non-empty SMTP password env var.
    os.environ.setdefault("SMTP_PASSWORD", "test-password")

    cfg = EngineConfig(
        mode="live",
        company={
            "name": "AEO Autopilot",
            "website": "https://aiseoautopilot.com",
            "intake_url": "https://aiseoautopilot.com/ai-seo/intake.html",
            "reply_to": "hello@aiseoautopilot.com",
            "mailing_address": "Test Address",
            "signature": "— AEO Autopilot",
        },
        agents={"outreach": outreach_cfg, "observer": {"observe_threshold": 999, "reflect_threshold": 999}},
        lead_sources=[],
        email={
            "provider": "smtp",
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "hello@aiseoautopilot.com",
            "smtp_password_env": "SMTP_PASSWORD",
        },
        compliance={
            "include_unsubscribe": True,
            "unsubscribe_url": "https://aiseoautopilot.com/unsubscribe.html?email={{email}}",
            "can_spam_required": True,
        },
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    engine = Engine(cfg)
    engine.sender.send = MagicMock(return_value="sent")
    return engine


def _lead(
    *,
    email: str,
    status: str,
    score: int = 90,
    email_method: str = "direct",
    name: str = "",
) -> Lead:
    return Lead(
        id=email,
        name=name or email.split("@", 1)[0],
        company=email,
        email=email,
        phone="",
        service="med spa",
        city="Miami",
        state="FL",
        source="t",
        score=score,
        status=status,
        email_method=email_method,
    )


def test_engine_blocks_fastmail_outreach_by_default(monkeypatch) -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)

    monkeypatch.setenv("SMTP_PASSWORD", "test-password")
    monkeypatch.delenv("ALLOW_FASTMAIL_OUTREACH", raising=False)

    cfg = EngineConfig(
        mode="live",
        company={
            "name": "AEO Autopilot",
            "website": "https://aiseoautopilot.com",
            "intake_url": "https://aiseoautopilot.com/ai-seo/intake.html",
            "reply_to": "hello@aiseoautopilot.com",
            "mailing_address": "Test Address",
            "signature": "— AEO Autopilot",
        },
        agents={"outreach": {"agent_id": "agent.outreach.v1", "daily_send_limit": 10, "min_score": 0, "followup": {"enabled": False}}},
        lead_sources=[],
        email={
            "provider": "smtp",
            "smtp_host": "smtp.fastmail.com",
            "smtp_port": 587,
            "smtp_user": "hello@aiseoautopilot.com",
            "smtp_password_env": "SMTP_PASSWORD",
        },
        compliance={"include_unsubscribe": True, "unsubscribe_url": "x", "can_spam_required": True},
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    engine = Engine(cfg)
    engine.sender.send = MagicMock(return_value="sent")

    engine.store.upsert_lead(
        Lead(
            id="jane.doe@example.com",
            name="Jane",
            company="Jane Co",
            email="jane.doe@example.com",
            phone="",
            service="med spa",
            city="Miami",
            state="FL",
            source="t",
            score=80,
            status="new",
            email_method="direct",
        )
    )

    sent = engine.run_initial_outreach()
    assert sent == 0
    assert engine.sender.send.call_count == 0

    cur = engine.store.conn.cursor()
    row = cur.execute("SELECT payload_json FROM actions WHERE action_type='outreach.blocked' ORDER BY ts DESC LIMIT 1").fetchone()
    assert row is not None
    payload = json.loads(row[0])
    assert payload["reason"] == "blocked-fastmail-outreach"
    assert payload["kind"] == "initial"


def test_engine_blocks_role_inboxes_by_default() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)

    engine = _make_engine(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        outreach_cfg={
            "agent_id": "agent.outreach.v1",
            "permissions": ["lead.read", "lead.write", "email.send"],
            "daily_send_limit": 10,
            "min_score": 0,
            "followup": {"enabled": False},
        },
    )

    engine.store.upsert_lead(
        Lead(
            id="info@example.com",
            name="",
            company="Info Co",
            email="info@example.com",
            phone="",
            service="med spa",
            city="Miami",
            state="FL",
            source="t",
            score=80,
            status="new",
            email_method="direct",
        )
    )
    engine.store.upsert_lead(
        Lead(
            id="jane.doe@example.com",
            name="Jane",
            company="Jane Co",
            email="jane.doe@example.com",
            phone="",
            service="med spa",
            city="Miami",
            state="FL",
            source="t",
            score=80,
            status="new",
            email_method="direct",
        )
    )

    sent = engine.run_initial_outreach()
    assert sent == 1
    assert engine.store.get_lead_status("jane.doe@example.com") == "contacted"
    assert engine.store.get_lead_status("info@example.com") == "new"


def test_engine_pauses_outreach_when_bounce_rate_spikes() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)

    engine = _make_engine(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        outreach_cfg={
            "agent_id": "agent.outreach.v1",
            "permissions": ["lead.read", "lead.write", "email.send"],
            "daily_send_limit": 10,
            "min_score": 0,
            "followup": {"enabled": False},
            "bounce_pause": {"enabled": True, "window_days": 7, "threshold": 0.25, "min_emailed": 20},
            "allowed_email_methods": ["direct"],
        },
    )

    # Seed 20 recently-emailed leads that are now marked bounced.
    for i in range(20):
        email = f"person{i}@example.com"
        engine.store.upsert_lead(
            Lead(
                id=email,
                name="",
                company=f"C{i}",
                email=email,
                phone="",
                service="med spa",
                city="Miami",
                state="FL",
                source="t",
                score=80,
                status="contacted",
                email_method="direct",
            )
        )
        engine.store.add_message(lead_id=email, channel="email", subject="s", body="b", status="sent")
        engine.store.mark_status_by_email(email, "bounced")

    sent = engine.run_initial_outreach()
    assert sent == 0

    cur = engine.store.conn.cursor()
    paused = cur.execute("SELECT COUNT(1) FROM actions WHERE action_type='outreach.paused'").fetchone()[0]
    assert int(paused or 0) >= 1

    payload_json = cur.execute(
        "SELECT payload_json FROM actions WHERE action_type='outreach.paused' ORDER BY ts DESC LIMIT 1"
    ).fetchone()[0]
    payload = json.loads(payload_json)
    assert payload["trigger"] == "overall"
    assert payload["deliverability_overall"]["emailed"] == 20
    assert payload["deliverability_filtered"]["emailed"] == 20


def test_engine_pauses_outreach_when_filtered_bounce_rate_spikes_even_if_overall_ok() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)

    engine = _make_engine(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        outreach_cfg={
            "agent_id": "agent.outreach.v1",
            "permissions": ["lead.read", "lead.write", "email.send"],
            "daily_send_limit": 10,
            "min_score": 0,
            "followup": {"enabled": False},
            "bounce_pause": {"enabled": True, "window_days": 7, "threshold": 0.25, "min_emailed": 20},
            "allowed_email_methods": ["direct"],
        },
    )

    # Seed 20 direct emailed leads, 10 bounced.
    for i in range(20):
        email = f"direct{i}@example.com"
        engine.store.upsert_lead(
            Lead(
                id=email,
                name="",
                company=f"D{i}",
                email=email,
                phone="",
                service="med spa",
                city="Miami",
                state="FL",
                source="t",
                score=80,
                status="contacted",
                email_method="direct",
            )
        )
        engine.store.add_message(lead_id=email, channel="email", subject="s", body="b", status="sent")
        if i < 10:
            engine.store.mark_status_by_email(email, "bounced")

    # Add 40 other emailed leads that are not bounced to keep overall bounce rate under threshold.
    for i in range(40):
        email = f"other{i}@example.com"
        engine.store.upsert_lead(
            Lead(
                id=email,
                name="",
                company=f"O{i}",
                email=email,
                phone="",
                service="med spa",
                city="Miami",
                state="FL",
                source="t",
                score=80,
                status="contacted",
                email_method="scrape",
            )
        )
        engine.store.add_message(lead_id=email, channel="email", subject="s", body="b", status="sent")

    sent = engine.run_initial_outreach()
    assert sent == 0

    cur = engine.store.conn.cursor()
    payload_json = cur.execute(
        "SELECT payload_json FROM actions WHERE action_type='outreach.paused' ORDER BY ts DESC LIMIT 1"
    ).fetchone()[0]
    payload = json.loads(payload_json)
    assert payload["trigger"] == "filtered"
    assert payload["deliverability_overall"]["emailed"] == 60
    assert payload["deliverability_overall"]["bounced"] == 10
    assert payload["deliverability_filtered"]["emailed"] == 20
    assert payload["deliverability_filtered"]["bounced"] == 10


def test_context_store_get_warm_close_leads_filters_and_orders() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    store = ContextStore(sqlite_path=sqlite_path, audit_log=audit_log)

    eligible_newer = "newer@example.com"
    eligible_older = "older@example.com"
    blocked_recent = "recent@example.com"
    blocked_optout = "optout@example.com"
    blocked_optout_custom_id = "custom-optout@example.com"
    blocked_converted = "converted@example.com"
    blocked_method = "method@example.com"

    def _put(email: str, status: str, method: str = "direct") -> None:
        store.upsert_lead(_lead(email=email, status=status, score=90, email_method=method))

    _put(eligible_newer, "interested")
    _put(eligible_older, "replied")
    _put(blocked_recent, "interested")
    _put(blocked_optout, "interested")
    store.upsert_lead(
        Lead(
            id="lead-custom-optout-id",
            name="custom",
            company="custom",
            email=blocked_optout_custom_id,
            phone="",
            service="med spa",
            city="Miami",
            state="FL",
            source="t",
            score=90,
            status="interested",
            email_method="direct",
        )
    )
    _put(blocked_converted, "interested")
    _put(blocked_method, "interested", method="scrape")

    store.log_action("agent", "lead.reply", "t1", {"lead_id": eligible_newer})
    store.log_action("agent", "sms.inbound", "t2", {"lead_id": eligible_older, "classification": "interested"})
    store.log_action("agent", "lead.reply", "t3", {"lead_id": blocked_recent})
    store.log_action("agent", "lead.reply", "t4", {"lead_id": blocked_optout})
    store.log_action("agent", "lead.reply", "t4b", {"lead_id": "lead-custom-optout-id"})
    store.log_action("agent", "lead.reply", "t5", {"lead_id": blocked_converted})
    store.log_action("agent", "lead.reply", "t6", {"lead_id": blocked_method})
    store.log_action("agent", "conversion.booking", "t7", {"lead_id": blocked_converted})

    # Force deterministic ordering: older signal should sort after newer signal.
    older_ts = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    store.conn.execute(
        """
        UPDATE actions
        SET ts = ?
        WHERE action_type = 'sms.inbound'
          AND COALESCE(json_extract(payload_json, '$.lead_id'), '') = ?
        """,
        (older_ts, eligible_older),
    )
    store.conn.commit()

    store.add_opt_out(blocked_optout)
    store.add_opt_out(blocked_optout_custom_id)
    store.add_message(
        lead_id=blocked_recent,
        channel="email",
        subject="warm",
        body="warm",
        status="sent",
        step=90,
    )

    rows = list(
        store.get_warm_close_leads(
            min_score=70,
            limit=10,
            cooldown_cutoff_ts=(datetime.now(timezone.utc) - timedelta(hours=12)).isoformat(),
            warm_close_step=90,
            email_methods=["direct"],
        )
    )
    assert [str(r["id"]) for r in rows] == [eligible_newer, eligible_older]
    store.close()


def test_engine_run_warm_close_emails_sends_and_logs() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    engine = _make_engine(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        outreach_cfg={
            "agent_id": "agent.outreach.v1",
            "permissions": ["lead.read", "lead.write", "email.send"],
            "daily_send_limit": 10,
            "min_score": 0,
            "followup": {"enabled": False},
            "warm_close_email": {"enabled": True, "daily_send_limit": 1, "cooldown_hours": 24, "min_score": 0},
            "allowed_email_methods": ["direct"],
            "bounce_pause": {"enabled": False},
        },
    )
    lead_id = "reply@example.com"
    engine.store.upsert_lead(_lead(email=lead_id, status="replied", score=95, name="Reply Lead"))
    engine.store.log_action("agent", "lead.reply", "trace-reply", {"lead_id": lead_id})

    sent = engine.run_warm_close_emails()
    assert sent == 1
    assert engine.sender.send.call_count == 1
    assert engine.store.get_lead_status(lead_id) == "replied"

    args = engine.sender.send.call_args.kwargs
    assert args["to_email"] == lead_id
    assert "quick next step" in str(args["subject"]).lower()

    msg = engine.store.conn.execute(
        "SELECT step, status FROM messages WHERE lead_id=? ORDER BY id DESC LIMIT 1",
        (lead_id,),
    ).fetchone()
    assert msg is not None
    assert int(msg["step"] or 0) == 90
    assert str(msg["status"]) == "sent"

    row = engine.store.conn.execute(
        "SELECT payload_json FROM actions WHERE action_type='email.send' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row is not None
    payload = json.loads(str(row["payload_json"]))
    assert payload["kind"] == "warm_close_email"
    assert payload["lead_id"] == lead_id
    assert int(payload["step"]) == 90
    assert payload["trigger"] == "status_replied_or_interested"


def test_engine_run_returns_sent_warm_close_metric() -> None:
    tmp = f"test_{uuid.uuid4().hex}"
    sqlite_path, audit_log = _tmp_state_paths(tmp)
    engine = _make_engine(
        sqlite_path=sqlite_path,
        audit_log=audit_log,
        outreach_cfg={
            "agent_id": "agent.outreach.v1",
            "permissions": ["lead.read", "lead.write", "email.send"],
            "daily_send_limit": 0,
            "min_score": 0,
            "followup": {"enabled": False},
            "warm_close_email": {"enabled": True, "daily_send_limit": 1, "cooldown_hours": 24, "min_score": 0},
            "allowed_email_methods": ["direct"],
            "bounce_pause": {"enabled": False},
        },
    )
    lead_id = "interested@example.com"
    engine.store.upsert_lead(_lead(email=lead_id, status="interested", score=90, name="Interested Lead"))
    engine.store.log_action("agent", "lead.reply", "trace-int", {"lead_id": lead_id})

    result = engine.run()
    assert int(result["sent_initial"]) == 0
    assert int(result["sent_warm_close"]) == 1
    assert int(result["sent_followup"]) == 0
