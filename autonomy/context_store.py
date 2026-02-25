from __future__ import annotations

import contextlib
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / "autonomy" / "state"


def _resolve_under_state_dir(raw_path: str) -> Path:
    """Resolve a path and ensure it stays within autonomy/state.

    Sonar flags filesystem paths sourced from config as user-controlled. We
    restrict runtime state writes to a safe directory to avoid path traversal
    and accidental writes elsewhere on disk.
    """

    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()

    state_root = STATE_DIR.resolve()
    if resolved != state_root and state_root not in resolved.parents:
        raise ValueError(f"Refusing path outside {state_root}: {resolved}")

    return resolved


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Lead:
    id: str
    name: str
    company: str
    email: str
    phone: str
    service: str
    city: str
    state: str
    source: str
    score: int = 0
    status: str = "new"
    email_method: str = "unknown"  # scrape|guess|unknown


class ContextStore:
    def __init__(self, sqlite_path: str, audit_log: str) -> None:
        self.sqlite_path = _resolve_under_state_dir(sqlite_path)
        self.audit_log = _resolve_under_state_dir(audit_log)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.sqlite_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
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
              email_method TEXT,
              created_at TEXT,
              updated_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS actions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT,
              agent_id TEXT,
              action_type TEXT,
              trace_id TEXT,
              payload_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              lead_id TEXT,
              channel TEXT,
              subject TEXT,
              body TEXT,
              status TEXT,
              ts TEXT,
              step INTEGER DEFAULT 0
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS opt_outs (
              email TEXT PRIMARY KEY,
              ts TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS observations (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              lead_id TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        with contextlib.suppress(sqlite3.OperationalError):
            cur.execute("ALTER TABLE actions ADD COLUMN observed INTEGER DEFAULT 0")
        with contextlib.suppress(sqlite3.OperationalError):
            cur.execute("ALTER TABLE messages ADD COLUMN step INTEGER DEFAULT 0")
        self.conn.commit()
        self._migrate_leads_email_method()

    def _migrate_leads_email_method(self) -> None:
        """Ensure leads.email_method exists and is normalized.

        This lets the outreach engine enforce a safe deliverability policy.
        """
        cur = self.conn.cursor()
        cols = {str(r[1]) for r in cur.execute("PRAGMA table_info(leads)").fetchall()}
        if "email_method" not in cols:
            cur.execute("ALTER TABLE leads ADD COLUMN email_method TEXT")
        cur.execute("UPDATE leads SET email_method='unknown' WHERE email_method IS NULL OR email_method=''")
        self.conn.commit()

    def upsert_lead(self, lead: Lead) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO leads (id, name, company, email, phone, service, city, state, source, score, status, email_method, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name,
              company=excluded.company,
              email=excluded.email,
              phone=excluded.phone,
              service=excluded.service,
              city=excluded.city,
              state=excluded.state,
              source=excluded.source,
              score=excluded.score,
              email_method=excluded.email_method,
              updated_at=excluded.updated_at
            """,
            (
                lead.id,
                lead.name,
                lead.company,
                lead.email,
                lead.phone,
                lead.service,
                lead.city,
                lead.state,
                lead.source,
                lead.score,
                lead.status,
                (lead.email_method or "unknown"),
                now_iso(),
                now_iso(),
            ),
        )
        self.conn.commit()

    def get_unsent_leads(
        self,
        min_score: int,
        limit: int,
        *,
        email_methods: list[str] | None = None,
    ) -> Iterable[sqlite3.Row]:
        cur = self.conn.cursor()

        sql = """
            SELECT id, name, company, email, phone, service, city, state, source, score, status, email_method
            FROM leads
            WHERE status = 'new' AND score >= ?
        """
        params: list[object] = [int(min_score)]
        if email_methods:
            placeholders = ",".join(["?"] * len(email_methods))
            sql += f" AND COALESCE(email_method,'unknown') IN ({placeholders})"
            params.extend([(m or "unknown") for m in email_methods])
        sql += """
            ORDER BY score DESC
            LIMIT ?
        """
        params.append(int(limit))
        cur.execute(sql, tuple(params))
        return cur.fetchall()

    def get_followup_leads(
        self,
        min_score: int,
        limit: int,
        max_emails_per_lead: int,
        cutoff_ts: str,
        *,
        email_methods: list[str] | None = None,
    ) -> Iterable[sqlite3.Row]:
        """Return contacted leads eligible for an email follow-up."""
        cur = self.conn.cursor()
        sql = """
            SELECT
              l.id, l.name, l.company, l.email, l.phone, l.service, l.city, l.state, l.source, l.score, l.status, l.email_method,
              COALESCE((
                SELECT COUNT(1)
                FROM messages m
                WHERE m.lead_id = l.id AND m.channel = 'email' AND m.status = 'sent'
              ), 0) AS email_message_count,
              COALESCE((
                SELECT MAX(m.ts)
                FROM messages m
                WHERE m.lead_id = l.id AND m.channel = 'email' AND m.status = 'sent'
              ), '') AS last_email_ts
            FROM leads l
            WHERE l.status = 'contacted'
              AND l.score >= ?
              AND COALESCE((
                SELECT COUNT(1)
                FROM messages m
                WHERE m.lead_id = l.id AND m.channel = 'email' AND m.status = 'sent'
              ), 0) < ?
              AND COALESCE((
                SELECT MAX(m.ts)
                FROM messages m
                WHERE m.lead_id = l.id AND m.channel = 'email' AND m.status = 'sent'
              ), '') <= ?
        """
        params: list[object] = [int(min_score), int(max_emails_per_lead), str(cutoff_ts)]
        if email_methods:
            placeholders = ",".join(["?"] * len(email_methods))
            sql += f" AND COALESCE(l.email_method,'unknown') IN ({placeholders})"
            params.extend([(m or "unknown") for m in email_methods])
        sql += """
            ORDER BY last_email_ts ASC
            LIMIT ?
        """
        params.append(int(limit))
        cur.execute(sql, tuple(params))
        return cur.fetchall()

    def mark_contacted(self, lead_id: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE leads SET status='contacted', updated_at=? WHERE id=?",
            (now_iso(), lead_id),
        )
        self.conn.commit()

    def mark_status_by_email(self, email: str, status: str) -> bool:
        """Update lead status by email (lead id is normalized email).

        Returns True if a lead row was updated, False otherwise.
        """

        normalized = (email or "").strip().lower()
        if not normalized:
            return False
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE leads SET status=?, updated_at=? WHERE id=?",
            (status, now_iso(), normalized),
        )
        self.conn.commit()
        return bool(cur.rowcount)

    def get_lead_status(self, email: str) -> str | None:
        normalized = (email or "").strip().lower()
        if not normalized:
            return None
        cur = self.conn.cursor()
        row = cur.execute("SELECT status FROM leads WHERE id=?", (normalized,)).fetchone()
        return str(row[0]) if row else None

    def add_message(self, lead_id: str, channel: str, subject: str, body: str, status: str, step: int = 0) -> int:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO messages (lead_id, channel, subject, body, status, ts, step) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (lead_id, channel, subject, body, status, now_iso(), step),
        )
        self.conn.commit()
        return cur.lastrowid or 0

    def get_last_email_step(self, lead_id: str) -> int:
        """Return the step number of the most recent email sent to this lead."""
        cur = self.conn.cursor()
        row = cur.execute(
            "SELECT step FROM messages WHERE lead_id=? AND channel='email' AND status='sent' ORDER BY ts DESC LIMIT 1",
            (lead_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def add_opt_out(self, email: str) -> None:
        normalized = (email or "").strip().lower()
        if not normalized:
            return
        cur = self.conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO opt_outs (email, ts) VALUES (?, ?)",
            (normalized, now_iso()),
        )
        self.conn.commit()

    def is_opted_out(self, email: str) -> bool:
        normalized = (email or "").strip().lower()
        if not normalized:
            return False
        cur = self.conn.cursor()
        cur.execute("SELECT 1 FROM opt_outs WHERE email=?", (normalized,))
        return cur.fetchone() is not None

    def log_action(self, agent_id: str, action_type: str, trace_id: str, payload: dict[str, Any]) -> None:
        record = {
            "ts": now_iso(),
            "agent_id": agent_id,
            "action_type": action_type,
            "trace_id": trace_id,
            "payload": payload,
        }
        with self.audit_log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO actions (ts, agent_id, action_type, trace_id, payload_json) VALUES (?, ?, ?, ?, ?)",
            (record["ts"], agent_id, action_type, trace_id, json.dumps(payload)),
        )
        self.conn.commit()

    def get_unobserved_actions(self, lead_id: str) -> list[sqlite3.Row]:
        """Return actions for a lead that haven't been compressed into observations yet."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, ts, agent_id, action_type, trace_id, payload_json
            FROM actions
            WHERE observed = 0
              AND json_extract(payload_json, '$.lead_id') = ?
            ORDER BY ts ASC
            """,
            (lead_id,),
        )
        return cur.fetchall()

    def mark_actions_observed(self, action_ids: list[int]) -> None:
        """Mark actions as compressed into observations."""
        if not action_ids:
            return
        placeholders = ",".join("?" for _ in action_ids)
        cur = self.conn.cursor()
        cur.execute(
            f"UPDATE actions SET observed = 1 WHERE id IN ({placeholders})",
            action_ids,
        )
        self.conn.commit()

    def add_observation(self, lead_id: str, content: str) -> None:
        """Store a compressed observation for a lead."""
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO observations (lead_id, content, created_at) VALUES (?, ?, ?)",
            (lead_id, content, now_iso()),
        )
        self.conn.commit()

    def get_observations(self, lead_id: str) -> list[sqlite3.Row]:
        """Return all observations for a lead, oldest first."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, lead_id, content, created_at FROM observations WHERE lead_id = ? ORDER BY created_at ASC",
            (lead_id,),
        )
        return cur.fetchall()

    def replace_observations(self, lead_id: str, condensed_content: str) -> None:
        """Replace all observations for a lead with a single condensed observation (Reflector)."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM observations WHERE lead_id = ?", (lead_id,))
        cur.execute(
            "INSERT INTO observations (lead_id, content, created_at) VALUES (?, ?, ?)",
            (lead_id, condensed_content, now_iso()),
        )
        self.conn.commit()

    def get_leads_with_unobserved_actions(self) -> list[str]:
        """Return distinct lead IDs that have unobserved actions."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT DISTINCT json_extract(payload_json, '$.lead_id')
            FROM actions
            WHERE observed = 0
              AND json_extract(payload_json, '$.lead_id') IS NOT NULL
            """,
        )
        return [row[0] for row in cur.fetchall()]

    def get_message_history(self, lead_id: str) -> list[sqlite3.Row]:
        """Return all messages for a lead, oldest first."""
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, lead_id, channel, subject, status, ts FROM messages WHERE lead_id = ? ORDER BY ts ASC",
            (lead_id,),
        )
        return cur.fetchall()

    def email_deliverability(self, *, days: int, email_methods: list[str] | None = None) -> dict[str, object]:
        """Compute bounce rate for leads emailed in the last N days.

        Denominator is distinct leads emailed (messages.status='sent').
        Numerator is those leads whose current status is 'bounced'.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=int(days))).isoformat()
        cur = self.conn.cursor()

        where = ""
        params: list[object] = [cutoff]
        if email_methods:
            placeholders = ",".join(["?"] * len(email_methods))
            where = f" AND COALESCE(l.email_method,'unknown') IN ({placeholders})"
            params.extend([(m or "unknown") for m in email_methods])

        emailed = int(
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT m.lead_id)
                FROM messages m
                JOIN leads l ON l.id = m.lead_id
                WHERE m.channel='email' AND m.status='sent' AND m.ts >= ?{where}
                """,
                tuple(params),
            ).fetchone()[0]
            or 0
        )
        bounced = int(
            cur.execute(
                f"""
                SELECT COUNT(DISTINCT m.lead_id)
                FROM messages m
                JOIN leads l ON l.id = m.lead_id
                WHERE m.channel='email' AND m.status='sent' AND m.ts >= ?{where}
                  AND l.status='bounced'
                """,
                tuple(params),
            ).fetchone()[0]
            or 0
        )

        bounce_rate = float(bounced) / float(emailed) if emailed else 0.0
        return {
            "days": int(days),
            "emailed": emailed,
            "bounced": bounced,
            "bounce_rate": bounce_rate,
        }
