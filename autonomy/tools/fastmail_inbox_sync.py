#!/usr/bin/env python3
import argparse
import imaplib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable

from autonomy.context_store import ContextStore


UTC = timezone.utc

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BOUNCE_SUBJECT_RE = re.compile(
    r"(undeliver|returned to sender|delivery status notification|delivery[ -]status|mail delivery failed|failure)",
    re.IGNORECASE,
)
OPT_OUT_RE = re.compile(r"\b(unsubscribe|opt\s*out|remove me)\b", re.IGNORECASE)


@dataclass
class InboxSyncResult:
    processed_messages: int
    new_bounces: int
    new_replies: int
    new_opt_outs: int
    intake_submissions: int
    calendly_bookings: int
    stripe_payments: int
    last_uid: int


def load_dotenv(path: Path) -> dict:
    env: dict = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def _read_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _iter_text_parts(msg) -> Iterable[str]:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = (part.get_content_type() or "").lower()
            if ctype != "text/plain":
                continue
            try:
                content = part.get_content()
                if isinstance(content, bytes):
                    yield content.decode("utf-8", errors="replace")
                else:
                    yield str(content)
            except Exception:
                continue
        return

    try:
        content = msg.get_content()
        if isinstance(content, bytes):
            yield content.decode("utf-8", errors="replace")
        else:
            yield str(content)
    except Exception:
        return


def _message_text(msg) -> str:
    parts: list[str] = []
    for part in _iter_text_parts(msg):
        if part:
            parts.append(part)
    return "\n".join(parts)


def _is_bounce(from_name: str, from_email: str, subject: str, body: str) -> bool:
    from_name_l = (from_name or "").lower()
    from_email_l = (from_email or "").lower()
    subject_l = (subject or "").lower()
    body_l = (body or "").lower()

    if "mailer-daemon" in from_email_l or "postmaster" in from_email_l:
        return True
    if "mail delivery" in from_name_l:
        return True
    if BOUNCE_SUBJECT_RE.search(subject_l or ""):
        return True
    # Common DSN markers.
    if "final-recipient" in body_l and "diagnostic-code" in body_l:
        return True
    return False


def _extract_failed_recipients(body: str) -> set[str]:
    body = body or ""
    out: set[str] = set()

    # DSN format: "Final-Recipient: rfc822; user@example.com"
    for m in re.finditer(r"Final-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)", body, re.IGNORECASE):
        out.add(m.group(1).strip().lower())
    for m in re.finditer(r"Original-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)", body, re.IGNORECASE):
        out.add(m.group(1).strip().lower())

    # Fallback: any email addresses, filtered later against leads table.
    for m in EMAIL_RE.finditer(body):
        out.add(m.group(0).strip().lower())

    return out


