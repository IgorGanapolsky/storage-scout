#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
BOOKING_ACTION = "conversion.booking"
PAYMENT_ACTION = "conversion.payment"
WARM_CLOSE_KIND = "warm_close_email"
WARM_CLOSE_STEP = 90
DEFAULT_STATUSES = ("interested", "replied")


@dataclass(frozen=True)
class WarmCloseFunnelEval:
    as_of_utc: str
    window_days: int
    statuses: tuple[str, ...]
    cohort_leads: int
    warm_close_sent_leads: int
    warm_close_missing_leads: int
    warm_close_sent_via_step90_leads: int
    warm_close_sent_via_kind_leads: int
    booked_after_warm_close_leads: int
    paid_after_warm_close_leads: int
    converted_after_warm_close_leads: int
    warm_close_send_rate: float
    booking_rate_from_warm_close: float
    payment_rate_from_warm_close: float
    conversion_rate_from_warm_close: float


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(1) FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return bool(int((row[0] or 0) if row else 0))


def _load_cohort_leads(conn: sqlite3.Connection, statuses: tuple[str, ...]) -> set[str]:
    if not _table_exists(conn, "leads"):
        return set()
    placeholders = ",".join(["?"] * len(statuses))
    rows = conn.execute(
        f"""
        SELECT LOWER(COALESCE(id, '')) AS lead_id
        FROM leads
        WHERE LOWER(COALESCE(status, '')) IN ({placeholders})
        """,
        tuple(statuses),
    ).fetchall()
    return {str(row[0] or "") for row in rows if str(row[0] or "")}


def _load_warm_sent_step_ts(conn: sqlite3.Connection, step: int) -> dict[str, str]:
    if not _table_exists(conn, "messages"):
        return {}
    rows = conn.execute(
        """
        SELECT LOWER(COALESCE(lead_id, '')) AS lead_id, MAX(ts) AS sent_ts
        FROM messages
        WHERE channel='email' AND status='sent' AND step=?
        GROUP BY LOWER(COALESCE(lead_id, ''))
        """,
        (int(step),),
    ).fetchall()
    return {str(row[0] or ""): str(row[1] or "") for row in rows if str(row[0] or "") and str(row[1] or "")}


def _load_warm_sent_kind_ts(conn: sqlite3.Connection, kind: str) -> dict[str, str]:
    if not _table_exists(conn, "actions"):
        return {}
    rows = conn.execute(
        """
        SELECT
          LOWER(COALESCE(json_extract(payload_json, '$.lead_id'), '')) AS lead_id,
          MAX(ts) AS sent_ts
        FROM actions
        WHERE action_type='email.send'
          AND LOWER(COALESCE(json_extract(payload_json, '$.kind'), '')) = LOWER(?)
          AND LOWER(COALESCE(json_extract(payload_json, '$.status'), 'sent')) = 'sent'
        GROUP BY LOWER(COALESCE(json_extract(payload_json, '$.lead_id'), ''))
        """,
        (str(kind),),
    ).fetchall()
    return {str(row[0] or ""): str(row[1] or "") for row in rows if str(row[0] or "") and str(row[1] or "")}


def _load_first_conversion_ts(conn: sqlite3.Connection, action_type: str) -> dict[str, str]:
    if not _table_exists(conn, "actions"):
        return {}
    rows = conn.execute(
        """
        SELECT
          LOWER(COALESCE(json_extract(payload_json, '$.lead_id'), '')) AS lead_id,
          MIN(ts) AS first_ts
        FROM actions
        WHERE action_type=?
        GROUP BY LOWER(COALESCE(json_extract(payload_json, '$.lead_id'), ''))
        """,
        (str(action_type),),
    ).fetchall()
    return {str(row[0] or ""): str(row[1] or "") for row in rows if str(row[0] or "") and str(row[1] or "")}


