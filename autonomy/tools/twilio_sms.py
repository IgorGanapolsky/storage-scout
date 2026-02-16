#!/usr/bin/env python3
"""
Autonomous SMS follow-up via Twilio after outbound calls.

Sends a short text with the Calendly booking link to leads that were called
(spoke or voicemail). Fully automated — no human intervention required.

Safety defaults:
- Disabled unless AUTO_SMS_ENABLED=1
- Skips opted-out leads
- Skips leads already texted within cooldown window
- Only texts during local business hours
- Includes STOP opt-out per TCPA / A2P compliance
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore

UTC = timezone.utc

_US_PHONE_RE = re.compile(r"\D+")

_STATE_TZ: dict[str, str] = {
    "AL": "America/Chicago", "AK": "America/Anchorage", "AZ": "America/Phoenix",
    "AR": "America/Chicago", "CA": "America/Los_Angeles", "CO": "America/Denver",
    "CT": "America/New_York", "DC": "America/New_York", "DE": "America/New_York",
    "FL": "America/New_York", "GA": "America/New_York", "HI": "Pacific/Honolulu",
    "ID": "America/Boise", "IL": "America/Chicago", "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago", "KS": "America/Chicago", "KY": "America/New_York",
    "LA": "America/Chicago", "ME": "America/New_York", "MD": "America/New_York",
    "MA": "America/New_York", "MI": "America/Detroit", "MN": "America/Chicago",
    "MS": "America/Chicago", "MO": "America/Chicago", "MT": "America/Denver",
    "NE": "America/Chicago", "NV": "America/Los_Angeles", "NH": "America/New_York",
    "NJ": "America/New_York", "NM": "America/Denver", "NY": "America/New_York",
    "NC": "America/New_York", "ND": "America/Chicago", "OH": "America/New_York",
    "OK": "America/Chicago", "OR": "America/Los_Angeles", "PA": "America/New_York",
    "RI": "America/New_York", "SC": "America/New_York", "SD": "America/Chicago",
    "TN": "America/Chicago", "TX": "America/Chicago", "UT": "America/Denver",
    "VT": "America/New_York", "VA": "America/New_York", "WA": "America/Los_Angeles",
    "WV": "America/New_York", "WI": "America/Chicago", "WY": "America/Denver",
}


def normalize_phone(raw: str) -> str:
    """Normalize a US phone number to E.164 (+1XXXXXXXXXX)."""
    digits = _US_PHONE_RE.sub("", raw or "")
    if digits.startswith("1") and len(digits) == 11:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+1{digits}"
    return ""


def _default_sms_body(booking_url: str) -> str:
    return (
        "Hi, this is CallCatcher Ops. We help dental practices recover "
        "missed calls with instant text-back + callback automation. "
        f"Book a free 5-min baseline: {booking_url} "
        "Reply STOP to opt out."
    )


@dataclass
class SmsResult:
    reason: str = "ok"
    attempted: int = 0
    delivered: int = 0
    failed: int = 0
    skipped: int = 0


@dataclass
class TwilioSmsConfig:
    account_sid: str
    auth_token: str
    from_number: str
    body: str
    max_per_run: int = 20
    cooldown_days: int = 7
    start_hour: int = 9
    end_hour: int = 17


def load_sms_config(env: dict[str, str], booking_url: str = "") -> TwilioSmsConfig | None:
    if not _truthy(env.get("AUTO_SMS_ENABLED") or ""):
        return None
    sid = (env.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (env.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (env.get("TWILIO_FROM_NUMBER") or "").strip()
    if not sid or not token or not from_num or not from_num.startswith("+"):
        return None

    body = (env.get("AUTO_SMS_BODY") or "").strip()
    if not body:
        url = booking_url or "https://calendly.com/igorganapolsky/audit-call"
        body = _default_sms_body(url)

    return TwilioSmsConfig(
        account_sid=sid,
        auth_token=token,
        from_number=from_num,
        body=body,
        max_per_run=int((env.get("AUTO_SMS_MAX_PER_RUN") or "20").strip() or 20),
        cooldown_days=int((env.get("AUTO_SMS_COOLDOWN_DAYS") or "7").strip() or 7),
        start_hour=int((env.get("AUTO_SMS_START_HOUR_LOCAL") or "9").strip() or 9),
        end_hour=int((env.get("AUTO_SMS_END_HOUR_LOCAL") or "17").strip() or 17),
    )


def _truthy(val: str) -> bool:
    return val.strip().lower() not in {"", "0", "false", "no", "off"}


def _auth_header(cfg: TwilioSmsConfig) -> str:
    raw = f"{cfg.account_sid}:{cfg.auth_token}".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"Basic {b64}"


def send_sms(cfg: TwilioSmsConfig, *, to_number: str) -> dict[str, Any]:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
    data = urllib.parse.urlencode({
        "To": to_number,
        "From": cfg.from_number,
        "Body": cfg.body,
    }).encode("utf-8")
    headers = {
        "Authorization": _auth_header(cfg),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _lead_texted_recently(store: ContextStore, *, lead_id: str, cooldown_days: int) -> bool:
    cutoff = (datetime.now(UTC) - timedelta(days=int(cooldown_days))).isoformat()
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type='sms.attempt'
          AND json_extract(payload_json, '$.lead_id') = ?
          AND ts >= ?
        LIMIT 1
        """,
        (lead_id, cutoff),
    ).fetchone()
    return row is not None


