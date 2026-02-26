#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from autonomy.utils import UTC, now_utc_iso

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
    priority_score: int = 0
    priority_reasons: str = ""
    last_touch_ts: str = ""
    recent_spoke: int = 0
    recent_voicemail: int = 0
    recent_no_answer: int = 0
    recent_failed: int = 0
    recent_sms_interested: int = 0
    recent_sms_replied: int = 0


@dataclass
class _IntentSignals:
    last_action_ts: datetime | None = None
    spoke: int = 0
    voicemail: int = 0
    no_answer: int = 0
    failed: int = 0
    sms_interested: int = 0
    sms_replied: int = 0


def _default_sqlite_path() -> Path:
    for candidate in (
        Path("autonomy/state/autonomy_live.sqlite3"),
        Path("autonomy/state/autonomy.sqlite3"),
    ):
        if candidate.exists():
            return candidate
    return Path("autonomy/state/autonomy_live.sqlite3")


def _email_local_part(email: str) -> str:
    return (email or "").strip().lower().split("@", 1)[0]


def _truthy_str(value: object) -> str:
    return "yes" if bool(value) else "no"


def _parse_ts(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed
    except Exception:
        return None


def _iso_or_empty(ts: datetime | None) -> str:
    return ts.isoformat() if ts is not None else ""


def _iter_chunks(items: list[str], size: int) -> list[list[str]]:
    if size <= 0:
        return [items]
    return [items[idx : idx + size] for idx in range(0, len(items), size)]


def _status_rank(status: str) -> int:
    normalized = (status or "").strip().lower()
    if normalized == "replied":
        return 0
    if normalized == "contacted":
        return 1
    if normalized == "new":
        return 2
    if normalized == "bounced":
        return 3
    return 9


def _status_bonus(status: str) -> int:
    normalized = (status or "").strip().lower()
    if normalized == "replied":
        return 35
    if normalized == "contacted":
        return 15
    if normalized == "new":
        return 5
    if normalized == "bounced":
        return -60
    return 0


def _load_intent_signals(
    *,
    conn: sqlite3.Connection,
    lead_ids: list[str],
    call_signal_days: int,
    sms_signal_days: int,
) -> dict[str, _IntentSignals]:
    if not lead_ids:
        return {}

    by_lead: dict[str, _IntentSignals] = {}
    call_cutoff = datetime.now(UTC) - timedelta(days=max(1, int(call_signal_days)))
    sms_cutoff = datetime.now(UTC) - timedelta(days=max(1, int(sms_signal_days)))

    for chunk in _iter_chunks(lead_ids, 500):
        placeholders = ",".join(["?"] * len(chunk))
        rows = conn.execute(
            f"""
            SELECT ts, action_type, payload_json
            FROM actions
            WHERE action_type IN ('call.attempt', 'sms.inbound')
              AND LOWER(COALESCE(json_extract(payload_json, '$.lead_id'), '')) IN ({placeholders})
            """,
            tuple(chunk),
        ).fetchall()

        for row in rows:
            ts = _parse_ts(str(row["ts"] or ""))
            if ts is None:
                continue

            payload_raw = row["payload_json"] or "{}"
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}

            lead_id = str(payload.get("lead_id") or "").strip().lower()
            if not lead_id:
                continue
            signals = by_lead.setdefault(lead_id, _IntentSignals())
            if signals.last_action_ts is None or ts > signals.last_action_ts:
                signals.last_action_ts = ts

            action_type = str(row["action_type"] or "")
            if action_type == "call.attempt":
                if ts < call_cutoff:
                    continue
                outcome = str(payload.get("outcome") or "").strip().lower()
                if outcome == "spoke":
                    signals.spoke += 1
                elif outcome == "voicemail":
                    signals.voicemail += 1
                elif outcome == "no_answer":
                    signals.no_answer += 1
                elif outcome == "failed":
                    signals.failed += 1
            elif action_type == "sms.inbound":
                if ts < sms_cutoff:
                    continue
                classification = str(payload.get("classification") or "").strip().lower()
                if classification == "interested":
                    signals.sms_interested += 1
                elif classification == "replied":
                    signals.sms_replied += 1

    return by_lead


