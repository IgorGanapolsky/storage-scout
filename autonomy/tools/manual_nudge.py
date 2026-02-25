#!/usr/bin/env python3
import os
import sqlite3
import json
import base64
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Constants and Configuration
SQLITE_PATH = "autonomy/state/autonomy_live.sqlite3"
BOOKING_URL = "https://calendly.com/igorganapolsky/audit-call"
KICKOFF_URL = "https://buy.stripe.com/4gMaEX0I4f5IdWh6i73sI01"

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()

def _auth_header(sid, token):
    raw = f"{sid}:{token}".encode("utf-8")
    return f"Basic {base64.b64encode(raw).decode('ascii')}"

def send_sms(sid, token, from_num, to_num, body):
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode({"To": to_num, "From": from_num, "Body": body}).encode("utf-8")
    headers = {
        "Authorization": _auth_header(sid, token),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))

def log_action(conn, agent_id, action_type, trace_id, payload):
    ts = now_utc_iso()
    payload_json = json.dumps(payload)
    conn.execute(
        "INSERT INTO actions (agent_id, action_type, trace_id, ts, payload_json) VALUES (?, ?, ?, ?, ?)",
        (agent_id, action_type, trace_id, ts, payload_json),
    )
    conn.commit()

def main():
    # Load env
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_num = os.environ.get("TWILIO_SMS_FROM_NUMBER") or os.environ.get("TWILIO_FROM_NUMBER")
    
    if not sid or not token or not from_num:
        print("Error: Missing Twilio credentials in environment.")
        return

    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    
    # 1. Get high-intent 'replied' leads
    leads = conn.execute(
        "SELECT id, company, phone, email, status FROM leads WHERE status='replied'"
    ).fetchall()
    
    if not leads:
        print("No leads in 'replied' status found.")
        return

    print(f"Found {len(leads)} high-intent leads to nudge.")
    
    body = (
        "Quick follow-up: if you want your missed-call recovery baseline, book here: "
        f"{BOOKING_URL} "
        "Need priority setup? Reserve kickoff here: "
        f"{KICKOFF_URL} Reply STOP to opt out."
    )

    for lead in leads:
        lead_id = lead["id"]
        to_phone = lead["phone"]
        company = lead["company"]
        email = lead["email"]
        
        # Check opt-out
        opt_out = conn.execute("SELECT 1 FROM opt_outs WHERE email=?", (email,)).fetchone()
        if opt_out:
            print(f"Skipping {company} - opted out.")
            continue

        print(f"Nudging {company} ({to_phone})...")
        try:
            resp = send_sms(sid, token, from_num, to_phone, body)
            msg_sid = resp.get("sid")
            print(f"Success: {msg_sid}")
            
            log_action(conn, "agent.manual.nudge.v1", "sms.manual_nudge", f"manual_nudge:{msg_sid}", {
                "lead_id": lead_id,
                "company": company,
                "to_phone": to_phone,
                "twilio_sid": msg_sid,
                "status": resp.get("status")
            })
            
        except Exception as e:
            print(f"Failed to nudge {company}: {e}")

    conn.close()

if __name__ == "__main__":
    main()
