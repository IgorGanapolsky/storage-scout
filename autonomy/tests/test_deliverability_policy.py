from __future__ import annotations

import csv
import sqlite3
import uuid
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
    with sqlite3.connect(sqlite_path) as conn:
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


def test_lead_source_csv_infers_email_method(tmp_path: Path) -> None:
    csv_path = tmp_path / "leads.csv"
    rows = [
        {"company": "A", "email": "info@example.com"},
        {"company": "B", "email": "jane.doe@example.com"},
        {"company": "C", "email": "owner@example.com", "email_method": "Apollo"},
        {"company": "D", "email": "x@example.com", "notes": "source=google_places; email=scrape"},
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r.keys()}))
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    leads = LeadSourceCSV(path=str(csv_path), source="t").load()
    by_email = {l.email: l for l in leads}
    assert by_email["info@example.com"].email_method == "unknown"
    assert by_email["jane.doe@example.com"].email_method == "direct"
    assert by_email["owner@example.com"].email_method == "apollo"
    assert by_email["x@example.com"].email_method == "scrape"


def _make_engine(*, sqlite_path: str, audit_log: str, outreach_cfg: dict) -> Engine:
    cfg = EngineConfig(
        mode="live",
        company={
            "name": "CallCatcher Ops",
            "website": "https://callcatcherops.com",
            "intake_url": "https://callcatcherops.com/callcatcherops/intake.html",
            "reply_to": "hello@callcatcherops.com",
            "mailing_address": "Test Address",
            "signature": "— CallCatcher Ops",
        },
        agents={"outreach": outreach_cfg, "observer": {"observe_threshold": 999, "reflect_threshold": 999}},
        lead_sources=[],
        email={
            "provider": "smtp",
            "smtp_host": "smtp.fastmail.com",
            "smtp_port": 587,
            "smtp_user": "hello@callcatcherops.com",
            "smtp_password_env": "SMTP_PASSWORD",
        },
        compliance={
            "include_unsubscribe": True,
            "unsubscribe_url": "https://callcatcherops.com/unsubscribe.html?email={{email}}",
            "can_spam_required": True,
        },
        storage={"sqlite_path": sqlite_path, "audit_log": audit_log},
    )
    engine = Engine(cfg)
    engine.sender.send = MagicMock(return_value="sent")
    return engine


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

