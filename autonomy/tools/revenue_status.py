#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc
PAYMENT_ACTION_TYPES = ("conversion.payment", "payment.received")
BOOKING_ACTION_TYPE = "conversion.booking"


@dataclass(frozen=True)
class RevenueStatus:
    as_of_utc: str
    window_days: int
    payment_amount_usd: float
    booking_amount_usd: float
    payments_total: int
    payments_recent: int
    bookings_total: int
    bookings_recent: int
    recognized_revenue_usd: float
    booked_pipeline_revenue_usd: float
    first_payment_ts: str
    last_payment_ts: str
    payment_sources: dict[str, int]


def _actions_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT COUNT(1) FROM sqlite_master WHERE type='table' AND name='actions'"
    ).fetchone()
    return bool(int((row[0] or 0) if row else 0))


def _count_actions(
    conn: sqlite3.Connection,
    *,
    action_types: tuple[str, ...],
    cutoff_ts: str | None = None,
) -> int:
    placeholders = ",".join(["?"] * len(action_types))
    sql = f"SELECT COUNT(1) FROM actions WHERE action_type IN ({placeholders})"
    params: list[object] = list(action_types)
    if cutoff_ts:
        sql += " AND ts >= ?"
        params.append(str(cutoff_ts))
    row = conn.execute(sql, tuple(params)).fetchone()
    return int((row[0] or 0) if row else 0)


def _first_last_payment_ts(conn: sqlite3.Connection) -> tuple[str, str]:
    placeholders = ",".join(["?"] * len(PAYMENT_ACTION_TYPES))
    row = conn.execute(
        f"""
        SELECT
          COALESCE(MIN(ts), '') AS first_ts,
          COALESCE(MAX(ts), '') AS last_ts
        FROM actions
        WHERE action_type IN ({placeholders})
        """,
        PAYMENT_ACTION_TYPES,
    ).fetchone()
    if not row:
        return "", ""
    return str(row[0] or ""), str(row[1] or "")


def _payment_source_breakdown(conn: sqlite3.Connection) -> dict[str, int]:
    placeholders = ",".join(["?"] * len(PAYMENT_ACTION_TYPES))
    rows = conn.execute(
        f"""
        SELECT
          COALESCE(NULLIF(json_extract(payload_json, '$.source'), ''), 'unknown') AS source,
          COUNT(1) AS cnt
        FROM actions
        WHERE action_type IN ({placeholders})
        GROUP BY source
        ORDER BY cnt DESC, source ASC
        """,
        PAYMENT_ACTION_TYPES,
    ).fetchall()
    return {str(source): int(count) for source, count in rows}


def load_revenue_status(
    *,
    sqlite_path: Path,
    days: int,
    payment_amount_usd: float,
    booking_amount_usd: float,
) -> RevenueStatus:
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite DB: {sqlite_path}")

    window_days = max(1, int(days))
    as_of = datetime.now(UTC).replace(microsecond=0)
    cutoff = (as_of - timedelta(days=window_days)).isoformat()
    payment_amount = float(max(0.0, payment_amount_usd))
    booking_amount = float(max(0.0, booking_amount_usd))

    with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
        if not _actions_table_exists(conn):
            return RevenueStatus(
                as_of_utc=as_of.isoformat(),
                window_days=window_days,
                payment_amount_usd=payment_amount,
                booking_amount_usd=booking_amount,
                payments_total=0,
                payments_recent=0,
                bookings_total=0,
                bookings_recent=0,
                recognized_revenue_usd=0.0,
                booked_pipeline_revenue_usd=0.0,
                first_payment_ts="",
                last_payment_ts="",
                payment_sources={},
            )

        payments_total = _count_actions(
            conn,
            action_types=PAYMENT_ACTION_TYPES,
        )
        payments_recent = _count_actions(
            conn,
            action_types=PAYMENT_ACTION_TYPES,
            cutoff_ts=cutoff,
        )
        bookings_total = _count_actions(
            conn,
            action_types=(BOOKING_ACTION_TYPE,),
        )
        bookings_recent = _count_actions(
            conn,
            action_types=(BOOKING_ACTION_TYPE,),
            cutoff_ts=cutoff,
        )
        first_payment_ts, last_payment_ts = _first_last_payment_ts(conn)
        payment_sources = _payment_source_breakdown(conn)

    return RevenueStatus(
        as_of_utc=as_of.isoformat(),
        window_days=window_days,
        payment_amount_usd=payment_amount,
        booking_amount_usd=booking_amount,
        payments_total=int(payments_total),
        payments_recent=int(payments_recent),
        bookings_total=int(bookings_total),
        bookings_recent=int(bookings_recent),
        recognized_revenue_usd=float(payments_total) * payment_amount,
        booked_pipeline_revenue_usd=float(bookings_total) * booking_amount,
        first_payment_ts=first_payment_ts,
        last_payment_ts=last_payment_ts,
        payment_sources=payment_sources,
    )


def _float_env(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def main() -> None:
    parser = argparse.ArgumentParser(description="AEO Autopilot recognized revenue snapshot (local SQLite).")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy_live.sqlite3", help="Path to sqlite DB.")
    parser.add_argument("--days", type=int, default=30, help="Window for recent counts.")
    parser.add_argument(
        "--payment-amount-usd",
        type=float,
        default=_float_env("AEO_SETUP_PRICE_USD", 249.0),
        help="Per-payment recognized revenue amount.",
    )
    parser.add_argument(
        "--booking-amount-usd",
        type=float,
        default=_float_env("AEO_BOOKING_VALUE_USD", _float_env("AEO_SETUP_PRICE_USD", 249.0)),
        help="Per-booking pipeline value amount.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of human-readable output.")
    args = parser.parse_args()

    status = load_revenue_status(
        sqlite_path=Path(args.sqlite),
        days=int(args.days),
        payment_amount_usd=float(args.payment_amount_usd),
        booking_amount_usd=float(args.booking_amount_usd),
    )

    if args.json:
        print(json.dumps(asdict(status), indent=2, sort_keys=True))
        return

    print("AEO Autopilot Revenue Status")
    print(f"As-of (UTC): {status.as_of_utc}")
    print(
        "Recognized revenue: "
        f"${status.recognized_revenue_usd:,.2f} "
        f"(payments={status.payments_total} total, {status.payments_recent} in last {status.window_days}d @ ${status.payment_amount_usd:,.2f})"
    )
    print(
        "Booked pipeline value: "
        f"${status.booked_pipeline_revenue_usd:,.2f} "
        f"(bookings={status.bookings_total} total, {status.bookings_recent} in last {status.window_days}d @ ${status.booking_amount_usd:,.2f})"
    )
    print(f"First payment ts: {status.first_payment_ts or 'n/a'}")
    print(f"Last payment ts: {status.last_payment_ts or 'n/a'}")
    if status.payment_sources:
        sources = ", ".join([f"{k}={v}" for k, v in status.payment_sources.items()])
    else:
        sources = "none"
    print(f"Payment sources: {sources}")


if __name__ == "__main__":
    main()
