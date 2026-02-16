#!/usr/bin/env python3
import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

UTC = timezone.utc


@dataclass
class Scoreboard:
    leads_total: int
    leads_new: int
    leads_contacted: int
    leads_replied: int
    leads_bounced: int
    leads_other: int
    email_sent_total: int
    email_sent_recent: int
    emailed_leads_recent: int
    bounced_leads_recent: int
    bounce_rate_recent: float
    opt_out_total: int
    last_email_ts: str
    call_attempts_total: int
    call_attempts_recent: int
    call_booked_total: int
    call_booked_recent: int
    last_call_ts: str


def _count(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> int:
    row = cur.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _scalar(cur: sqlite3.Cursor, sql: str, params: tuple = ()) -> str:
    row = cur.execute(sql, params).fetchone()
    return str(row[0] or "") if row else ""


def load_scoreboard(sqlite_path: Path, days: int) -> Scoreboard:
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite DB: {sqlite_path}")

    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

    with sqlite3.connect(sqlite_path) as conn:
        cur = conn.cursor()

        leads_total = _count(cur, "SELECT COUNT(1) FROM leads")
        leads_new = _count(cur, "SELECT COUNT(1) FROM leads WHERE status='new'")
        leads_contacted = _count(cur, "SELECT COUNT(1) FROM leads WHERE status='contacted'")
        leads_replied = _count(cur, "SELECT COUNT(1) FROM leads WHERE status='replied'")
        leads_bounced = _count(cur, "SELECT COUNT(1) FROM leads WHERE status='bounced'")
        leads_other = _count(
            cur,
            "SELECT COUNT(1) FROM leads WHERE status NOT IN ('new','contacted','replied','bounced')",
        )

        email_sent_total = _count(
            cur,
            "SELECT COUNT(1) FROM messages WHERE channel='email' AND status='sent'",
        )
        email_sent_recent = _count(
            cur,
            "SELECT COUNT(1) FROM messages WHERE channel='email' AND status='sent' AND ts >= ?",
            (cutoff,),
        )
        emailed_leads_recent = _count(
            cur,
            "SELECT COUNT(DISTINCT lead_id) FROM messages WHERE channel='email' AND status='sent' AND ts >= ?",
            (cutoff,),
        )
        bounced_leads_recent = _count(
            cur,
            """
            SELECT COUNT(DISTINCT m.lead_id)
            FROM messages m
            JOIN leads l ON l.id = m.lead_id
            WHERE m.channel='email' AND m.status='sent' AND m.ts >= ?
              AND l.status='bounced'
            """,
            (cutoff,),
        )
        bounce_rate_recent = float(bounced_leads_recent) / float(emailed_leads_recent) if emailed_leads_recent else 0.0
        last_email_ts = _scalar(
            cur,
            "SELECT MAX(ts) FROM messages WHERE channel='email' AND status='sent'",
        )

        opt_out_total = _count(cur, "SELECT COUNT(1) FROM opt_outs")

        call_attempts_total = _count(cur, "SELECT COUNT(1) FROM actions WHERE action_type='call.attempt'")
        call_attempts_recent = _count(
            cur,
            "SELECT COUNT(1) FROM actions WHERE action_type='call.attempt' AND ts >= ?",
            (cutoff,),
        )
        call_booked_total = _count(
            cur,
            """
            SELECT COUNT(1)
            FROM actions
            WHERE action_type='call.attempt'
              AND json_extract(payload_json, '$.outcome') = 'booked'
            """,
        )
        call_booked_recent = _count(
            cur,
            """
            SELECT COUNT(1)
            FROM actions
            WHERE action_type='call.attempt'
              AND ts >= ?
              AND json_extract(payload_json, '$.outcome') = 'booked'
            """,
            (cutoff,),
        )
        last_call_ts = _scalar(cur, "SELECT MAX(ts) FROM actions WHERE action_type='call.attempt'")

    return Scoreboard(
        leads_total=leads_total,
        leads_new=leads_new,
        leads_contacted=leads_contacted,
        leads_replied=leads_replied,
        leads_bounced=leads_bounced,
        leads_other=leads_other,
        email_sent_total=email_sent_total,
        email_sent_recent=email_sent_recent,
        emailed_leads_recent=emailed_leads_recent,
        bounced_leads_recent=bounced_leads_recent,
        bounce_rate_recent=bounce_rate_recent,
        opt_out_total=opt_out_total,
        last_email_ts=last_email_ts,
        call_attempts_total=call_attempts_total,
        call_attempts_recent=call_attempts_recent,
        call_booked_total=call_booked_total,
        call_booked_recent=call_booked_recent,
        last_call_ts=last_call_ts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CallCatcher Ops outreach scoreboard (local).")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy_live.sqlite3", help="Path to sqlite DB.")
    parser.add_argument("--days", type=int, default=7, help="Window for recent metrics.")
    args = parser.parse_args()

    board = load_scoreboard(Path(args.sqlite), days=int(args.days))

    print("CallCatcher Ops Scoreboard")
    print(f"As-of (UTC): {datetime.now(UTC).replace(microsecond=0).isoformat()}")
    print("")
    print(
        "Leads: "
        f"{board.leads_total} total | "
        f"{board.leads_new} new | "
        f"{board.leads_contacted} contacted | "
        f"{board.leads_replied} replied | "
        f"{board.leads_bounced} bounced | "
        f"{board.leads_other} other"
    )
    print(
        f"Email sent: {board.email_sent_total} total | {board.email_sent_recent} in last {int(args.days)} days | last sent: {board.last_email_ts or 'n/a'}"
    )
    print(
        "Deliverability (last "
        f"{int(args.days)} days): "
        f"{board.bounced_leads_recent}/{board.emailed_leads_recent} bounced leads "
        f"({board.bounce_rate_recent:.0%})"
    )
    print(
        "Calls: "
        f"{board.call_attempts_total} total | "
        f"{board.call_attempts_recent} in last {int(args.days)} days | "
        f"booked: {board.call_booked_total} total ({board.call_booked_recent} recent) | "
        f"last call: {board.last_call_ts or 'n/a'}"
    )
    print(f"Opt-outs recorded: {board.opt_out_total}")


if __name__ == "__main__":
    main()
