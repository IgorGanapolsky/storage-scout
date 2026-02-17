#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import smtplib
import sys
import time
import urllib.request
from dataclasses import asdict
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

# Support running as a script (launchd uses absolute paths).
if __package__ is None:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import contextlib

from autonomy.context_store import ContextStore
from autonomy.engine import Engine, load_config
from autonomy.tools.call_list import generate_call_list, write_call_list
from autonomy.tools.fastmail_inbox_sync import (
    InboxSyncResult,
    load_dotenv,
    sync_fastmail_inbox,
)
from autonomy.tools.funnel_watchdog import FunnelWatchdogResult, run_funnel_watchdog
from autonomy.tools.lead_gen_broward import (
    DEFAULT_CATEGORIES,
    build_leads,
    get_api_key,
    load_cities,
    load_existing,
    save_city_index,
    write_leads,
)
from autonomy.tools.revenue_rag import build_revenue_lesson, record_revenue_lesson
from autonomy.tools.scoreboard import load_scoreboard
from autonomy.tools.twilio_autocall import AutoCallResult, run_auto_calls
from autonomy.tools.twilio_interest_nudge import InterestNudgeResult, run_interest_nudges
from autonomy.tools.twilio_inbox_sync import TwilioInboxResult, run_twilio_inbox_sync
from autonomy.tools.twilio_sms import SmsResult, run_sms_followup
from autonomy.utils import UTC, truthy


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _int_env(raw: str | None, default: int) -> int:
    if raw is None:
        return int(default)
    try:
        return int(str(raw).strip() or default)
    except Exception:
        return int(default)


def _float_env(raw: str | None, default: float) -> float:
    if raw is None:
        return float(default)
    try:
        return float(str(raw).strip() or default)
    except Exception:
        return float(default)


def _resolve_store_paths(*, cfg, repo_root: Path) -> tuple[Path, Path]:
    sqlite_raw = Path(cfg.storage["sqlite_path"])
    audit_raw = Path(cfg.storage["audit_log"])
    sqlite_path = sqlite_raw if sqlite_raw.is_absolute() else (repo_root / sqlite_raw).resolve()
    audit_log = audit_raw if audit_raw.is_absolute() else (repo_root / audit_raw).resolve()
    return sqlite_path, audit_log


