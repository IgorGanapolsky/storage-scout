#!/usr/bin/env python3
import argparse
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
from autonomy.tools.fastmail_inbox_sync import load_dotenv, sync_fastmail_inbox
from autonomy.tools.scoreboard import load_scoreboard


UTC = timezone.utc


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


def _format_report(*, engine_result: dict, inbox_result, scoreboard, scoreboard_days: int) -> str:
    now_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    lines: list[str] = []
    lines.append("CallCatcher Ops Daily Report")
    lines.append(f"As-of (UTC): {now_utc}")
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
        engine_result=engine_result,
        inbox_result=inbox_result,
        scoreboard=board,
        scoreboard_days=int(args.scoreboard_days),
    )

    report_path = (repo_root / args.report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")

    subject = f"CallCatcher Ops Daily Report ({datetime.now(UTC).date().isoformat()})"
    _send_email(
        smtp_user=cfg.email["smtp_user"],
        smtp_password=smtp_password,
        to_email=report_to,
        subject=subject,
        body=report,
    )

    # Helpful for launchd logs.
    print(report)


if __name__ == "__main__":
    main()
