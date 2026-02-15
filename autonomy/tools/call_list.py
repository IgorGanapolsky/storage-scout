#!/usr/bin/env python3
"""
Call list exporter for CallCatcher Ops outreach.

Usage examples:
  python3 autonomy/tools/call_list.py --service Dentist --status contacted
  python3 autonomy/tools/call_list.py --service Dentist --status contacted --format md
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence


UTC = timezone.utc


@dataclass(frozen=True)
class LeadRow:
    company: str
    email: str
    phone: str
    city: str
    state: str
    service: str
    status: str
    last_email_ts: str


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _default_sqlite_path() -> str:
    for candidate in (
        Path("autonomy/state/autonomy_live.sqlite3"),
        Path("autonomy/state/autonomy.sqlite3"),
    ):
        if candidate.exists():
            return str(candidate)
    return "autonomy/state/autonomy_live.sqlite3"


def _split_csv_arg(raw: str) -> List[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


def _iter_placeholders(n: int) -> str:
    return ", ".join(["?"] * n)


def load_call_list(
    *,
    sqlite_path: Path,
    services: Sequence[str],
    statuses: Sequence[str],
    only_with_phone: bool,
    limit: int,
) -> List[LeadRow]:
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite DB: {sqlite_path}")

    where: List[str] = []
    params: List[object] = []

    if services:
        where.append(f"l.service IN ({_iter_placeholders(len(services))})")
        params.extend(list(services))

    if statuses:
        where.append(f"l.status IN ({_iter_placeholders(len(statuses))})")
        params.extend(list(statuses))

    if only_with_phone:
        where.append("COALESCE(TRIM(l.phone), '') <> ''")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    sql = f"""
    SELECT
      COALESCE(l.company, '') AS company,
      COALESCE(l.email, '') AS email,
      COALESCE(l.phone, '') AS phone,
      COALESCE(l.city, '') AS city,
      COALESCE(l.state, '') AS state,
      COALESCE(l.service, '') AS service,
      COALESCE(l.status, '') AS status,
      COALESCE(MAX(CASE WHEN m.channel='email' AND m.status='sent' THEN m.ts END), '') AS last_email_ts
    FROM leads l
    LEFT JOIN messages m ON m.lead_id = l.id
    {where_sql}
    GROUP BY l.id
    ORDER BY last_email_ts DESC, COALESCE(l.updated_at, '') DESC, company ASC
    LIMIT ?
    """

    rows: List[LeadRow] = []
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for r in cur.execute(sql, tuple(params) + (int(limit),)):
            rows.append(
                LeadRow(
                    company=str(r["company"] or "").strip(),
                    email=str(r["email"] or "").strip(),
                    phone=str(r["phone"] or "").strip(),
                    city=str(r["city"] or "").strip(),
                    state=str(r["state"] or "").strip(),
                    service=str(r["service"] or "").strip(),
                    status=str(r["status"] or "").strip(),
                    last_email_ts=str(r["last_email_ts"] or "").strip(),
                )
            )
    return rows


def _print_csv(rows: Iterable[LeadRow]) -> None:
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["company", "phone", "email", "city", "state", "service", "status", "last_email_ts"])
    for r in rows:
        w.writerow([r.company, r.phone, r.email, r.city, r.state, r.service, r.status, r.last_email_ts])


def _print_md(rows: Sequence[LeadRow]) -> None:
    headers = ["company", "phone", "email", "city", "state", "service", "status", "last_email_ts"]
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows:
        print(
            "| "
            + " | ".join(
                [
                    r.company or "",
                    r.phone or "",
                    r.email or "",
                    r.city or "",
                    r.state or "",
                    r.service or "",
                    r.status or "",
                    r.last_email_ts or "",
                ]
            )
            + " |"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a call list from the outreach sqlite DB.")
    parser.add_argument("--sqlite", default=_default_sqlite_path(), help="Path to sqlite DB (default: live if present).")
    parser.add_argument(
        "--service",
        default="",
        help="Service filter (exact match). For multiple services: comma-separated, e.g. 'Dentist,Plumber'.",
    )
    parser.add_argument(
        "--status",
        default="contacted",
        help="Status filter (exact match). For multiple: comma-separated. Default: contacted.",
    )
    parser.add_argument("--only-with-phone", action="store_true", help="Only include leads that have a phone number.")
    parser.add_argument("--limit", type=int, default=250, help="Max rows to output.")
    parser.add_argument("--format", choices=["csv", "md"], default="csv", help="Output format.")
    args = parser.parse_args()

    rows = load_call_list(
        sqlite_path=Path(args.sqlite),
        services=_split_csv_arg(args.service),
        statuses=_split_csv_arg(args.status),
        only_with_phone=bool(args.only_with_phone),
        limit=int(args.limit),
    )

    if args.format == "md":
        _print_md(rows)
    else:
        _print_csv(rows)

    # stderr summary for quick sanity.
    sys.stderr.write(f"As-of (UTC): {_now_utc_iso()}\n")
    sys.stderr.write(f"Rows: {len(rows)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

