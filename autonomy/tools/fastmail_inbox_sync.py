#!/usr/bin/env python3
import argparse
import contextlib
import imaplib
import json
import time
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path

from autonomy.agents import LeadScorer
from autonomy.context_store import ContextStore, Lead
from autonomy.utils import EMAIL_SEARCH_RE

UTC = timezone.utc
BOUNCE_SUBJECT_RE = re.compile(
    r"(undeliver|returned to sender|delivery status notification|delivery[ -]status|mail delivery failed|failure)",
    re.IGNORECASE,
)
OPT_OUT_RE = re.compile(r"\b(unsubscribe|opt\s*out|remove me)\b", re.IGNORECASE)
CALENDLY_SUBJECT_RE = re.compile(
    r"(calendly|invitation:|scheduled with|rescheduled|cancelled event)",
    re.IGNORECASE,
)
CALENDLY_BODY_RE = re.compile(r"(calendly\.com/|you are scheduled|new event type)", re.IGNORECASE)
STRIPE_SUBJECT_RE = re.compile(
    r"(charge\.succeeded|invoice\.paid|payment succeeded|receipt for your payment)",
    re.IGNORECASE,
)
STRIPE_BODY_RE = re.compile(
    r"(stripe\.com/receipts|checkout\.stripe\.com/pay/|view your invoice|payment_intent\.succeeded|checkout\.session\.completed)",
    re.IGNORECASE,
)

IMAP_TIMEOUT_SECS = 20
IMAP_CONNECT_RETRIES = 3
IMAP_RETRY_DELAY_SECS = 5


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


def _parse_intake_body(body: str) -> dict[str, str]:
    """Parse FormSubmit-style 'Field: Value' pairs from email body."""
    out = {}
    lines = (body or "").splitlines()
    for line in lines:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        key = k.strip().lower()
        val = v.strip()
        if key in ("name", "full name"):
            out["name"] = val
        elif key in ("email", "e-mail"):
            out["email"] = val
        elif key in ("phone", "telephone", "cell"):
            out["phone"] = val
        elif key in ("company", "business", "practice"):
            out["company"] = val
        elif key in ("service", "industry"):
            out["service"] = val
        elif key in ("city", "location"):
            out["city"] = val
        elif key in ("state", "province"):
            out["state"] = val
    return out


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
    return bool("final-recipient" in body_l and "diagnostic-code" in body_l)


def _extract_failed_recipients(body: str) -> set[str]:
    body = body or ""
    out: set[str] = set()

    # DSN format: "Final-Recipient: rfc822; user@example.com"
    for m in re.finditer(r"Final-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)", body, re.IGNORECASE):
        out.add(m.group(1).strip().lower())
    for m in re.finditer(r"Original-Recipient:\s*rfc822;\s*([^\s<>]+@[^\s<>]+)", body, re.IGNORECASE):
        out.add(m.group(1).strip().lower())

    # Fallback: any email addresses, filtered later against leads table.
    for m in EMAIL_SEARCH_RE.finditer(body):
        out.add(m.group(0).strip().lower())

    return out


def _looks_like_calendly_booking(from_email: str, subject: str, body: str) -> bool:
    sender = (from_email or "").strip().lower()
    if "calendly" in sender:
        return True
    return bool(CALENDLY_SUBJECT_RE.search(subject or "") or CALENDLY_BODY_RE.search(body or ""))


def _looks_like_stripe_payment(from_email: str, subject: str, body: str) -> bool:
    sender = (from_email or "").strip().lower()
    if "stripe" in sender:
        return True
    return bool(STRIPE_SUBJECT_RE.search(subject or "") or STRIPE_BODY_RE.search(body or ""))


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
    scorer = LeadScorer()

    processed = 0
    new_bounces = 0
    new_replies = 0
    new_opt_outs = 0
    intake_submissions = 0
    calendly_bookings = 0
    stripe_payments = 0
    max_uid_seen = last_uid

    # Retry IMAP connection to handle intermittent TLS failures.
    imap = None
    last_err: Exception | None = None
    for attempt in range(IMAP_CONNECT_RETRIES):
        try:
            imap = imaplib.IMAP4_SSL("imap.fastmail.com", 993, timeout=IMAP_TIMEOUT_SECS)
            break
        except TypeError:
            imap = imaplib.IMAP4_SSL("imap.fastmail.com", 993)
            break
        except Exception as exc:
            last_err = exc
            if attempt < IMAP_CONNECT_RETRIES - 1:
                time.sleep(IMAP_RETRY_DELAY_SECS * (attempt + 1))
    if imap is None:
        raise last_err or OSError("IMAP connection failed after retries")
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

            # Bounces MUST be checked first — bounce bodies contain our original
            # outreach email (with Calendly/Stripe links), which would otherwise
            # trigger false-positive booking/payment detections.
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

            # Intake submissions (formsubmit -> hello inbox)
            if "baseline intake" in subject.lower() and "callcatcher" in subject.lower():
                intake_submissions += 1
                data = _parse_intake_body(body_text)
                if data.get("email"):
                    email = data["email"].strip().lower()
                    lead = Lead(
                        id=email,
                        name=data.get("name", ""),
                        company=data.get("company", ""),
                        email=email,
                        phone=data.get("phone", ""),
                        service=data.get("service", ""),
                        city=data.get("city", ""),
                        state=data.get("state", ""),
                        source="intake",
                        status="new",
                    )
                    lead.score = scorer.score(lead)
                    store.upsert_lead(lead)
                    store.log_action(
                        agent_id="agent.inbox_sync.v1",
                        action_type="lead.intake_scored",
                        trace_id=f"imap:intake:{uid}",
                        payload={
                            "email": email,
                            "score": lead.score,
                            "mailbox": mailbox,
                            "message_uid": uid,
                        },
                    )

            is_calendly_notice = _looks_like_calendly_booking(from_email, subject, body_text)
            is_stripe_notice = _looks_like_stripe_payment(from_email, subject, body_text)

            # Calendly booking notifications
            if is_calendly_notice:
                calendly_bookings += 1
                store.log_action(
                    agent_id="agent.inbox_sync.v1",
                    action_type="conversion.booking",
                    trace_id=f"imap:booking:{uid}",
                    payload={"mailbox": mailbox, "source": "fastmail", "message_uid": uid},
                )

            # Stripe payment notifications
            if is_stripe_notice:
                stripe_payments += 1
                store.log_action(
                    agent_id="agent.inbox_sync.v1",
                    action_type="conversion.payment",
                    trace_id=f"imap:payment:{uid}",
                    payload={"mailbox": mailbox, "source": "fastmail", "message_uid": uid},
                )

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
                        triggered_by_step = store.get_last_email_step(from_email_norm)
                        store.log_action(
                            agent_id="agent.inbox_sync.v1",
                            action_type="lead.reply",
                            trace_id=f"imap:{uid}",
                            payload={
                                "lead_id": from_email_norm,
                                "mailbox": mailbox,
                                "triggered_by_step": triggered_by_step,
                            },
                        )

        # Persist state only after processing.
        if max_uid_seen > last_uid:
            _write_state(state_path, {"last_uid": max_uid_seen, "updated_at_utc": datetime.now(UTC).isoformat()})
    finally:
        with contextlib.suppress(Exception):
            imap.logout()

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
