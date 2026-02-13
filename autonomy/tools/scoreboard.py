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
    email_sent_total: int
    email_sent_recent: int
    opt_out_total: int
    last_email_ts: str


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

        email_sent_total = _count(
            cur,
            "SELECT COUNT(1) FROM messages WHERE channel='email' AND status='sent'",
        )
        email_sent_recent = _count(
            cur,
            "SELECT COUNT(1) FROM messages WHERE channel='email' AND status='sent' AND ts >= ?",
            (cutoff,),
        )
        last_email_ts = _scalar(
            cur,
            "SELECT MAX(ts) FROM messages WHERE channel='email' AND status='sent'",
        )

        opt_out_total = _count(cur, "SELECT COUNT(1) FROM opt_outs")

    return Scoreboard(
        leads_total=leads_total,
        leads_new=leads_new,
        leads_contacted=leads_contacted,
        email_sent_total=email_sent_total,
        email_sent_recent=email_sent_recent,
        opt_out_total=opt_out_total,
        last_email_ts=last_email_ts,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="CallCatcher Ops outreach scoreboard (local).")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy.sqlite3", help="Path to sqlite DB.")
    parser.add_argument("--days", type=int, default=7, help="Window for recent metrics.")
    args = parser.parse_args()

    board = load_scoreboard(Path(args.sqlite), days=int(args.days))

    print("CallCatcher Ops Scoreboard")
    print(f"As-of (UTC): {datetime.now(UTC).replace(microsecond=0).isoformat()}")
    print("")
    print(f"Leads: {board.leads_total} total | {board.leads_new} new | {board.leads_contacted} contacted")
    print(
        f"Email sent: {board.email_sent_total} total | {board.email_sent_recent} in last {int(args.days)} days | last sent: {board.last_email_ts or 'n/a'}"
    )
    print(f"Opt-outs recorded: {board.opt_out_total}")


if __name__ == "__main__":
    main()

