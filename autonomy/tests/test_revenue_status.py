from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autonomy.tools.revenue_status import load_revenue_status

UTC = timezone.utc


def test_revenue_status_no_actions_table_returns_zero(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE leads (id TEXT)")
    conn.commit()
    conn.close()

    status = load_revenue_status(
        sqlite_path=db_path,
        days=30,
        payment_amount_usd=249.0,
        booking_amount_usd=249.0,
    )

    assert status.payments_total == 0
    assert status.bookings_total == 0
    assert status.recognized_revenue_usd == 0.0
    assert status.booked_pipeline_revenue_usd == 0.0
    assert status.payment_sources == {}


def test_revenue_status_counts_payments_bookings_and_sources(tmp_path: Path) -> None:
    db_path = tmp_path / "revenue.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE actions (action_type TEXT, ts TEXT, payload_json TEXT)")

    now = datetime.now(UTC).replace(microsecond=0)
    recent_ts = now.isoformat()
    old_ts = (now - timedelta(days=45)).isoformat()
    conn.executemany(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        [
            ("conversion.payment", recent_ts, '{"source":"fastmail"}'),
            ("payment.received", recent_ts, '{"source":"manual"}'),
            ("conversion.payment", old_ts, '{"source":"fastmail"}'),
            ("conversion.booking", recent_ts, '{"source":"calendly"}'),
            ("conversion.booking", old_ts, '{"source":"calendly"}'),
        ],
    )
    conn.commit()
    conn.close()

    status = load_revenue_status(
        sqlite_path=db_path,
        days=30,
        payment_amount_usd=249.0,
        booking_amount_usd=149.0,
    )

    assert status.payments_total == 3
    assert status.payments_recent == 2
    assert status.bookings_total == 2
    assert status.bookings_recent == 1
    assert status.recognized_revenue_usd == 747.0
    assert status.booked_pipeline_revenue_usd == 298.0
    assert status.first_payment_ts == old_ts
    assert status.last_payment_ts == recent_ts
    assert status.payment_sources == {"fastmail": 2, "manual": 1}
