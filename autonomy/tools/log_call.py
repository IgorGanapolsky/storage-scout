#!/usr/bin/env python3
"""
Log a phone call attempt/outcome against a lead in the autonomy sqlite DB.

This is intentionally lightweight: it does not place calls, it only records them
so daily reporting can measure phone-first execution.
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone
from pathlib import Path

from autonomy.context_store import ContextStore


UTC = timezone.utc

OUTCOMES = (
    "no_answer",
    "voicemail",
    "gatekeeper",
    "spoke",
    "interested",
    "booked",
    "not_interested",
    "wrong_number",
    "do_not_contact",
)


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


def _default_audit_log_path() -> str:
    for candidate in (
        Path("autonomy/state/audit_live.jsonl"),
        Path("autonomy/state/audit.jsonl"),
    ):
        if candidate.exists():
            return str(candidate)
    return "autonomy/state/audit_live.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description="Log a CallCatcher Ops phone touch in the outreach DB.")
    parser.add_argument("--sqlite", default=_default_sqlite_path(), help="Path to sqlite DB.")
    parser.add_argument("--audit-log", default=_default_audit_log_path(), help="Path to audit log.")
    parser.add_argument("--email", required=True, help="Lead email (lead_id is normalized email).")
    parser.add_argument("--outcome", required=True, choices=OUTCOMES, help="Call outcome.")
    parser.add_argument("--notes", default="", help="Optional notes (short).")
    parser.add_argument("--attempted-at", default="", help="Optional ISO timestamp override (UTC).")
    args = parser.parse_args()

    email_norm = (args.email or "").strip().lower()
    if "@" not in email_norm:
        raise SystemExit("Invalid --email (expected an email address)")

    store = ContextStore(sqlite_path=str(Path(args.sqlite)), audit_log=str(Path(args.audit_log)))
    cur_status = store.get_lead_status(email_norm)
    if not cur_status:
        raise SystemExit(f"Lead not found for email: {email_norm}")

    row = store.conn.execute(
        "SELECT COALESCE(company,''), COALESCE(service,''), COALESCE(phone,''), COALESCE(city,''), COALESCE(state,'') FROM leads WHERE id=?",
        (email_norm,),
    ).fetchone()
    company, service, phone, city, state = (row or ("", "", "", "", ""))

    attempted_at = (args.attempted_at or "").strip() or _now_utc_iso()

    outcome = str(args.outcome or "").strip().lower()
    notes = (args.notes or "").strip()

    # Minimal status updates to reduce spam/duplicate touches:
    # - new -> contacted once we've attempted a call
    # - do_not_contact -> opted_out
    # - booked/interested -> replied (treated as "engaged" in the system)
    if outcome == "do_not_contact":
        store.add_opt_out(email_norm)
        store.mark_status_by_email(email_norm, "opted_out")
    elif outcome in {"booked", "interested"}:
        store.mark_status_by_email(email_norm, "replied")
    elif cur_status == "new":
        store.mark_contacted(email_norm)

    store.log_action(
        agent_id="agent.phone_ops.v1",
        action_type="call.attempt",
        trace_id=f"call:{uuid.uuid4()}",
        payload={
            "lead_id": email_norm,
            "attempted_at": attempted_at,
            "outcome": outcome,
            "notes": notes,
            "company": company,
            "service": service,
            "phone": phone,
            "city": city,
            "state": state,
        },
    )

    print("Logged call attempt")
    print(f"As-of (UTC): {_now_utc_iso()}")
    print(f"lead_id: {email_norm}")
    print(f"outcome: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
