#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


UTC = timezone.utc

# Keep in sync with outreach policy defaults; this is used only for reporting,
# not for suppression (suppression lives in the outreach engine config/policy).
ROLE_LOCAL_PARTS = {
    "info",
    "contact",
    "hello",
    "office",
    "support",
    "sales",
    "service",
    "team",
    "admin",
    "appointments",
    "booking",
    "inquiries",
}


@dataclass(frozen=True)
class CallListRow:
    company: str
    service: str
    city: str
    state: str
    phone: str
    website: str
    contact_name: str
    email: str
    email_method: str
    lead_status: str
    score: int
    source: str
    role_inbox: str
    last_email_ts: str
    email_sent_count: int
    opted_out: str
    call_status: str = ""
    call_attempted_at: str = ""
    call_outcome: str = ""
    baseline_yes: str = ""
    baseline_call_time: str = ""
    pilot_yes: str = ""
    notes: str = ""


def _email_local_part(email: str) -> str:
    return (email or "").strip().lower().split("@", 1)[0]


def _truthy_str(value: object) -> str:
    return "yes" if bool(value) else "no"


def _load_website_map(csv_path: Path | None) -> dict[str, str]:
    if not csv_path:
        return {}
    if not csv_path.exists():
        return {}

    website_by_email: dict[str, str] = {}
    try:
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = (row.get("email") or "").strip().lower()
                website = (row.get("website") or "").strip()
                if email and website:
                    website_by_email[email] = website
    except Exception:
        return {}

    return website_by_email


def generate_call_list(
    *,
    sqlite_path: Path,
    services: list[str],
    limit: int,
    require_phone: bool = True,
    include_opt_outs: bool = False,
    source_csv: Path | None = None,
) -> list[CallListRow]:
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite DB: {sqlite_path}")

    website_by_email = _load_website_map(source_csv)
    services_norm = [s.strip().lower() for s in services if s.strip()]

    clauses: list[str] = []
    params: list[object] = []
    if services_norm:
        placeholders = ",".join(["?"] * len(services_norm))
        clauses.append(f"LOWER(COALESCE(service,'')) IN ({placeholders})")
        params.extend(services_norm)
    if require_phone:
        clauses.append("TRIM(COALESCE(phone,'')) <> ''")
    if not include_opt_outs:
        clauses.append("NOT EXISTS (SELECT 1 FROM opt_outs o WHERE o.email = leads.email)")

    where_sql = ""
    if clauses:
        where_sql = "WHERE " + " AND ".join(clauses)

    sql = f"""
        SELECT
            id,
            COALESCE(company,'') AS company,
            COALESCE(service,'') AS service,
            COALESCE(city,'') AS city,
            COALESCE(state,'') AS state,
            COALESCE(phone,'') AS phone,
            COALESCE(name,'') AS contact_name,
            COALESCE(email,'') AS email,
            COALESCE(email_method,'unknown') AS email_method,
            COALESCE(status,'') AS lead_status,
            COALESCE(score,0) AS score,
            COALESCE(source,'') AS source,
            COALESCE((
                SELECT MAX(ts)
                FROM messages m
                WHERE m.lead_id = leads.id
                  AND m.channel = 'email'
                  AND m.status = 'sent'
            ), '') AS last_email_ts,
            COALESCE((
                SELECT COUNT(1)
                FROM messages m
                WHERE m.lead_id = leads.id
                  AND m.channel = 'email'
                  AND m.status = 'sent'
            ), 0) AS email_sent_count,
            CASE WHEN EXISTS (SELECT 1 FROM opt_outs o WHERE o.email = leads.email)
                 THEN 1 ELSE 0 END AS opted_out
        FROM leads
        {where_sql}
        ORDER BY
            CASE COALESCE(status,'')
                WHEN 'new' THEN 0
                WHEN 'contacted' THEN 1
                WHEN 'replied' THEN 2
                WHEN 'bounced' THEN 3
                ELSE 9
            END,
            score DESC,
            updated_at DESC
        LIMIT ?
    """
    params.append(int(limit))

    rows: list[CallListRow] = []
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        for r in cur.execute(sql, tuple(params)).fetchall():
            email = str(r["email"] or "")
            local = _email_local_part(email)
            rows.append(
                CallListRow(
                    company=str(r["company"] or ""),
                    service=str(r["service"] or ""),
                    city=str(r["city"] or ""),
                    state=str(r["state"] or ""),
                    phone=str(r["phone"] or ""),
                    website=website_by_email.get(email.strip().lower(), ""),
                    contact_name=str(r["contact_name"] or ""),
                    email=email,
                    email_method=str(r["email_method"] or "unknown"),
                    lead_status=str(r["lead_status"] or ""),
                    score=int(r["score"] or 0),
                    source=str(r["source"] or ""),
                    role_inbox=_truthy_str(local in ROLE_LOCAL_PARTS),
                    last_email_ts=str(r["last_email_ts"] or ""),
                    email_sent_count=int(r["email_sent_count"] or 0),
                    opted_out=_truthy_str(int(r["opted_out"] or 0) > 0),
                )
            )

    return rows


def write_call_list(path: Path, rows: list[CallListRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(CallListRow.__dataclass_fields__.keys()))
        writer.writeheader()
        for r in rows:
            writer.writerow(r.__dict__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a phone-first call list from the outreach SQLite DB.")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy_live.sqlite3", help="Path to sqlite DB.")
    parser.add_argument(
        "--services",
        default="med spa",
        help="Comma-separated services to include (exact match on lead.service, lowercased).",
    )
    parser.add_argument("--limit", type=int, default=200, help="Max rows to output.")
    parser.add_argument("--include-opt-outs", action="store_true", help="Include leads that opted out (not recommended).")
    parser.add_argument("--no-require-phone", action="store_true", help="Include leads without phone numbers.")
    parser.add_argument(
        "--source-csv",
        default="autonomy/state/leads_callcatcherops_real.csv",
        help="Optional CSV to pull website URLs from (matched by email).",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output CSV path. Default: autonomy/state/call_list_<services>_<YYYY-MM-DD>.csv",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    services = [s.strip() for s in (args.services or "").split(",") if s.strip()]
    today = datetime.now(UTC).date().isoformat()
    services_slug = "-".join([s.lower().replace(" ", "_") for s in services]) or "all"
    output = args.output or f"autonomy/state/call_list_{services_slug}_{today}.csv"

    rows = generate_call_list(
        sqlite_path=sqlite_path,
        services=services,
        limit=int(args.limit),
        require_phone=not bool(args.no_require_phone),
        include_opt_outs=bool(args.include_opt_outs),
        source_csv=Path(args.source_csv) if args.source_csv else None,
    )
    write_call_list(Path(output), rows)
    print(f"Wrote {len(rows)} rows -> {output}")


if __name__ == "__main__":
    main()