def sync_fastmail_inbox(
    *,
    sqlite_path: Path,
    audit_log: Path,
    fastmail_user: str,
    fastmail_password: str,
    state_path: Path,
    mailbox: str = "INBOX",
    lookback_first_run: int = 200,
) -> InboxSyncResult:
    state = _read_state(state_path)
    last_uid = int(state.get("last_uid") or 0)

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))

    processed = 0
    new_bounces = 0
    new_replies = 0
    new_opt_outs = 0
    intake_submissions = 0
    calendly_bookings = 0
    stripe_payments = 0
    max_uid_seen = last_uid

    imap = imaplib.IMAP4_SSL("imap.fastmail.com", 993)
    try:
        imap.login(fastmail_user, fastmail_password)
        imap.select(mailbox)

        # UIDs are stable; process only newer messages.
        if last_uid > 0:
            typ, data = imap.uid("search", None, f"UID {last_uid + 1}:*")
            uids = (data[0] or b"").split() if typ == "OK" else []
        else:
            typ, data = imap.uid("search", None, "ALL")
            all_uids = (data[0] or b"").split() if typ == "OK" else []
            uids = all_uids[-lookback_first_run:]

        for raw_uid in uids:
            try:
                uid = int(raw_uid)
            except Exception:
                continue
            # Fastmail resolves '*' in UID search sets to the current max UID. When
            # last_uid already equals max UID, a query like `UID {last_uid+1}:*`
            # becomes a reversed range (e.g. 66:65) which includes 65 again.
            # Filter to only strictly-new UIDs so we don't reprocess the last message.
            if uid <= last_uid:
                continue
            max_uid_seen = max(max_uid_seen, uid)

            typ, msg_data = imap.uid("fetch", raw_uid, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue

            raw_bytes = msg_data[0][1]
            msg = BytesParser(policy=policy.default).parsebytes(raw_bytes)

            from_name, from_email = parseaddr(msg.get("From", ""))
            subject = str(msg.get("Subject", "") or "")
            body_text = _message_text(msg)

            processed += 1

            # Intake submissions (formsubmit -> hello inbox)
            if "baseline intake" in subject.lower() and "callcatcher" in subject.lower():
                intake_submissions += 1

            # Calendly booking notifications
            if "calendly" in (from_email or "").lower() or "calendly" in subject.lower():
                calendly_bookings += 1

            # Stripe payment notifications
            if "stripe" in (from_email or "").lower() or "stripe" in subject.lower():
                stripe_payments += 1

            if _is_bounce(from_name, from_email, subject, body_text):
                failed = _extract_failed_recipients(body_text)
                for email_addr in failed:
                    # Only mark if the email exists as a lead.
                    cur_status = store.get_lead_status(email_addr)
                    if not cur_status:
                        continue
                    if cur_status == "replied":
                        continue
                    if cur_status == "bounced":
                        continue
                    if cur_status == "opted_out":
                        continue
                    if store.mark_status_by_email(email_addr, "bounced"):
                        new_bounces += 1
                        store.log_action(
                            agent_id="agent.inbox_sync.v1",
                            action_type="lead.bounce",
                            trace_id=f"imap:{uid}",
                            payload={"lead_id": email_addr, "mailbox": mailbox},
                        )
                continue

            # Replies from a lead email address.
            from_email_norm = (from_email or "").strip().lower()
            if from_email_norm:
                cur_status = store.get_lead_status(from_email_norm)
                if cur_status:
                    if cur_status == "bounced":
                        continue
                    if OPT_OUT_RE.search(body_text or ""):
                        if cur_status == "opted_out":
                            continue
                        store.add_opt_out(from_email_norm)
                        store.mark_status_by_email(from_email_norm, "opted_out")
                        new_opt_outs += 1
                        store.log_action(
                            agent_id="agent.inbox_sync.v1",
                            action_type="lead.opt_out_email",
                            trace_id=f"imap:{uid}",
                            payload={"lead_id": from_email_norm, "mailbox": mailbox},
                        )
                    elif cur_status != "replied":
                        store.mark_status_by_email(from_email_norm, "replied")
                        new_replies += 1
                        store.log_action(
                            agent_id="agent.inbox_sync.v1",
                            action_type="lead.reply",
                            trace_id=f"imap:{uid}",
                            payload={"lead_id": from_email_norm, "mailbox": mailbox},
                        )

        # Persist state only after processing.
        if max_uid_seen > last_uid:
            _write_state(state_path, {"last_uid": max_uid_seen, "updated_at_utc": datetime.now(UTC).isoformat()})
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    return InboxSyncResult(
        processed_messages=processed,
        new_bounces=new_bounces,
        new_replies=new_replies,
        new_opt_outs=new_opt_outs,
        intake_submissions=intake_submissions,
        calendly_bookings=calendly_bookings,
        stripe_payments=stripe_payments,
        last_uid=max_uid_seen,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Fastmail inbox -> update outreach DB (no PII output).")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy_live.sqlite3", help="Path to sqlite DB.")
    parser.add_argument("--audit-log", default="autonomy/state/audit_live.jsonl", help="Audit log path.")
    parser.add_argument("--state", default="autonomy/state/fastmail_sync_state.json", help="Local state file.")
    parser.add_argument("--dotenv", default=".env", help="Path to local .env file.")
    parser.add_argument("--mailbox", default="INBOX", help="Mailbox to scan.")
    args = parser.parse_args()

    env = load_dotenv(Path(args.dotenv))
    user = env.get("FASTMAIL_USER", "")
    # Fastmail typically requires an app password for IMAP; we reuse SMTP_PASSWORD.
    pw = env.get("SMTP_PASSWORD", "")
    if not user or not pw:
        raise SystemExit("Missing FASTMAIL_USER and SMTP_PASSWORD in .env")

    res = sync_fastmail_inbox(
        sqlite_path=Path(args.sqlite),
        audit_log=Path(args.audit_log),
        fastmail_user=user,
        fastmail_password=pw,
        state_path=Path(args.state),
        mailbox=args.mailbox,
    )

    print("Fastmail inbox sync")
    print(f"As-of (UTC): {datetime.now(UTC).replace(microsecond=0).isoformat()}")
    print("")
    print(f"Processed messages: {res.processed_messages}")
    print(f"New bounces marked: {res.new_bounces}")
    print(f"New replies marked: {res.new_replies}")
    print(f"New opt-outs recorded: {res.new_opt_outs}")
    print(f"Intake submissions (heuristic): {res.intake_submissions}")
    print(f"Calendly notices (heuristic): {res.calendly_bookings}")
    print(f"Stripe notices (heuristic): {res.stripe_payments}")
    print(f"State last UID: {res.last_uid}")


if __name__ == "__main__":
    main()
