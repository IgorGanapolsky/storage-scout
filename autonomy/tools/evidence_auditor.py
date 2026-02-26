from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class EvidenceSignal:
    source_id: str
    impact: str  # 'positive', 'negative', 'neutral'
    note: str
    assumption_id: str


class EvidenceAuditor:
    def __init__(self, sqlite_path: Path) -> None:
        self.sqlite_path = sqlite_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes the assumptions table and seeds default strategic assumptions."""
        conn = sqlite3.connect(self.sqlite_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS assumptions (
                id TEXT PRIMARY KEY,
                statement TEXT,
                category TEXT,
                status TEXT,
                evidence_count INTEGER DEFAULT 0,
                last_updated_at TEXT
            )
            """
        )
        defaults = [
            (
                "price_point_249",
                "A $249 setup fee is an acceptable entry point for dentists.",
                "pricing",
                "pending",
            ),
            (
                "sms_recovery_priority",
                "SMS-back is the #1 pain point owners will pay to solve.",
                "product",
                "pending",
            ),
            (
                "connect_rate_threshold",
                "A 25% human connect rate is sufficient to scale the business.",
                "outreach",
                "pending",
            ),
        ]
        now = datetime.now().isoformat()
        for d in defaults:
            cursor.execute(
                """
                INSERT OR IGNORE INTO assumptions (id, statement, category, status, last_updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (d[0], d[1], d[2], d[3], now),
            )
        conn.commit()
        conn.close()

    def audit_interactions(self) -> list[EvidenceSignal]:
        """Scans the actions table for evidence related to current assumptions."""
        signals = []
        conn = sqlite3.connect(self.sqlite_path)
        cursor = conn.cursor()

        # 1. Audit Price Point Evidence
        try:
            cursor.execute("SELECT COUNT(*) FROM actions WHERE action_type='payment.received'")
            payments = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            payments = 0

        if payments > 0:
            signals.append(
                EvidenceSignal(
                    source_id="actions_table",
                    impact="positive",
                    note=f"Found {payments} successful payments at $249 price point.",
                    assumption_id="price_point_249",
                )
            )
        else:
            try:
                cursor.execute("SELECT COUNT(*) FROM leads WHERE status='replied'")
                replied = cursor.fetchone()[0]
            except sqlite3.OperationalError:
                replied = 0

            if replied > 5:
                signals.append(
                    EvidenceSignal(
                        source_id="leads_table",
                        impact="negative",
                        note=f"Found {replied} warm leads but 0 payments. Pricing friction possible.",
                        assumption_id="price_point_249",
                    )
                )

        # 2. Audit Connect Rate
        try:
            cursor.execute("SELECT COUNT(*) FROM actions WHERE action_type='call.attempt'")
            total_calls = cursor.fetchone()[0]
        except sqlite3.OperationalError:
            total_calls = 0

        if total_calls > 0:
            cursor.execute(
                "SELECT COUNT(*) FROM actions WHERE action_type='call.attempt' AND json_extract(payload_json, '$.outcome')='spoke'"
            )
            connects = cursor.fetchone()[0]
            rate = connects / total_calls
            impact = "positive" if rate >= 0.20 else "negative"
            signals.append(
                EvidenceSignal(
                    source_id="actions_table",
                    impact=impact,
                    note=f"Current connect rate is {rate:.1%}. (Target: 20%)",
                    assumption_id="connect_rate_threshold",
                )
            )

        conn.close()
        return signals

    def update_assumptions(self, signals: list[EvidenceSignal]) -> None:
        """Updates the assumption store based on new evidence signals."""
        conn = sqlite3.connect(self.sqlite_path)
        cursor = conn.cursor()
        for signal in signals:
            cursor.execute(
                "UPDATE assumptions SET evidence_count = evidence_count + 1, last_updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), signal.assumption_id),
            )
        conn.commit()
        conn.close()
