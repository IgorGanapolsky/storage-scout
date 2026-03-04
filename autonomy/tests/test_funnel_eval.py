from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from autonomy.tools import funnel_eval
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


def test_funnel_eval_missing_sqlite_raises(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.sqlite3"
    with pytest.raises(SystemExit):
        load_warm_close_funnel_eval(sqlite_path=missing, days=30)


def test_funnel_eval_empty_statuses_defaults_and_uses_latest_send_when_both_exist(tmp_path: Path) -> None:
    db = tmp_path / "funnel_both.sqlite3"
    conn = sqlite3.connect(db)
    _setup_schema(conn)
    now = datetime.now(UTC).replace(microsecond=0)
    older = (now - timedelta(minutes=5)).isoformat()
    newer = now.isoformat()

    conn.execute("INSERT INTO leads (id, status, score) VALUES (?, ?, ?)", ("lead-z@example.com", "replied", 90))
    conn.execute(
        "INSERT INTO messages (lead_id, channel, subject, body, status, ts, step) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lead-z@example.com", "email", "s", "b", "sent", older, 90),
    )
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("email.send", newer, '{"lead_id":"lead-z@example.com","kind":"warm_close_email","status":"sent"}'),
    )
    # Booking at old ts should be ignored because latest warm-close ts is from action.
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.booking", older, '{"lead_id":"lead-z@example.com"}'),
    )
    conn.commit()
    conn.close()

    result = load_warm_close_funnel_eval(sqlite_path=db, statuses=tuple(), days=30)
    assert result.statuses == ("interested", "replied")
    assert result.warm_close_sent_leads == 1
    assert result.booked_after_warm_close_leads == 0


def test_funnel_eval_without_actions_table_hits_fallback_paths(tmp_path: Path) -> None:
    db = tmp_path / "funnel_no_actions.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE leads (id TEXT PRIMARY KEY, status TEXT, score INTEGER)")
    conn.execute("CREATE TABLE messages (lead_id TEXT, channel TEXT, subject TEXT, body TEXT, status TEXT, ts TEXT, step INTEGER)")
    conn.execute("INSERT INTO leads (id, status, score) VALUES (?, ?, ?)", ("lead-q@example.com", "interested", 90))
    conn.execute(
        "INSERT INTO messages (lead_id, channel, subject, body, status, ts, step) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("lead-q@example.com", "email", "s", "b", "sent", datetime.now(UTC).replace(microsecond=0).isoformat(), 90),
    )
    conn.commit()
    conn.close()
    result = load_warm_close_funnel_eval(sqlite_path=db, days=30)
    assert result.warm_close_sent_leads == 1
    assert result.paid_after_warm_close_leads == 0


def test_funnel_eval_cli_json_and_text_modes(tmp_path: Path, monkeypatch, capsys) -> None:
    db = tmp_path / "funnel_cli.sqlite3"
    conn = sqlite3.connect(db)
    _setup_schema(conn)
    conn.execute("INSERT INTO leads (id, status, score) VALUES (?, ?, ?)", ("lead-r@example.com", "interested", 75))
    conn.commit()
    conn.close()

    monkeypatch.setattr("sys.argv", ["funnel_eval.py", "--sqlite", str(db), "--json"])
    funnel_eval.main()
    payload = json.loads(capsys.readouterr().out)
    assert payload["cohort_leads"] == 1

    monkeypatch.setattr("sys.argv", ["funnel_eval.py", "--sqlite", str(db)])
    funnel_eval.main()
    out = capsys.readouterr().out
    assert "Warm-Close Funnel Eval" in out
    assert "Cohort (interested,replied): 1" in out