def _count_actions_since(store: ContextStore, *, action_type: str, since_iso: str) -> int:
    row = store.conn.execute(
        "SELECT COUNT(1) FROM actions WHERE action_type=? AND ts >= ?",
        (str(action_type), str(since_iso)),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _count_actions_today(store: ContextStore, *, action_type: str, paid_only: bool = False) -> int:
    """Count actions from today's UTC window.

    When `paid_only=True`, only count Twilio-originated attempts that have a
    concrete Twilio SID (best-effort proxy for billable channel usage).
    """
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    where: list[str] = ["action_type = ?", "ts >= ?"]
    params: list[object] = [str(action_type), str(today_start)]

    if paid_only and action_type == "call.attempt":
        where.append("agent_id = ?")
        params.append("agent.autocall.twilio.v1")
        where.append("COALESCE(json_extract(payload_json, '$.twilio.sid'), '') <> ''")
    elif paid_only and action_type in {"sms.attempt", "sms.interest_nudge"}:
        where.append("agent_id IN (?, ?)")
        params.extend(["agent.sms.twilio.v1", "agent.sms.twilio.nudge.v1"])
        where.append("COALESCE(json_extract(payload_json, '$.twilio.sid'), '') <> ''")

    sql = f"SELECT COUNT(1) FROM actions WHERE {' AND '.join(where)}"
    row = store.conn.execute(sql, tuple(params)).fetchone()
    return int(row[0] or 0) if row else 0


def _count_call_booked_today(store: ContextStore) -> int:
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    row = store.conn.execute(
        """
        SELECT COUNT(1)
        FROM actions
        WHERE action_type='call.attempt'
          AND ts >= ?
          AND json_extract(payload_json, '$.outcome') = 'booked'
        """,
        (today_start,),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _deliverability_snapshot(store: ContextStore, *, days: int) -> dict[str, float | int]:
    cutoff = (datetime.now(UTC) - timedelta(days=max(1, int(days)))).isoformat()
    emailed_row = store.conn.execute(
        """
        SELECT COUNT(DISTINCT lead_id)
        FROM messages
        WHERE channel='email' AND status='sent' AND ts >= ?
        """,
        (cutoff,),
    ).fetchone()
    bounced_row = store.conn.execute(
        """
        SELECT COUNT(DISTINCT m.lead_id)
        FROM messages m
        JOIN leads l ON l.id = m.lead_id
        WHERE m.channel='email' AND m.status='sent' AND m.ts >= ?
          AND l.status='bounced'
        """,
        (cutoff,),
    ).fetchone()
    emailed = int((emailed_row[0] or 0) if emailed_row else 0)
    bounced = int((bounced_row[0] or 0) if bounced_row else 0)
    bounce_rate = float(bounced) / float(emailed) if emailed else 0.0
    return {
        "window_days": max(1, int(days)),
        "emailed": emailed,
        "bounced": bounced,
        "bounce_rate": bounce_rate,
    }


def _compute_sms_channel_budgets(
    *,
    daily_sms_cap: int,
    sms_today_followup: int,
    sms_today_nudge: int,
    interest_reserve: int,
) -> dict[str, int]:
    """Compute total and per-channel SMS budgets for this UTC day.

    Reserve is a protected quota for high-intent inbound nudges. Follow-up SMS
    can only consume capacity beyond the remaining reserve.
    """
    cap = max(0, int(daily_sms_cap))
    reserve = max(0, min(int(interest_reserve), cap))
    used_followup = max(0, int(sms_today_followup))
    used_nudge = max(0, int(sms_today_nudge))

    used_total = max(0, used_followup + used_nudge)
    total_remaining = max(0, cap - used_total)

    # Reserve is consumed by nudge traffic first; remaining reserve is held.
    reserve_remaining = max(0, reserve - used_nudge)
    followup_remaining = max(0, total_remaining - reserve_remaining)

    return {
        "cap": cap,
        "interest_reserve": reserve,
        "interest_reserve_remaining": reserve_remaining,
        "used_followup": used_followup,
        "used_nudge": used_nudge,
        "used_total": used_total,
        "total_remaining": total_remaining,
        "followup_remaining": followup_remaining,
    }


def _log_guard_block(
    *,
    store: ContextStore,
    channel: str,
    reason: str,
    details: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {"channel": str(channel), "reason": str(reason)}
    if details:
        payload["details"] = details
    trace = f"guard:{channel}:{int(time.time())}"
    store.log_action(
        agent_id="guardrails.v1",
        action_type="guard.block",
        trace_id=trace,
        payload=payload,
    )


def _parse_iso_date(raw: str | None) -> date | None:
    val = (raw or "").strip()
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except Exception:
        return None


def _evaluate_paid_stop_loss(
    *,
    repo_root: Path,
    env: dict[str, str],
    has_revenue_signal: bool,
) -> dict[str, object]:
    state_path = repo_root / "autonomy" / "state" / "paid_stop_loss_state.json"
    state = _read_json(state_path)

    enabled = truthy(env.get("STOP_LOSS_ENABLED"), default=True)
    max_zero_runs = max(1, _int_env(env.get("STOP_LOSS_ZERO_REVENUE_RUNS"), 1))
    max_zero_days = max(1, _int_env(env.get("STOP_LOSS_ZERO_REVENUE_DAYS"), 1))
    today = datetime.now(UTC).date()

    if has_revenue_signal:
        next_state = {
            "enabled": bool(enabled),
            "has_revenue_signal": True,
            "zero_revenue_runs": 0,
            "first_zero_revenue_date_utc": "",
            "last_eval_date_utc": today.isoformat(),
            "blocked": False,
            "block_reason": "",
            "max_zero_runs": int(max_zero_runs),
            "max_zero_days": int(max_zero_days),
        }
        _write_json(state_path, next_state)
        return next_state

    first_zero_date = _parse_iso_date(str(state.get("first_zero_revenue_date_utc") or ""))
    if first_zero_date is None:
        first_zero_date = today

    zero_runs = _int_env(str(state.get("zero_revenue_runs", 0)), 0) + 1
    zero_days = int((today - first_zero_date).days) + 1

    blocked = bool(enabled) and (zero_runs >= max_zero_runs or zero_days >= max_zero_days)
    block_reason = ""
    if blocked:
        if zero_runs >= max_zero_runs:
            block_reason = "stop_loss_zero_revenue_runs"
        else:
            block_reason = "stop_loss_zero_revenue_days"

    next_state = {
        "enabled": bool(enabled),
        "has_revenue_signal": False,
        "zero_revenue_runs": int(zero_runs),
        "zero_revenue_days": int(zero_days),
        "first_zero_revenue_date_utc": first_zero_date.isoformat(),
        "last_eval_date_utc": today.isoformat(),
        "blocked": bool(blocked),
        "block_reason": block_reason,
        "max_zero_runs": int(max_zero_runs),
        "max_zero_days": int(max_zero_days),
    }
    _write_json(state_path, next_state)
    return next_state


def _send_email(*, smtp_user: str, smtp_password: str, to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP("smtp.fastmail.com", 587, timeout=20) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)


def _acquire_lock(lock_path: Path) -> object | None:
    """Best-effort single-instance lock (prevents double-runs and duplicate reports)."""
    try:
        import fcntl  # unix-only
    except Exception:  # pragma: no cover
        return None

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("w", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        with contextlib.suppress(Exception):
            fh.close()
        return None

    try:
        fh.write(str(os.getpid()))
        fh.flush()
    except (OSError, ValueError):
        # Lock ownership still holds; PID write is only a diagnostic convenience.
        return fh
    return fh


def _iter_ntfy_topics(raw: str) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


def _parse_categories(raw: str) -> list[str]:
    parts = [p.strip().lower() for p in (raw or "").split(",")]
    return [p for p in parts if p]


def _send_ntfy(
    *,
    server: str,
    topics: list[str],
    token: str,
    title: str,
    body: str,
    priority: int = 3,
    tags: str = "",
) -> bool:
    """
    Send a push notification via ntfy.sh (or self-hosted ntfy).

    Returns True if at least one topic was successfully notified.
    """
    server = (server or "").strip().rstrip("/")
    if not server or not topics:
        return False

    payload = (body or "").encode("utf-8")
    ok = False
    for topic in topics:
        url = f"{server}/{topic}"
        headers = {
            "User-Agent": "callcatcherops-live-job/1.0",
            "Title": title,
            "Priority": str(int(priority)),
        }
        if tags:
            headers["Tags"] = tags
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=20) as resp:
                # Best-effort: drain a tiny response body so the request completes cleanly.
                resp.read(64)
            ok = True
        except Exception as exc:
            print(f"ntfy send failed for topic={topic!r}: {exc}", file=sys.stderr)
            continue

    return ok


def _format_report(
    *,
    leadgen_new: int,
    call_list: dict | None = None,
    auto_calls: AutoCallResult | None = None,
    sms_followup: SmsResult | None = None,
    interest_nudge: InterestNudgeResult | None = None,
    twilio_inbox: TwilioInboxResult | None = None,
    revenue_learning: dict | None = None,
    guardrails: dict | None = None,
    engine_result: dict,
    inbox_result,
    scoreboard,
    scoreboard_days: int,
    kpi: dict[str, int] | None = None,
    funnel_result: FunnelWatchdogResult | None = None,
    goal_tasks: dict | None = None,
) -> str:
    now_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    lines: list[str] = []
    lines.append("CallCatcher Ops Daily Report")
    lines.append(f"As-of (UTC): {now_utc}")
    lines.append("")
    lines.append("Lead gen")
    lines.append(f"- new_leads_generated: {int(leadgen_new)}")
    if call_list is not None:
        lines.append("")
        lines.append("Call list (phone-first)")
        services = call_list.get("services") or []
        services_str = ",".join([str(s) for s in services]) if services else "n/a"
        lines.append(f"- services: {services_str}")
        lines.append(f"- rows: {int(call_list.get('rows') or 0)}")
        lines.append(f"- path: {call_list.get('path') or ''}")
    if auto_calls is not None:
        lines.append("")
        lines.append("Auto calls (Twilio)")
        lines.append(f"- status: {auto_calls.reason}")
        lines.append(f"- attempted: {auto_calls.attempted}")
        lines.append(f"- completed: {auto_calls.completed}")
        lines.append(f"- spoke: {auto_calls.spoke}")
        lines.append(f"- voicemail: {auto_calls.voicemail}")
        lines.append(f"- no_answer: {auto_calls.no_answer}")
        lines.append(f"- wrong_number: {auto_calls.wrong_number}")
        lines.append(f"- failed: {auto_calls.failed}")
        lines.append(f"- skipped: {auto_calls.skipped}")
    if sms_followup is not None:
        lines.append("")
        lines.append("SMS follow-up (Twilio)")
        lines.append(f"- status: {sms_followup.reason}")
        lines.append(f"- attempted: {sms_followup.attempted}")
        lines.append(f"- delivered: {sms_followup.delivered}")
        lines.append(f"- failed: {sms_followup.failed}")
        lines.append(f"- skipped: {sms_followup.skipped}")
    if interest_nudge is not None:
        lines.append("")
        lines.append("Interested nudge (Twilio)")
        lines.append(f"- status: {interest_nudge.reason}")
        lines.append(f"- candidates: {interest_nudge.candidates}")
        lines.append(f"- attempted: {interest_nudge.attempted}")
        lines.append(f"- nudged: {interest_nudge.nudged}")
        lines.append(f"- failed: {interest_nudge.failed}")
        lines.append(f"- skipped: {interest_nudge.skipped}")
    lines.append("")
    if kpi:
        lines.append("Revenue KPI")
        lines.append(f"- bookings_today: {int(kpi.get('bookings_today') or 0)}")
        lines.append(f"- payments_today: {int(kpi.get('payments_today') or 0)}")
        lines.append(f"- bookings_last_{int(scoreboard_days)}d: {int(kpi.get('bookings_window') or 0)}")
        lines.append(f"- payments_last_{int(scoreboard_days)}d: {int(kpi.get('payments_window') or 0)}")
        lines.append("")
    lines.append("Outreach run")
    lines.append(f"- sent_initial: {int(engine_result.get('sent_initial') or 0)}")
    lines.append(f"- sent_followup: {int(engine_result.get('sent_followup') or 0)}")
    if guardrails:
        lines.append("")
        lines.append("Guardrails")
        for k, v in guardrails.items():
            lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("Inbox sync (Fastmail)")
    for k, v in asdict(inbox_result).items():
        lines.append(f"- {k}: {v}")
    if twilio_inbox is not None:
        lines.append("")
        lines.append("Inbox sync (Twilio SMS)")
        for k, v in asdict(twilio_inbox).items():
            lines.append(f"- {k}: {v}")
    if revenue_learning:
        lines.append("")
        lines.append("Revenue learning (RAG)")
        lines.append(f"- saved: {bool(revenue_learning.get('saved'))}")
        lines.append(f"- bottleneck: {revenue_learning.get('bottleneck') or ''}")
        lines.append(f"- leading_signal: {revenue_learning.get('leading_signal') or ''}")
        lines.append(f"- confidence_pct: {revenue_learning.get('confidence_pct')}")
        lines.append(f"- path: {revenue_learning.get('path') or ''}")
        for action in revenue_learning.get("next_actions", [])[:3]:
            lines.append(f"- next_action: {action}")

    if funnel_result is not None:
        lines.append("")
        lines.append("Funnel watchdog")
        lines.append(f"- healthy: {bool(funnel_result.is_healthy)}")
        lines.append(f"- checks: {int(funnel_result.checks_ok)}/{int(funnel_result.checks_total)}")
        if funnel_result.issues:
            for issue in funnel_result.issues:
                lines.append(f"- issue_{issue.name}: {issue.detail} ({issue.url})")
    if goal_tasks is not None:
        lines.append("")
        lines.append("Goal-driven tasks")
        lines.append(f"- generated: {int(goal_tasks.get('generated', 0))}")
        lines.append(f"- done: {int(goal_tasks.get('done', 0))}")
        lines.append(f"- failed: {int(goal_tasks.get('failed', 0))}")
    lines.append("")
    lines.append(f"Scoreboard (last {int(scoreboard_days)} days)")
    lines.append(
        "Leads: "
        f"{scoreboard.leads_total} total | "
        f"{scoreboard.leads_new} new | "
        f"{scoreboard.leads_contacted} contacted | "
        f"{scoreboard.leads_replied} replied | "
        f"{scoreboard.leads_bounced} bounced | "
        f"{scoreboard.leads_other} other"
    )
    lines.append(
        "Email sent: "
        f"{scoreboard.email_sent_total} total | "
        f"{scoreboard.email_sent_recent} in last {int(scoreboard_days)} days | "
        f"last sent: {scoreboard.last_email_ts or 'n/a'}"
    )
    lines.append(
        "Deliverability: "
        f"{int(scoreboard.bounced_leads_recent)}/{int(scoreboard.emailed_leads_recent)} bounced leads in last {int(scoreboard_days)} days "
        f"({float(scoreboard.bounce_rate_recent or 0.0):.0%})"
    )
    lines.append(
        "Calls: "
        f"{int(scoreboard.call_attempts_total)} total | "
        f"{int(scoreboard.call_attempts_recent)} in last {int(scoreboard_days)} days | "
        f"booked: {int(scoreboard.call_booked_total)} total ({int(scoreboard.call_booked_recent)} recent)"
    )
    lines.append(
        "Revenue outcomes: "
        f"bookings={int(scoreboard.bookings_total)} total ({int(scoreboard.bookings_recent)} recent) | "
        f"payments={int(scoreboard.stripe_payments_total)} total ({int(scoreboard.stripe_payments_recent)} recent)"
    )
    lines.append(f"Opt-outs recorded: {scoreboard.opt_out_total}")
    return "\n".join(lines).strip() + "\n"


def _maybe_run_leadgen(*, cfg, env: dict, repo_root: Path) -> int:
    limit_raw = (env.get("DAILY_LEADGEN_LIMIT") or "").strip()
    if not limit_raw:
        return 0
    try:
        limit = int(limit_raw)
    except Exception:
        return 0
    if limit <= 0:
        return 0

    # Put Google API key(s) into process env so leadgen can read them.
    for key_name in ("GOOGLE_PLACES_API_KEY", "GOOGLE_CLOUD_API_KEY", "GOOGLE_API_KEY"):
        val = (env.get(key_name) or "").strip()
        if val:
            os.environ.setdefault(key_name, val)

    # Determine output CSV from the first configured CSV lead source.
    output_rel = ""
    for src in (cfg.lead_sources or []):
        if (src.get("type") or "").lower() == "csv":
            output_rel = str(src.get("path") or "").strip()
            break
    if not output_rel:
        return 0

    output_path = (repo_root / output_rel).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        api_key = get_api_key()
    except SystemExit:
        return 0

    try:
        cities = load_cities(None)
    except SystemExit:
        return 0
    categories_raw = (
        (env.get("DAILY_LEADGEN_CATEGORIES") or "").strip()
        or (env.get("LEADGEN_CATEGORIES") or "").strip()
    )
    categories = _parse_categories(categories_raw) or DEFAULT_CATEGORIES[:]

    existing_emails, existing_domains, existing_phones = load_existing(output_path)
    try:
        leads, new_index = build_leads(
            cities=cities,
            categories=categories,
            limit=limit,
            api_key=api_key,
            existing_emails=existing_emails,
            existing_domains=existing_domains,
            existing_phones=existing_phones,
        )
    except SystemExit:
        return 0
    except Exception:
        return 0

    if not leads:
        return 0

    write_leads(output_path, leads, replace=False)
    save_city_index(new_index)
    return len(leads)


def _maybe_write_call_list(*, cfg, env: dict, repo_root: Path) -> dict | None:
    raw_services = (env.get("DAILY_CALL_LIST_SERVICES") or "").strip()
    if not raw_services:
        fallback = (cfg.agents.get("outreach", {}) or {}).get("target_services") or []
        raw_services = ",".join([str(s).strip() for s in fallback if str(s).strip()])
    if not raw_services:
        return None

    services = [s.strip() for s in raw_services.split(",") if s.strip()]
    if not services:
        return None

    limit_raw = (env.get("DAILY_CALL_LIST_LIMIT") or "").strip()
    limit = 25
    if limit_raw:
        try:
            limit = int(limit_raw)
        except Exception:
            limit = 25
    if limit <= 0:
        return None

    high_intent_only = truthy(env.get("HIGH_INTENT_OUTREACH_ONLY"), default=True)
    raw_statuses = (env.get("DAILY_CALL_LIST_STATUSES") or "").strip()
    statuses = [s.strip() for s in raw_statuses.split(",") if s.strip()]
    if not statuses and high_intent_only:
        statuses = ["replied", "contacted", "new"]

    default_min_score = 80 if high_intent_only else 0
    min_score = max(0, _int_env(env.get("DAILY_CALL_LIST_MIN_SCORE"), default_min_score))
    exclude_role_inbox = truthy(env.get("DAILY_CALL_LIST_EXCLUDE_ROLE_INBOX"), default=high_intent_only)

    output_rel = (env.get("DAILY_CALL_LIST_OUTPUT") or "").strip()
    if not output_rel:
        today_utc = datetime.now(UTC).date().isoformat()
        slug = "-".join([s.lower().replace(" ", "_") for s in services]) or "all"
        output_rel = f"autonomy/state/call_list_{slug}_{today_utc}.csv"

    # Pull website URLs from the first configured CSV lead source, if available.
    source_csv_path: Path | None = None
    for src in (cfg.lead_sources or []):
        if (src.get("type") or "").lower() == "csv":
            rel = str(src.get("path") or "").strip()
            if rel:
                source_csv_path = (repo_root / rel).resolve()
            break

    sqlite_path_raw = Path(cfg.storage["sqlite_path"])
    sqlite_path = sqlite_path_raw if sqlite_path_raw.is_absolute() else (repo_root / sqlite_path_raw).resolve()

    rows = generate_call_list(
        sqlite_path=sqlite_path,
        services=services,
        statuses=statuses or None,
        min_score=min_score,
        exclude_role_inbox=exclude_role_inbox,
        limit=limit,
        require_phone=True,
        include_opt_outs=False,
        source_csv=source_csv_path,
    )
    output_path = (repo_root / output_rel).resolve()
    write_call_list(output_path, rows)

    # Include row data in-memory so other steps (e.g. auto-calls) can reuse it.
    return {
        "services": services,
        "rows": len(rows),
        "path": str(output_rel),
        "data": rows,
        "statuses": statuses,
        "min_score": min_score,
        "exclude_role_inbox": bool(exclude_role_inbox),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="CallCatcher Ops live daily job: inbox sync + outreach + report.")
    parser.add_argument("--config", default="autonomy/state/config.callcatcherops.live.json", help="Live config path.")
    parser.add_argument("--dotenv", default=".env", help="Local .env path (gitignored).")
    parser.add_argument("--scoreboard-days", type=int, default=30, help="Scoreboard window.")
    parser.add_argument("--report-to", default="", help="Override report recipient email.")
    parser.add_argument(
        "--report-path",
        default="autonomy/state/daily_report_latest.txt",
        help="Write the latest report here (gitignored).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    dotenv_path = (repo_root / args.dotenv).resolve()
    env = load_dotenv(dotenv_path)

    lock_enabled = truthy(env.get("LIVE_JOB_LOCK"), default=True)
    lock_fh = None
    if lock_enabled:
        lock_fh = _acquire_lock(repo_root / "autonomy" / "state" / "live_job.lock")
        if lock_fh is None:
            print("live_job: another instance appears to be running; exiting", file=sys.stderr)
            return

    t0 = time.monotonic()

    report_delivery = (env.get("REPORT_DELIVERY") or "email").strip().lower()
    if report_delivery not in {"email", "ntfy", "both", "none"}:
        report_delivery = "email"
    send_report_email = report_delivery in {"email", "both"}
    send_report_ntfy = report_delivery in {"ntfy", "both"}

    ntfy_server = (env.get("NTFY_SERVER") or "https://ntfy.sh").strip()
    ntfy_topics = _iter_ntfy_topics(env.get("NTFY_TOPIC", ""))
    ntfy_token = (env.get("NTFY_TOKEN") or "").strip()

    fastmail_user = env.get("FASTMAIL_USER", "")
    smtp_password = env.get("SMTP_PASSWORD", "")
    report_to = args.report_to.strip() or env.get("FASTMAIL_FORWARD_TO", "").strip()

    if not fastmail_user:
        raise SystemExit("Missing FASTMAIL_USER in .env")
    if not smtp_password:
        raise SystemExit("Missing SMTP_PASSWORD in .env")
    if send_report_email and not report_to:
        raise SystemExit("Missing FASTMAIL_FORWARD_TO or --report-to (required for REPORT_DELIVERY=email/both)")
    if send_report_ntfy and not ntfy_topics:
        raise SystemExit("Missing NTFY_TOPIC (required for REPORT_DELIVERY=ntfy/both)")

    # Ensure the outreach engine can read SMTP_PASSWORD via config.email.smtp_password_env.
    os.environ.setdefault("SMTP_PASSWORD", smtp_password)

    cfg_path = (repo_root / args.config).resolve()
    cfg = load_config(str(cfg_path))
    sqlite_path, audit_log = _resolve_store_paths(cfg=cfg, repo_root=repo_root)
    guard_store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    guardrails: dict[str, object] = {}
    twilio_inbox_result = TwilioInboxResult(reason="not_run")

    # 0) Optional: generate new leads before outreach (to keep pipeline full).
    leadgen_new = _maybe_run_leadgen(cfg=cfg, env=env, repo_root=repo_root)
    print(f"live_job: leadgen_new={leadgen_new} (t+{time.monotonic() - t0:.1f}s)", file=sys.stderr)

    # 1) Sync inbox first so bounces/replies suppress follow-ups.
    fastmail_state_path = repo_root / "autonomy" / "state" / "fastmail_sync_state.json"
    try:
        inbox_result = sync_fastmail_inbox(
            sqlite_path=sqlite_path,
            audit_log=audit_log,
            fastmail_user=fastmail_user,
            fastmail_password=smtp_password,
            state_path=fastmail_state_path,
        )
    except Exception as exc:
        # Never block the daily job if IMAP is flaky.
        print(f"inbox sync failed: {exc}", file=sys.stderr)
        prior_uid = int((_read_json(fastmail_state_path).get("last_uid") or 0) or 0)
        inbox_result = InboxSyncResult(
            processed_messages=0,
            new_bounces=0,
            new_replies=0,
            new_opt_outs=0,
            intake_submissions=0,
            calendly_bookings=0,
            stripe_payments=0,
            last_uid=prior_uid,
        )
    print(f"live_job: inbox_sync done (t+{time.monotonic() - t0:.1f}s)", file=sys.stderr)

    if truthy(env.get("TWILIO_INBOX_SYNC_ENABLED"), default=True):
        twilio_inbox_result = run_twilio_inbox_sync(
            sqlite_path=sqlite_path,
            audit_log=audit_log,
            env=env,
            booking_url=cfg.company.get("booking_url", ""),
            kickoff_url=cfg.company.get("kickoff_url", ""),
        )
    else:
        twilio_inbox_result = TwilioInboxResult(reason="disabled")
    print(f"live_job: twilio_inbox done (t+{time.monotonic() - t0:.1f}s)", file=sys.stderr)

    board_pre = load_scoreboard(sqlite_path, days=int(args.scoreboard_days))

    deliverability_gate_enabled = truthy(env.get("DELIVERABILITY_GATE_ENABLED"), default=True)
    high_intent_only = truthy(env.get("HIGH_INTENT_OUTREACH_ONLY"), default=True)
    guardrails["high_intent_mode"] = bool(high_intent_only)
    deliverability_window_days = max(1, _int_env(env.get("DELIVERABILITY_WINDOW_DAYS"), 7))
    deliverability_min_emails = max(1, _int_env(env.get("DELIVERABILITY_MIN_EMAILS"), 10))
    deliverability_snapshot = _deliverability_snapshot(guard_store, days=deliverability_window_days)
    deliverability_max_bounce = max(0.0, min(1.0, _float_env(env.get("DELIVERABILITY_MAX_BOUNCE_RATE"), 0.05)))
    deliverability_block = bool(
        deliverability_gate_enabled
        and int(deliverability_snapshot["emailed"] or 0) >= int(deliverability_min_emails)
        and float(deliverability_snapshot["bounce_rate"] or 0.0) > float(deliverability_max_bounce)
    )
    guardrails["deliverability_gate_enabled"] = bool(deliverability_gate_enabled)
    guardrails["deliverability_window_days"] = int(deliverability_window_days)
    guardrails["deliverability_min_emails"] = int(deliverability_min_emails)
    guardrails["deliverability_max_bounce_rate"] = float(deliverability_max_bounce)
    guardrails["deliverability_emailed_window"] = int(deliverability_snapshot["emailed"] or 0)
    guardrails["deliverability_bounced_window"] = int(deliverability_snapshot["bounced"] or 0)
    guardrails["deliverability_recent_bounce_rate"] = float(deliverability_snapshot["bounce_rate"] or 0.0)
    guardrails["deliverability_blocked"] = bool(deliverability_block)

    if deliverability_block:
        _log_guard_block(
            store=guard_store,
            channel="email.outreach",
            reason="deliverability_bounce_rate",
            details={
                "bounce_rate_recent": float(deliverability_snapshot["bounce_rate"] or 0.0),
                "max_bounce_rate": float(deliverability_max_bounce),
                "emailed_leads_recent": int(deliverability_snapshot["emailed"] or 0),
                "window_days": int(deliverability_window_days),
                "min_emails": int(deliverability_min_emails),
            },
        )
        engine_result = {
            "sent_initial": 0,
            "sent_followup": 0,
            "goal_tasks_generated": 0,
            "goal_tasks_done": 0,
            "goal_tasks_failed": 0,
            "guard_blocked": "deliverability_bounce_rate",
        }
        print("live_job: engine blocked by deliverability gate", file=sys.stderr)
    else:
        if high_intent_only:
            outreach_cfg = dict((cfg.agents.get("outreach") or {}))
            follow_cfg = dict((outreach_cfg.get("followup") or {}))
            min_email_score = max(0, _int_env(env.get("HIGH_INTENT_EMAIL_MIN_SCORE"), 80))
            outreach_cfg["min_score"] = max(int(outreach_cfg.get("min_score") or 0), min_email_score)
            if truthy(env.get("HIGH_INTENT_SKIP_COLD_EMAIL"), default=True):
                outreach_cfg["daily_send_limit"] = 0
            follow_cfg["enabled"] = bool(follow_cfg.get("enabled", True))
            outreach_cfg["followup"] = follow_cfg
            cfg.agents["outreach"] = outreach_cfg
            guardrails["high_intent_email_min_score"] = int(outreach_cfg["min_score"])
            guardrails["high_intent_skip_cold_email"] = bool(outreach_cfg.get("daily_send_limit", 0) == 0)

        # 2) Run outreach (initial + follow-ups) using live config.
        engine = Engine(cfg)
        engine_result = engine.run()
        print(f"live_job: engine done (t+{time.monotonic() - t0:.1f}s)", file=sys.stderr)

    has_revenue_signal = bool(
        int(board_pre.bookings_total or 0) > 0
        or int(board_pre.stripe_payments_total or 0) > 0
        or int(inbox_result.calendly_bookings or 0) > 0
        or int(inbox_result.stripe_payments or 0) > 0
        or int(twilio_inbox_result.interested or 0) > 0
    )
    stop_loss_state = _evaluate_paid_stop_loss(
        repo_root=repo_root,
        env=env,
        has_revenue_signal=has_revenue_signal,
    )
    guardrails["stop_loss_blocked"] = bool(stop_loss_state.get("blocked", False))
    guardrails["stop_loss_reason"] = str(stop_loss_state.get("block_reason") or "")
    guardrails["zero_revenue_runs"] = int(stop_loss_state.get("zero_revenue_runs") or 0)
    guardrails["zero_revenue_days"] = int(stop_loss_state.get("zero_revenue_days") or 0)

    paid_kill_switch = truthy(env.get("PAID_KILL_SWITCH"), default=False)
    guardrails["paid_kill_switch"] = bool(paid_kill_switch)

    daily_call_cap = max(0, _int_env(env.get("PAID_DAILY_CALL_CAP"), 10))
    calls_today_all = _count_actions_today(guard_store, action_type="call.attempt")
    calls_today = _count_actions_today(guard_store, action_type="call.attempt", paid_only=True)
    call_budget_remaining = max(0, int(daily_call_cap) - int(calls_today))
    guardrails["call_daily_cap"] = int(daily_call_cap)
    guardrails["calls_today_scope"] = "billable_twilio"
    guardrails["calls_today_all_actions"] = int(calls_today_all)
    guardrails["calls_today"] = int(calls_today)
    guardrails["calls_budget_remaining"] = int(call_budget_remaining)

    daily_sms_cap = max(0, _int_env(env.get("PAID_DAILY_SMS_CAP"), 10))
    daily_sms_interest_reserve = max(0, _int_env(env.get("PAID_DAILY_SMS_INTEREST_RESERVE"), 3))
    sms_today_followup_all = _count_actions_today(guard_store, action_type="sms.attempt")
    sms_today_nudge_all = _count_actions_today(guard_store, action_type="sms.interest_nudge")
    sms_today_all = int(sms_today_followup_all) + int(sms_today_nudge_all)
    sms_today_followup = _count_actions_today(guard_store, action_type="sms.attempt", paid_only=True)
    sms_today_nudge = _count_actions_today(guard_store, action_type="sms.interest_nudge", paid_only=True)
    sms_budgets = _compute_sms_channel_budgets(
        daily_sms_cap=daily_sms_cap,
        sms_today_followup=sms_today_followup,
        sms_today_nudge=sms_today_nudge,
        interest_reserve=daily_sms_interest_reserve,
    )
    sms_today = int(sms_budgets["used_total"])
    sms_budget_remaining = int(sms_budgets["total_remaining"])
    sms_followup_budget_remaining = int(sms_budgets["followup_remaining"])
    guardrails["sms_daily_cap"] = int(daily_sms_cap)
    guardrails["sms_interest_reserve"] = int(sms_budgets["interest_reserve"])
    guardrails["sms_interest_reserve_remaining"] = int(sms_budgets["interest_reserve_remaining"])
    guardrails["sms_today_scope"] = "billable_twilio"
    guardrails["sms_today_all_actions"] = int(sms_today_all)
    guardrails["sms_today_followup_actions"] = int(sms_today_followup_all)
    guardrails["sms_today_interest_nudges"] = int(sms_today_nudge_all)
    guardrails["sms_today"] = int(sms_today)
    guardrails["sms_budget_remaining"] = int(sms_budget_remaining)
    guardrails["sms_followup_budget_remaining"] = int(sms_followup_budget_remaining)

    funnel_enabled = (env.get("FUNNEL_WATCHDOG") or "1").strip().lower() not in {"0", "false", "no", "off"}
    funnel_result: FunnelWatchdogResult | None = None
    if funnel_enabled:
        try:
            funnel_result = run_funnel_watchdog(
                repo_root=repo_root,
                intake_url=cfg.company.get("intake_url", ""),
                unsubscribe_url_template=(cfg.compliance or {}).get("unsubscribe_url", ""),
            )
        except Exception as exc:
            funnel_result = FunnelWatchdogResult(as_of_utc=datetime.now(UTC).replace(microsecond=0).isoformat())
            funnel_result.add_issue(name="watchdog_error", url=cfg.company.get("intake_url", ""), detail=str(exc))
    print(f"live_job: funnel_watchdog done (t+{time.monotonic() - t0:.1f}s)", file=sys.stderr)

    # 2b) High-intent SMS nudges for inbound "interested" replies.
    interest_nudge_result: InterestNudgeResult | None = None
    nudge_block_reason = ""
    if not truthy(env.get("AUTO_INTEREST_NUDGE_ENABLED"), default=True):
        nudge_block_reason = "auto_interest_nudge_disabled"
    elif paid_kill_switch:
        nudge_block_reason = "paid_kill_switch"
    elif bool(stop_loss_state.get("blocked", False)):
        nudge_block_reason = str(stop_loss_state.get("block_reason") or "stop_loss")
    elif sms_budget_remaining <= 0:
        nudge_block_reason = "sms_daily_cap_reached"

    if nudge_block_reason:
        _log_guard_block(
            store=guard_store,
            channel="sms.interest_nudge",
            reason=nudge_block_reason,
            details={
                "sms_today": int(sms_today),
                "sms_today_all_actions": int(sms_today_all),
                "sms_daily_cap": int(daily_sms_cap),
            },
        )
        interest_nudge_result = InterestNudgeResult(reason=f"blocked:{nudge_block_reason}")
    else:
        nudge_env = dict(env)
        configured_max_nudges = max(1, _int_env(nudge_env.get("AUTO_INTEREST_NUDGE_MAX_PER_RUN"), 6))
        nudge_env["AUTO_INTEREST_NUDGE_MAX_PER_RUN"] = str(min(configured_max_nudges, sms_budget_remaining))
        interest_nudge_result = run_interest_nudges(
            sqlite_path=sqlite_path,
            audit_log=audit_log,
            env=nudge_env,
            booking_url=cfg.company.get("booking_url", ""),
            kickoff_url=cfg.company.get("kickoff_url", ""),
        )
        sms_budgets = _compute_sms_channel_budgets(
            daily_sms_cap=daily_sms_cap,
            sms_today_followup=sms_today_followup,
            sms_today_nudge=(sms_today_nudge + int(interest_nudge_result.nudged)),
            interest_reserve=daily_sms_interest_reserve,
        )
        sms_budget_remaining = int(sms_budgets["total_remaining"])
        sms_followup_budget_remaining = int(sms_budgets["followup_remaining"])
        guardrails["sms_budget_remaining_after_nudges"] = int(sms_budget_remaining)
        guardrails["sms_followup_budget_remaining_after_nudges"] = int(sms_followup_budget_remaining)

    # 3) Optional: write a call list and place outbound calls (Twilio) before computing scoreboard.
    call_list = _maybe_write_call_list(cfg=cfg, env=env, repo_root=repo_root)
    if call_list is not None:
        guardrails["call_list_statuses"] = call_list.get("statuses") or []
        guardrails["call_list_min_score"] = int(call_list.get("min_score") or 0)
        guardrails["call_list_exclude_role_inbox"] = bool(call_list.get("exclude_role_inbox"))
    auto_calls: AutoCallResult | None = None
    if call_list is not None and isinstance(call_list.get("data"), list):
        calls_block_reason = ""
        if not truthy(env.get("AUTO_CALLS_ENABLED"), default=False):
            calls_block_reason = "auto_calls_disabled"
        elif paid_kill_switch:
            calls_block_reason = "paid_kill_switch"
        elif bool(stop_loss_state.get("blocked", False)):
            calls_block_reason = str(stop_loss_state.get("block_reason") or "stop_loss")
        elif call_budget_remaining <= 0:
            calls_block_reason = "call_daily_cap_reached"

        if calls_block_reason:
            _log_guard_block(
                store=guard_store,
                channel="calls.twilio",
                reason=calls_block_reason,
                details={
                    "calls_today": int(calls_today),
                    "calls_today_all_actions": int(calls_today_all),
                    "call_daily_cap": int(daily_call_cap),
                },
            )
            auto_calls = AutoCallResult(
                attempted=0,
                completed=0,
                spoke=0,
                voicemail=0,
                no_answer=0,
                wrong_number=0,
                failed=0,
                skipped=0,
                reason=f"blocked:{calls_block_reason}",
            )
        else:
            call_env = dict(env)
            configured_max_calls = max(1, _int_env(call_env.get("AUTO_CALLS_MAX_PER_RUN"), 10))
            call_env["AUTO_CALLS_MAX_PER_RUN"] = str(min(configured_max_calls, call_budget_remaining))
            auto_calls = run_auto_calls(sqlite_path=sqlite_path, audit_log=audit_log, env=call_env, call_rows=call_list["data"])

    # 3b) Optional: send SMS follow-ups to leads that were called (spoke/voicemail).
    sms_result: SmsResult | None = None
    if auto_calls is not None and (auto_calls.spoke + auto_calls.voicemail) > 0:
        sms_block_reason = ""
        if not truthy(env.get("AUTO_SMS_ENABLED"), default=False):
            sms_block_reason = "auto_sms_disabled"
        elif paid_kill_switch:
            sms_block_reason = "paid_kill_switch"
        elif bool(stop_loss_state.get("blocked", False)):
            sms_block_reason = str(stop_loss_state.get("block_reason") or "stop_loss")
        elif sms_followup_budget_remaining <= 0:
            if sms_budget_remaining > 0:
                sms_block_reason = "sms_reserved_for_interest"
            else:
                sms_block_reason = "sms_daily_cap_reached"

        if sms_block_reason:
            _log_guard_block(
                store=guard_store,
                channel="sms.twilio",
                reason=sms_block_reason,
                details={
                    "sms_today": int(sms_today),
                    "sms_today_all_actions": int(sms_today_all),
                    "sms_daily_cap": int(daily_sms_cap),
                    "sms_interest_reserve": int(sms_budgets["interest_reserve"]),
                    "sms_interest_reserve_remaining": int(sms_budgets["interest_reserve_remaining"]),
                    "sms_followup_budget_remaining": int(sms_followup_budget_remaining),
                },
            )
            sms_result = SmsResult(reason=f"blocked:{sms_block_reason}")
        else:
            sms_env = dict(env)
            configured_max_sms = max(1, _int_env(sms_env.get("AUTO_SMS_MAX_PER_RUN"), 20))
            sms_env["AUTO_SMS_MAX_PER_RUN"] = str(min(configured_max_sms, sms_followup_budget_remaining))
            sms_result = run_sms_followup(
                sqlite_path=sqlite_path,
                audit_log=audit_log,
                env=sms_env,
                booking_url=cfg.company.get("booking_url", ""),
            )

    board = load_scoreboard(sqlite_path, days=int(args.scoreboard_days))
    bookings_today = int(_count_call_booked_today(guard_store)) + int(
        _count_actions_today(guard_store, action_type="conversion.booking")
    )
    payments_today = int(_count_actions_today(guard_store, action_type="conversion.payment"))
    kpi = {
        "bookings_today": bookings_today,
        "payments_today": payments_today,
        "bookings_window": int(board.bookings_recent),
        "payments_window": int(board.stripe_payments_recent),
    }
    guardrails["kpi_bookings_today"] = int(bookings_today)
    guardrails["kpi_payments_today"] = int(payments_today)
    guardrails[f"kpi_bookings_last_{int(args.scoreboard_days)}d"] = int(board.bookings_recent)
    guardrails[f"kpi_payments_last_{int(args.scoreboard_days)}d"] = int(board.stripe_payments_recent)
    revenue_sources = [s.strip() for s in (env.get("REVENUE_RESEARCH_SOURCES") or "").split(",") if s.strip()]
    lesson = build_revenue_lesson(
        scoreboard=board,
        guardrails=guardrails,
        inbox_result=inbox_result,
        twilio_inbox_result=twilio_inbox_result,
        auto_calls=auto_calls,
        sms_followup=sms_result,
        sources=revenue_sources,
    )
    revenue_learning_raw = record_revenue_lesson(repo_root=repo_root, lesson=lesson)
    revenue_learning = {
        "saved": bool(revenue_learning_raw.get("saved")),
        "path": str(revenue_learning_raw.get("path") or ""),
        "bottleneck": lesson.bottleneck,
        "leading_signal": lesson.leading_signal,
        "confidence_pct": lesson.confidence_pct,
        "next_actions": lesson.next_actions,
    }
    goal_task_data = {
        "generated": engine_result.get("goal_tasks_generated", 0),
        "done": engine_result.get("goal_tasks_done", 0),
        "failed": engine_result.get("goal_tasks_failed", 0),
    }
    report = _format_report(
        leadgen_new=leadgen_new,
        call_list=call_list,
        auto_calls=auto_calls,
        sms_followup=sms_result,
        interest_nudge=interest_nudge_result,
        twilio_inbox=twilio_inbox_result,
        revenue_learning=revenue_learning,
        guardrails=guardrails,
        engine_result=engine_result,
        inbox_result=inbox_result,
        scoreboard=board,
        scoreboard_days=int(args.scoreboard_days),
        kpi=kpi,
        funnel_result=funnel_result,
        goal_tasks=goal_task_data,
    )

    report_path = (repo_root / args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    # De-dupe: avoid spamming multiple reports in the same day (common during restarts).
    report_state_path = repo_root / "autonomy" / "state" / "daily_report_state.json"
    state = _read_json(report_state_path)
    today_utc = datetime.now(UTC).date().isoformat()

    summary_payload = {
        "leadgen_new": int(leadgen_new),
        "engine_result": engine_result,
        "inbox_result": asdict(inbox_result),
        "twilio_inbox_result": asdict(twilio_inbox_result),
        "interest_nudge_result": asdict(interest_nudge_result) if interest_nudge_result is not None else None,
        "revenue_learning": revenue_learning,
        "funnel_watchdog": asdict(funnel_result) if funnel_result is not None else None,
        "guardrails": guardrails,
        "scoreboard_days": int(args.scoreboard_days),
        "scoreboard": asdict(board),
        "kpi": kpi,
    }
    summary_sha1 = hashlib.sha1(json.dumps(summary_payload, sort_keys=True).encode("utf-8")).hexdigest()

    last_sent_date = state.get("last_sent_date_utc")
    # Backward compat: older runs wrote last_sent_sha1.
    last_sent_sha1 = state.get("last_summary_sha1") or state.get("last_sent_sha1")

    # If we already sent a report today, only resend when something truly urgent happens.
    # Default urgency is tied to booking/revenue signals to avoid inbox fatigue.
    urgent_change = bool(
        int(inbox_result.calendly_bookings or 0) > 0
        or int(inbox_result.stripe_payments or 0) > 0
    )
    if truthy(env.get("REPORT_URGENT_ON_INTAKE"), default=False) and int(inbox_result.intake_submissions or 0) > 0:
        urgent_change = True
    if truthy(env.get("REPORT_URGENT_ON_REPLY"), default=False) and int(inbox_result.new_replies or 0) > 0:
        urgent_change = True
    if truthy(env.get("REPORT_URGENT_ON_TWILIO_INTEREST"), default=False) and int(twilio_inbox_result.interested or 0) > 0:
        urgent_change = True
    if truthy(env.get("REPORT_URGENT_ON_FUNNEL_ISSUES"), default=True) and funnel_result is not None and not funnel_result.is_healthy:
        urgent_change = True

    should_send = False
    if last_sent_date != today_utc:
        should_send = True  # daily heartbeat
    elif summary_sha1 != last_sent_sha1 and urgent_change:
        should_send = True  # urgent update the same day

    if should_send:
        is_urgent_update = last_sent_date == today_utc and urgent_change
        subject = f"CallCatcher Ops {'Urgent Update' if is_urgent_update else 'Daily Report'} ({today_utc})"
        tags = "callcatcherops"
        priority = 5 if is_urgent_update else 3
        if urgent_change:
            tags += ",urgent"

        sent_any = False
        if send_report_email:
            try:
                _send_email(
                    smtp_user=cfg.email["smtp_user"],
                    smtp_password=smtp_password,
                    to_email=report_to,
                    subject=subject,
                    body=report,
                )
                sent_any = True
            except Exception as exc:
                print(f"email report send failed: {exc}", file=sys.stderr)

        if send_report_ntfy:
            sent_any = (
                _send_ntfy(
                    server=ntfy_server,
                    topics=ntfy_topics,
                    token=ntfy_token,
                    title=subject,
                    body=report,
                    priority=priority,
                    tags=tags,
                )
                or sent_any
            )

        if not sent_any:
            print("warning: report not delivered (REPORT_DELIVERY=none or all sinks failed)", file=sys.stderr)
        else:
            _write_json(
                report_state_path,
                {
                    "last_sent_date_utc": today_utc,
                    "last_summary_sha1": summary_sha1,
                    "sent_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
                },
            )
    print(f"live_job: report done (t+{time.monotonic() - t0:.1f}s)", file=sys.stderr)

    # Helpful for launchd logs.
    print(report)
    with contextlib.suppress(Exception):
        guard_store.conn.close()
    if lock_fh is not None:
        with contextlib.suppress(OSError, ValueError):
            lock_fh.close()


if __name__ == "__main__":
    main()
