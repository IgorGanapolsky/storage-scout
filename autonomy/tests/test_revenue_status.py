from __future__ import annotations

import pytest
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from autonomy.tools import revenue_status
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


def test_revenue_status_missing_db_raises(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(SystemExit, match="Missing sqlite DB"):
        load_revenue_status(
            sqlite_path=missing,
            days=30,
            payment_amount_usd=249.0,
            booking_amount_usd=249.0,
        )


def test_revenue_status_main_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "main_json.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE actions (action_type TEXT, ts TEXT, payload_json TEXT)")
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.payment", datetime.now(UTC).replace(microsecond=0).isoformat(), '{"source":"fastmail"}'),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "sys.argv",
        [
            "revenue_status.py",
            "--sqlite",
            str(db_path),
            "--days",
            "7",
            "--payment-amount-usd",
            "249",
            "--booking-amount-usd",
            "149",
            "--json",
        ],
    )
    revenue_status.main()
    out = capsys.readouterr().out
    assert '"recognized_revenue_usd": 249.0' in out
    assert '"payments_total": 1' in out


def test_revenue_status_main_human_output_defaults_from_env(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "main_human.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE actions (action_type TEXT, ts TEXT, payload_json TEXT)")
    conn.execute(
        "INSERT INTO actions (action_type, ts, payload_json) VALUES (?, ?, ?)",
        ("conversion.booking", datetime.now(UTC).replace(microsecond=0).isoformat(), '{"source":"calendly"}'),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("AEO_SETUP_PRICE_USD", "300")
    monkeypatch.setenv("AEO_BOOKING_VALUE_USD", "450")
    monkeypatch.setattr("sys.argv", ["revenue_status.py", "--sqlite", str(db_path), "--days", "30"])

    revenue_status.main()
    out = capsys.readouterr().out
    assert "AEO Autopilot Revenue Status" in out
    assert "Recognized revenue: $0.00" in out
    assert "Booked pipeline value: $450.00" in out
