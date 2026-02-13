import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

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
              ts TEXT
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
        self.conn.commit()

    def upsert_lead(self, lead: Lead) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            INSERT INTO leads (id, name, company, email, phone, service, city, state, source, score, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                now_iso(),
                now_iso(),
            ),
        )
        self.conn.commit()

    def get_unsent_leads(self, min_score: int, limit: int) -> Iterable[sqlite3.Row]:
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT id, name, company, email, phone, service, city, state, source, score, status
            FROM leads
            WHERE status = 'new' AND score >= ?
            ORDER BY score DESC
            LIMIT ?
            """,
            (min_score, limit),
        )
        return cur.fetchall()

    def get_followup_leads(
        self,
        min_score: int,
        limit: int,
        max_emails_per_lead: int,
        cutoff_ts: str,
    ) -> Iterable[sqlite3.Row]:
        """Return contacted leads eligible for an email follow-up."""
        cur = self.conn.cursor()
        cur.execute(
            """
            SELECT
              l.id, l.name, l.company, l.email, l.phone, l.service, l.city, l.state, l.source, l.score, l.status,
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
            ORDER BY last_email_ts ASC
            LIMIT ?
            """,
            (min_score, max_emails_per_lead, cutoff_ts, limit),
        )
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

    def add_message(self, lead_id: str, channel: str, subject: str, body: str, status: str) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO messages (lead_id, channel, subject, body, status, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (lead_id, channel, subject, body, status, now_iso()),
        )
        self.conn.commit()

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

    def log_action(self, agent_id: str, action_type: str, trace_id: str, payload: Dict[str, Any]) -> None:
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