def load_warm_close_funnel_eval(
    *,
    sqlite_path: Path,
    days: int = 30,
    statuses: tuple[str, ...] = DEFAULT_STATUSES,
    warm_close_step: int = WARM_CLOSE_STEP,
    warm_close_kind: str = WARM_CLOSE_KIND,
) -> WarmCloseFunnelEval:
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite DB: {sqlite_path}")

    window_days = max(1, int(days))
    as_of = datetime.now(UTC).replace(microsecond=0).isoformat()
    status_set = tuple(sorted({str(s or "").strip().lower() for s in statuses if str(s or "").strip()}))
    if not status_set:
        status_set = DEFAULT_STATUSES

    with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
        cohort = _load_cohort_leads(conn, status_set)
        step_ts = _load_warm_sent_step_ts(conn, warm_close_step)
        kind_ts = _load_warm_sent_kind_ts(conn, warm_close_kind)
        booking_first_ts = _load_first_conversion_ts(conn, BOOKING_ACTION)
        payment_first_ts = _load_first_conversion_ts(conn, PAYMENT_ACTION)

    warm_sent_leads: set[str] = set()
    booked_after = 0
    paid_after = 0
    converted_after = 0
    step_sent_count = 0
    kind_sent_count = 0

    for lead_id in cohort:
        has_step = lead_id in step_ts
        has_kind = lead_id in kind_ts
        if has_step:
            step_sent_count += 1
        if has_kind:
            kind_sent_count += 1

        warm_ts = ""
        if has_step and has_kind:
            warm_ts = max(str(step_ts[lead_id]), str(kind_ts[lead_id]))
        elif has_step:
            warm_ts = str(step_ts[lead_id])
        elif has_kind:
            warm_ts = str(kind_ts[lead_id])

        if not warm_ts:
            continue

        warm_sent_leads.add(lead_id)
        booked = bool(lead_id in booking_first_ts and str(booking_first_ts[lead_id]) >= warm_ts)
        paid = bool(lead_id in payment_first_ts and str(payment_first_ts[lead_id]) >= warm_ts)
        if booked:
            booked_after += 1
        if paid:
            paid_after += 1
        if booked or paid:
            converted_after += 1

    cohort_count = int(len(cohort))
    sent_count = int(len(warm_sent_leads))
    missing_count = max(0, cohort_count - sent_count)
    send_rate = float(sent_count) / float(cohort_count) if cohort_count else 0.0
    booking_rate = float(booked_after) / float(sent_count) if sent_count else 0.0
    payment_rate = float(paid_after) / float(sent_count) if sent_count else 0.0
    conversion_rate = float(converted_after) / float(sent_count) if sent_count else 0.0

    return WarmCloseFunnelEval(
        as_of_utc=as_of,
        window_days=window_days,
        statuses=tuple(status_set),
        cohort_leads=cohort_count,
        warm_close_sent_leads=sent_count,
        warm_close_missing_leads=missing_count,
        warm_close_sent_via_step90_leads=int(step_sent_count),
        warm_close_sent_via_kind_leads=int(kind_sent_count),
        booked_after_warm_close_leads=int(booked_after),
        paid_after_warm_close_leads=int(paid_after),
        converted_after_warm_close_leads=int(converted_after),
        warm_close_send_rate=send_rate,
        booking_rate_from_warm_close=booking_rate,
        payment_rate_from_warm_close=payment_rate,
        conversion_rate_from_warm_close=conversion_rate,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm-close funnel eval (interested/replied -> warm_close_email -> booking/payment).")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy_live.sqlite3", help="Path to sqlite DB.")
    parser.add_argument("--days", type=int, default=30, help="Window for eval metadata.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    result = load_warm_close_funnel_eval(
        sqlite_path=Path(args.sqlite),
        days=int(args.days),
    )
    if args.json:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return

    print("Warm-Close Funnel Eval")
    print(f"As-of (UTC): {result.as_of_utc}")
    print(f"Cohort ({','.join(result.statuses)}): {result.cohort_leads}")
    print(f"Warm-close sent: {result.warm_close_sent_leads} ({result.warm_close_send_rate:.0%})")
    print(f"Missing warm-close: {result.warm_close_missing_leads}")
    print(
        "Post-send conversion: "
        f"booked={result.booked_after_warm_close_leads} ({result.booking_rate_from_warm_close:.0%}), "
        f"paid={result.paid_after_warm_close_leads} ({result.payment_rate_from_warm_close:.0%}), "
        f"either={result.converted_after_warm_close_leads} ({result.conversion_rate_from_warm_close:.0%})"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