def _score_priority(
    *,
    base_score: int,
    lead_status: str,
    role_inbox: str,
    opted_out: str,
    email_sent_count: int,
    last_email_ts: str,
    signals: _IntentSignals | None,
) -> tuple[int, str, str]:
    score = int(base_score)
    reasons: list[str] = [f"base={int(base_score)}"]

    status_delta = _status_bonus(lead_status)
    score += status_delta
    if status_delta:
        reasons.append(f"status={status_delta:+d}")

    if opted_out == "yes":
        score -= 250
        reasons.append("optout=-250")
    if role_inbox == "yes":
        score -= 10
        reasons.append("role_inbox=-10")

    if email_sent_count == 0:
        score += 4
        reasons.append("email_fresh=+4")
    elif email_sent_count >= 3:
        email_penalty = min(10, (int(email_sent_count) - 2) * 2)
        score -= email_penalty
        reasons.append(f"email_fatigue=-{email_penalty}")

    last_touch: datetime | None = _parse_ts(last_email_ts)
    if signals is not None:
        if signals.last_action_ts is not None and (last_touch is None or signals.last_action_ts > last_touch):
            last_touch = signals.last_action_ts

        if signals.spoke > 0:
            spoke_bonus = 20 + min(10, signals.spoke * 2)
            score += spoke_bonus
            reasons.append(f"spoke=+{spoke_bonus}")
        if signals.voicemail > 0:
            vm_bonus = min(10, signals.voicemail * 3)
            score += vm_bonus
            reasons.append(f"voicemail=+{vm_bonus}")
        if signals.no_answer > 0:
            na_penalty = min(12, signals.no_answer * 4)
            score -= na_penalty
            reasons.append(f"no_answer=-{na_penalty}")
        if signals.failed > 0:
            fail_penalty = min(18, signals.failed * 6)
            score -= fail_penalty
            reasons.append(f"failed=-{fail_penalty}")
        if signals.sms_interested > 0:
            sms_interest_bonus = min(36, signals.sms_interested * 12)
            score += sms_interest_bonus
            reasons.append(f"sms_interested=+{sms_interest_bonus}")
        if signals.sms_replied > 0:
            sms_replied_bonus = min(18, signals.sms_replied * 6)
            score += sms_replied_bonus
            reasons.append(f"sms_replied=+{sms_replied_bonus}")

    if last_touch is not None:
        age_hours = (datetime.now(UTC) - last_touch).total_seconds() / 3600.0
        if age_hours <= 2:
            score += 12
            reasons.append("fresh_2h=+12")
        elif age_hours <= 24:
            score += 8
            reasons.append("fresh_24h=+8")
        elif age_hours <= 72:
            score += 4
            reasons.append("fresh_72h=+4")
        elif age_hours > 24 * 7:
            score -= 6
            reasons.append("stale_7d=-6")

    return score, ";".join(reasons), _iso_or_empty(last_touch)


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
    statuses: list[str] | None = None,
    min_score: int = 0,
    exclude_role_inbox: bool = False,
    enrichment_enabled: bool = True,
    call_signal_days: int = 14,
    sms_signal_days: int = 30,
) -> list[CallListRow]:
    if not sqlite_path.exists():
        raise SystemExit(f"Missing sqlite DB: {sqlite_path}")

    website_by_email = _load_website_map(source_csv)
    services_norm = [s.strip().lower() for s in services if s.strip()]
    statuses_norm = [s.strip().lower() for s in (statuses or []) if s.strip()]

    clauses: list[str] = []
    params: list[object] = []
    if services_norm:
        placeholders = ",".join(["?"] * len(services_norm))
        clauses.append(f"LOWER(COALESCE(service,'')) IN ({placeholders})")
        params.extend(services_norm)
    if statuses_norm:
        placeholders = ",".join(["?"] * len(statuses_norm))
        clauses.append(f"LOWER(COALESCE(status,'')) IN ({placeholders})")
        params.extend(statuses_norm)
    if int(min_score) > 0:
        clauses.append("COALESCE(score, 0) >= ?")
        params.append(int(min_score))
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
            COALESCE(updated_at,'') AS updated_at,
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
                WHEN 'replied' THEN 0
                WHEN 'contacted' THEN 1
                WHEN 'new' THEN 2
                WHEN 'bounced' THEN 3
                ELSE 9
            END,
            score DESC,
            email_sent_count ASC,
            updated_at DESC
        LIMIT ?
    """
    query_limit = int(limit)
    if exclude_role_inbox:
        query_limit = max(int(limit), int(limit) * 5)
    params.append(query_limit)

    rows: list[CallListRow] = []
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        fetched = cur.execute(sql, tuple(params)).fetchall()
        lead_ids = [str(r["id"] or "").strip().lower() for r in fetched if str(r["id"] or "").strip()]
        signals_by_lead = (
            _load_intent_signals(
                conn=conn,
                lead_ids=lead_ids,
                call_signal_days=max(1, int(call_signal_days)),
                sms_signal_days=max(1, int(sms_signal_days)),
            )
            if enrichment_enabled
            else {}
        )

        ranked_rows: list[tuple[tuple[object, ...], CallListRow]] = []
        for r in fetched:
            email = str(r["email"] or "")
            local = _email_local_part(email)
            role_inbox = _truthy_str(local in ROLE_LOCAL_PARTS)
            if exclude_role_inbox and role_inbox == "yes":
                continue

            lead_id = str(r["id"] or "").strip().lower()
            lead_status = str(r["lead_status"] or "")
            score = int(r["score"] or 0)
            email_sent_count = int(r["email_sent_count"] or 0)
            opted_out = _truthy_str(int(r["opted_out"] or 0) > 0)
            signal = signals_by_lead.get(lead_id)
            if enrichment_enabled:
                priority_score, priority_reasons, last_touch_ts = _score_priority(
                    base_score=score,
                    lead_status=lead_status,
                    role_inbox=role_inbox,
                    opted_out=opted_out,
                    email_sent_count=email_sent_count,
                    last_email_ts=str(r["last_email_ts"] or ""),
                    signals=signal,
                )
            else:
                priority_score = int(score)
                priority_reasons = "enrichment_disabled"
                last_touch_ts = str(r["last_email_ts"] or "")
            row_obj = CallListRow(
                company=str(r["company"] or ""),
                service=str(r["service"] or ""),
                city=str(r["city"] or ""),
                state=str(r["state"] or ""),
                phone=str(r["phone"] or ""),
                website=website_by_email.get(email.strip().lower(), ""),
                contact_name=str(r["contact_name"] or ""),
                email=email,
                email_method=str(r["email_method"] or "unknown"),
                lead_status=lead_status,
                score=score,
                source=str(r["source"] or ""),
                role_inbox=role_inbox,
                last_email_ts=str(r["last_email_ts"] or ""),
                email_sent_count=email_sent_count,
                opted_out=opted_out,
                priority_score=int(priority_score),
                priority_reasons=priority_reasons,
                last_touch_ts=last_touch_ts,
                recent_spoke=int(signal.spoke if signal is not None else 0),
                recent_voicemail=int(signal.voicemail if signal is not None else 0),
                recent_no_answer=int(signal.no_answer if signal is not None else 0),
                recent_failed=int(signal.failed if signal is not None else 0),
                recent_sms_interested=int(signal.sms_interested if signal is not None else 0),
                recent_sms_replied=int(signal.sms_replied if signal is not None else 0),
            )
            updated_at_dt = _parse_ts(str(r["updated_at"] or ""))
            if enrichment_enabled:
                rank_key = (
                    -int(row_obj.priority_score),
                    _status_rank(row_obj.lead_status),
                    int(row_obj.email_sent_count),
                    -int(row_obj.score),
                    -(float(updated_at_dt.timestamp()) if updated_at_dt else 0.0),
                    row_obj.company.lower(),
                )
            else:
                rank_key = (
                    _status_rank(row_obj.lead_status),
                    -int(row_obj.score),
                    int(row_obj.email_sent_count),
                    -(float(updated_at_dt.timestamp()) if updated_at_dt else 0.0),
                    row_obj.company.lower(),
                )
            ranked_rows.append((rank_key, row_obj))

        ranked_rows.sort(key=lambda item: item[0])
        rows = [item[1] for item in ranked_rows[: int(limit)]]

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
    parser.add_argument("--sqlite", default=str(_default_sqlite_path()), help="Path to sqlite DB.")
    parser.add_argument(
        "--services",
        default="med spa",
        help="Comma-separated services to include (exact match on lead.service, lowercased).",
    )
    parser.add_argument(
        "--statuses",
        default="",
        help="Optional comma-separated lead statuses to include (e.g. 'new,contacted').",
    )
    parser.add_argument("--min-score", type=int, default=0, help="Optional minimum lead score.")
    parser.add_argument(
        "--no-enrichment",
        action="store_true",
        help="Disable action-derived intent enrichment and dynamic priority scoring.",
    )
    parser.add_argument(
        "--call-signal-days",
        type=int,
        default=14,
        help="Lookback window (days) for call outcomes used in priority scoring.",
    )
    parser.add_argument(
        "--sms-signal-days",
        type=int,
        default=30,
        help="Lookback window (days) for inbound SMS classifications used in priority scoring.",
    )
    parser.add_argument(
        "--exclude-role-inbox",
        action="store_true",
        help="Exclude role inbox local-parts (info@, contact@, support@, etc).",
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
    statuses = [s.strip() for s in (args.statuses or "").split(",") if s.strip()]
    today = datetime.now(UTC).date().isoformat()
    services_slug = "-".join([s.lower().replace(" ", "_") for s in services]) or "all"
    output = args.output or f"autonomy/state/call_list_{services_slug}_{today}.csv"

    rows = generate_call_list(
        sqlite_path=sqlite_path,
        services=services,
        statuses=statuses or None,
        min_score=max(0, int(args.min_score)),
        exclude_role_inbox=bool(args.exclude_role_inbox),
        enrichment_enabled=not bool(args.no_enrichment),
        call_signal_days=max(1, int(args.call_signal_days)),
        sms_signal_days=max(1, int(args.sms_signal_days)),
        limit=int(args.limit),
        require_phone=not bool(args.no_require_phone),
        include_opt_outs=bool(args.include_opt_outs),
        source_csv=Path(args.source_csv) if args.source_csv else None,
    )
    write_call_list(Path(output), rows)
    print(f"As-of (UTC): {now_utc_iso()}")
    print(f"Wrote {len(rows)} rows -> {output}")


if __name__ == "__main__":
    main()
