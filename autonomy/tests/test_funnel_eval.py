from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autonomy.tools.funnel_eval import load_warm_close_funnel_eval

UTC = timezone.utc


def _setup_schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE leads (id TEXT PRIMARY KEY, status TEXT, score INTEGER)")
    conn.execute("CREATE TABLE messages (lead_id TEXT, channel TEXT, subject TEXT, body TEXT, status TEXT, ts TEXT, step INTEGER)")
    conn.execute("CREATE TABLE actions (action_type TEXT, ts TEXT, payload_json TEXT)")


def test_funnel_eval_counts_step90_and_kind_paths(tmp_path: Path) -> None:
    db = tmp_path / "funnel.sqlite3"
    conn = sqlite3.connect(db)
    _setup_schema(conn)
    now = datetime.now(UTC).replace(microsecond=0)
    ts = now.isoformat()

    conn.executemany(
        "INSERT INTO leads (id, status, score) VALUES (?, ?, ?)",
        [
            ("lead-a@example.com", "interested", 90),
            ("lead-b@example.com", "replied", 88),
            ("lead-c@example.com", "interested", 81),
        ],
    )
    conn.execute(
        "INSERT INTO messages (lead_id, channel, subject, body, status, ts, step) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lead-a@example.com", "email", "s", "b", "sent", ts, 90),
    )
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("email.send", ts, '{"lead_id":"lead-b@example.com","kind":"warm_close_email","status":"sent"}'),
    )
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.booking", ts, '{"lead_id":"lead-a@example.com"}'),
    )
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.payment", ts, '{"lead_id":"lead-b@example.com"}'),
    )
    conn.commit()
    conn.close()

    result = load_warm_close_funnel_eval(sqlite_path=db, days=30)
    assert result.cohort_leads == 3
    assert result.warm_close_sent_leads == 2
    assert result.warm_close_sent_via_step90_leads == 1
    assert result.warm_close_sent_via_kind_leads == 1
    assert result.booked_after_warm_close_leads == 1
    assert result.paid_after_warm_close_leads == 1
    assert result.converted_after_warm_close_leads == 2
    assert result.warm_close_missing_leads == 1


def test_funnel_eval_ignores_conversion_before_warm_close_send(tmp_path: Path) -> None:
    db = tmp_path / "funnel_order.sqlite3"
    conn = sqlite3.connect(db)
    _setup_schema(conn)
    now = datetime.now(UTC).replace(microsecond=0)
    before = (now - timedelta(hours=2)).isoformat()
    after = (now + timedelta(hours=2)).isoformat()
    send_ts = now.isoformat()

    conn.execute("INSERT INTO leads (id, status, score) VALUES (?, ?, ?)", ("lead-x@example.com", "interested", 90))
    conn.execute(
        "INSERT INTO messages (lead_id, channel, subject, body, status, ts, step) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lead-x@example.com", "email", "s", "b", "sent", send_ts, 90),
    )
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.booking", before, '{"lead_id":"lead-x@example.com"}'),
    )
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.payment", after, '{"lead_id":"lead-x@example.com"}'),
    )
    conn.commit()
    conn.close()

    result = load_warm_close_funnel_eval(sqlite_path=db, days=30)
    assert result.booked_after_warm_close_leads == 0
    assert result.paid_after_warm_close_leads == 1
    assert result.converted_after_warm_close_leads == 1


def test_funnel_eval_missing_required_tables_returns_zero(tmp_path: Path) -> None:
    db = tmp_path / "missing.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE actions (action_type TEXT, ts TEXT, payload_json TEXT)")
    conn.commit()
    conn.close()

    result = load_warm_close_funnel_eval(sqlite_path=db, days=30)
    assert result.cohort_leads == 0
    assert result.warm_close_sent_leads == 0
    assert result.warm_close_missing_leads == 0
    assert result.booked_after_warm_close_leads == 0
    assert result.paid_after_warm_close_leads == 0
    assert result.warm_close_send_rate == 0.0
    assert result.conversion_rate_from_warm_close == 0.0