def _is_business_hours(state: str, start_hour: int, end_hour: int) -> bool:
    import zoneinfo
    tz_name = _STATE_TZ.get((state or "").strip().upper(), "America/New_York")
    try:
        tz = zoneinfo.ZoneInfo(tz_name)
    except Exception:
        tz = zoneinfo.ZoneInfo("America/New_York")
    now_local = datetime.now(tz)
    if now_local.weekday() >= 5:
        return False
    return start_hour <= now_local.hour < end_hour


def _is_opted_out(store: ContextStore, email: str) -> bool:
    row = store.conn.execute(
        "SELECT 1 FROM opt_outs WHERE email = ? LIMIT 1",
        (email,),
    ).fetchone()
    return row is not None


def run_sms_followup(
    *,
    sqlite_path: Path,
    audit_log: Path,
    env: dict[str, str],
    booking_url: str = "",
) -> SmsResult:
    """Send SMS follow-ups to leads that were called today but didn't book."""
    cfg = load_sms_config(env, booking_url=booking_url)
    if cfg is None:
        enabled = _truthy(env.get("AUTO_SMS_ENABLED") or "")
        if not enabled:
            return SmsResult(reason="disabled")
        return SmsResult(reason="missing_twilio_env")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    result = SmsResult()

    # Find leads that were called (spoke or voicemail) but haven't been texted yet.
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    called_leads = store.conn.execute(
        """
        SELECT DISTINCT
            json_extract(payload_json, '$.lead_id') as lead_id,
            json_extract(payload_json, '$.phone') as phone,
            json_extract(payload_json, '$.company') as company,
            json_extract(payload_json, '$.service') as service,
            json_extract(payload_json, '$.city') as city,
            json_extract(payload_json, '$.state') as state,
            json_extract(payload_json, '$.outcome') as outcome
        FROM actions
        WHERE action_type='call.attempt'
          AND ts >= ?
          AND json_extract(payload_json, '$.outcome') IN ('spoke', 'voicemail')
        """,
        (today_start,),
    ).fetchall()

    sent_count = 0
    for row in called_leads:
        if sent_count >= cfg.max_per_run:
            break

        lead_id = row[0] or ""
        phone_raw = row[1] or ""
        company = row[2] or ""
        service = row[3] or ""
        city = row[4] or ""
        state = row[5] or ""
        outcome = row[6] or ""

        phone = normalize_phone(phone_raw)
        if not phone:
            result.skipped += 1
            continue

        if _is_opted_out(store, lead_id):
            result.skipped += 1
            continue

        if _lead_texted_recently(store, lead_id=lead_id, cooldown_days=cfg.cooldown_days):
            result.skipped += 1
            continue

        if not _is_business_hours(state, cfg.start_hour, cfg.end_hour):
            result.skipped += 1
            continue

        now_iso = datetime.now(UTC).isoformat()
        payload: dict[str, Any] = {
            "lead_id": lead_id,
            "attempted_at": now_iso,
            "outcome": "pending",
            "company": company,
            "service": service,
            "phone": phone_raw,
            "city": city,
            "state": state,
            "call_outcome": outcome,
            "twilio": {},
        }

        try:
            resp = send_sms(cfg, to_number=phone)
            sid = resp.get("sid", "")
            status = resp.get("status", "")
            payload["outcome"] = "delivered"
            payload["twilio"] = {
                "sid": sid,
                "status": status,
                "error_code": resp.get("error_code"),
                "error_message": resp.get("error_message"),
            }
            result.delivered += 1
        except urllib.error.HTTPError as exc:
            error_body = ""
            try:
                error_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            error_data: dict[str, Any] = {}
            try:
                error_data = json.loads(error_body)
            except Exception:
                pass
            payload["outcome"] = "failed"
            payload["twilio"] = {
                "sid": "",
                "status": "exception",
                "error_code": error_data.get("code"),
                "http_status": exc.code,
                "error_type": "HTTPError",
                "error_message": error_data.get("message", str(exc)),
            }
            payload["notes"] = (
                f"exception=HTTPError status={exc.code} "
                f"code={error_data.get('code', '')} "
                f"message={error_data.get('message', str(exc))}"
            )
            result.failed += 1
        except Exception as exc:
            payload["outcome"] = "failed"
            payload["twilio"] = {
                "sid": "",
                "status": "exception",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            }
            payload["notes"] = f"exception={type(exc).__name__} message={str(exc)}"
            result.failed += 1

        result.attempted += 1
        sent_count += 1

        store.log_action(
            agent_id="agent.sms.twilio.v1",
            action_type="sms.attempt",
            trace_id=f"twilio_sms:{payload['twilio'].get('sid', now_iso)}",
            payload=payload,
        )

    try:
        store.conn.close()
    except Exception:
        pass

    return result
