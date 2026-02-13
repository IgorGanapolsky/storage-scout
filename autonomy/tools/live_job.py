#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import smtplib
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

# Support running as a script (launchd uses absolute paths).
if __package__ is None:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autonomy.engine import Engine, load_config
from autonomy.tools.lead_gen_broward import (
    DEFAULT_CATEGORIES,
    build_leads,
    get_api_key,
    load_cities,
    load_existing,
    save_city_index,
    write_leads,
)
from autonomy.tools.fastmail_inbox_sync import load_dotenv, sync_fastmail_inbox
from autonomy.tools.scoreboard import load_scoreboard


UTC = timezone.utc


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


def _format_report(*, leadgen_new: int, engine_result: dict, inbox_result, scoreboard, scoreboard_days: int) -> str:
    now_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    lines: list[str] = []
    lines.append("CallCatcher Ops Daily Report")
    lines.append(f"As-of (UTC): {now_utc}")
    lines.append("")
    lines.append("Lead gen")
    lines.append(f"- new_leads_generated: {int(leadgen_new)}")
    lines.append("")
    lines.append("Outreach run")
    lines.append(f"- sent_initial: {int(engine_result.get('sent_initial') or 0)}")
    lines.append(f"- sent_followup: {int(engine_result.get('sent_followup') or 0)}")
    lines.append("")
    lines.append("Inbox sync (Fastmail)")
    for k, v in asdict(inbox_result).items():
        lines.append(f"- {k}: {v}")
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
    categories = DEFAULT_CATEGORIES[:]

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

    fastmail_user = env.get("FASTMAIL_USER", "")
    smtp_password = env.get("SMTP_PASSWORD", "")
    report_to = args.report_to.strip() or env.get("FASTMAIL_FORWARD_TO", "").strip()

    if not fastmail_user:
        raise SystemExit("Missing FASTMAIL_USER in .env")
    if not smtp_password:
        raise SystemExit("Missing SMTP_PASSWORD in .env")
    if not report_to:
        raise SystemExit("Missing FASTMAIL_FORWARD_TO or --report-to")

    # Ensure the outreach engine can read SMTP_PASSWORD via config.email.smtp_password_env.
    os.environ.setdefault("SMTP_PASSWORD", smtp_password)

    cfg_path = (repo_root / args.config).resolve()
    cfg = load_config(str(cfg_path))

    # 0) Optional: generate new leads before outreach (to keep pipeline full).
    leadgen_new = _maybe_run_leadgen(cfg=cfg, env=env, repo_root=repo_root)

    # 1) Sync inbox first so bounces/replies suppress follow-ups.
    inbox_result = sync_fastmail_inbox(
        sqlite_path=Path(cfg.storage["sqlite_path"]),
        audit_log=Path(cfg.storage["audit_log"]),
        fastmail_user=fastmail_user,
        fastmail_password=smtp_password,
        state_path=repo_root / "autonomy" / "state" / "fastmail_sync_state.json",
    )

    # 2) Run outreach (initial + follow-ups) using live config.
    engine = Engine(cfg)
    engine_result = engine.run()

    # 3) Scoreboard + email report.
    board = load_scoreboard(Path(cfg.storage["sqlite_path"]), days=int(args.scoreboard_days))
    report = _format_report(
        leadgen_new=leadgen_new,
        engine_result=engine_result,
        inbox_result=inbox_result,
        scoreboard=board,
        scoreboard_days=int(args.scoreboard_days),
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
        "scoreboard_days": int(args.scoreboard_days),
        "scoreboard": asdict(board),
    }
    summary_sha1 = hashlib.sha1(json.dumps(summary_payload, sort_keys=True).encode("utf-8")).hexdigest()

    last_sent_date = state.get("last_sent_date_utc")
    # Backward compat: older runs wrote last_sent_sha1.
    last_sent_sha1 = state.get("last_summary_sha1") or state.get("last_sent_sha1")

    # If we already sent a report today, only resend when something truly urgent happens.
    # (Outbound send counts are not urgent; they can be reviewed in tomorrow's report.)
    urgent_change = any(
        [
            int(inbox_result.new_replies or 0) > 0,
            int(inbox_result.intake_submissions or 0) > 0,
            int(inbox_result.calendly_bookings or 0) > 0,
            int(inbox_result.stripe_payments or 0) > 0,
        ]
    )

    should_send = False
    if last_sent_date != today_utc:
        should_send = True  # daily heartbeat
    elif summary_sha1 != last_sent_sha1 and urgent_change:
        should_send = True  # urgent update the same day

    if should_send:
        subject = f"CallCatcher Ops Daily Report ({today_utc})"
        _send_email(
            smtp_user=cfg.email["smtp_user"],
            smtp_password=smtp_password,
            to_email=report_to,
            subject=subject,
            body=report,
        )
        _write_json(
            report_state_path,
            {
                "last_sent_date_utc": today_utc,
                "last_summary_sha1": summary_sha1,
                "sent_at_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
            },
        )

    # Helpful for launchd logs.
    print(report)


if __name__ == "__main__":
    main()
