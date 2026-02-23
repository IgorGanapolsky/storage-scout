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
import contextlib
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore
from autonomy.utils import UTC, normalize_us_phone, state_tz, truthy

# Re-export for backward compatibility (tests import this name).
normalize_phone = normalize_us_phone


def _is_business_hours(state: str, start_hour: int, end_hour: int, *, allow_weekends: bool = False) -> bool:
    """Keep local wrapper for monkeypatch-friendly tests and stable behavior."""
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        return True

    tz_name = state_tz(state)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")

    now_local = datetime.now(tz)
    if not bool(allow_weekends) and now_local.weekday() >= 5:
        return False
    return int(start_hour) <= int(now_local.hour) < int(end_hour)


def _default_sms_body(booking_url: str) -> str:
    return (
        "Hi, this is CallCatcher Ops. We help dental practices recover "
        "missed calls with instant text-back + callback automation. "
        f"Book a free 5-min baseline: {booking_url} "
        "Reply STOP to opt out."
    )


def _default_sms_second_nudge_body(booking_url: str) -> str:
    return (
        "Quick follow-up from CallCatcher Ops. If missed-call recovery is still a priority, "
        f"grab a 5-min baseline slot here: {booking_url} "
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
    allow_weekends: bool = False
    second_nudge_enabled: bool = False
    second_nudge_min_hours: int = 6
    second_nudge_max_per_run: int = 3
    second_nudge_body: str = ""


def load_sms_config(env: dict[str, str], booking_url: str = "") -> TwilioSmsConfig | None:
    if not truthy(env.get("AUTO_SMS_ENABLED") or ""):
        return None
    sid = (env.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (env.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (env.get("TWILIO_SMS_FROM_NUMBER") or env.get("TWILIO_FROM_NUMBER") or "").strip()
    if not sid or not token or not from_num or not from_num.startswith("+"):
        return None

    body = (env.get("AUTO_SMS_BODY") or "").strip()
    if not body:
        url = booking_url or "https://calendly.com/igorganapolsky/audit-call"
        body = _default_sms_body(url)
    second_nudge_body = (env.get("AUTO_SMS_SECOND_NUDGE_BODY") or "").strip()
    if not second_nudge_body:
        url = booking_url or "https://calendly.com/igorganapolsky/audit-call"
        second_nudge_body = _default_sms_second_nudge_body(url)

    return TwilioSmsConfig(
        account_sid=sid,
        auth_token=token,
        from_number=from_num,
        body=body,
        max_per_run=int((env.get("AUTO_SMS_MAX_PER_RUN") or "20").strip() or 20),
        cooldown_days=int((env.get("AUTO_SMS_COOLDOWN_DAYS") or "7").strip() or 7),
        start_hour=int((env.get("AUTO_SMS_START_HOUR_LOCAL") or "9").strip() or 9),
        end_hour=int((env.get("AUTO_SMS_END_HOUR_LOCAL") or "17").strip() or 17),
        allow_weekends=truthy(env.get("AUTO_SMS_ALLOW_WEEKENDS"), default=False),
        second_nudge_enabled=truthy(env.get("AUTO_SMS_SECOND_NUDGE_ENABLED"), default=False),
        second_nudge_min_hours=max(1, int((env.get("AUTO_SMS_SECOND_NUDGE_MIN_HOURS") or "6").strip() or 6)),
        second_nudge_max_per_run=max(0, int((env.get("AUTO_SMS_SECOND_NUDGE_MAX_PER_RUN") or "3").strip() or 3)),
        second_nudge_body=second_nudge_body,
    )


def _auth_header(cfg: TwilioSmsConfig) -> str:
    raw = f"{cfg.account_sid}:{cfg.auth_token}".encode()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"Basic {b64}"


def send_sms(cfg: TwilioSmsConfig, *, to_number: str, body_override: str | None = None) -> dict[str, Any]:
    body = (body_override or "").strip() or cfg.body
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
    data = urllib.parse.urlencode({
        "To": to_number,
        "From": cfg.from_number,
        "Body": body,
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


def _is_opted_out(store: ContextStore, email: str) -> bool:
    row = store.conn.execute(
        "SELECT 1 FROM opt_outs WHERE email = ? LIMIT 1",
        (email,),
    ).fetchone()
    return row is not None


def _has_inbound_reply_since(store: ContextStore, *, lead_id: str, since_iso: str) -> bool:
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type='sms.inbound'
          AND json_extract(payload_json, '$.lead_id') = ?
          AND ts > ?
        LIMIT 1
        """,
        (lead_id, since_iso),
    ).fetchone()
    return row is not None


def _has_conversion_since(store: ContextStore, *, lead_id: str, since_iso: str) -> bool:
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type IN ('conversion.booking', 'conversion.payment')
          AND json_extract(payload_json, '$.lead_id') = ?
          AND ts > ?
        LIMIT 1
        """,
        (lead_id, since_iso),
    ).fetchone()
    return row is not None


def _second_nudge_already_sent_since(store: ContextStore, *, lead_id: str, since_iso: str) -> bool:
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type='sms.attempt'
          AND json_extract(payload_json, '$.lead_id') = ?
          AND COALESCE(json_extract(payload_json, '$.phase'), '') = 'second_nudge'
          AND ts >= ?
        LIMIT 1
        """,
        (lead_id, since_iso),
    ).fetchone()
    return row is not None


def _load_second_nudge_candidates(store: ContextStore, *, min_hours: int, max_rows: int) -> list[sqlite3.Row]:
    threshold_iso = (datetime.now(UTC) - timedelta(hours=max(1, int(min_hours)))).isoformat()
    floor_iso = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    return store.conn.execute(
        """
        SELECT
            json_extract(payload_json, '$.lead_id') as lead_id,
            json_extract(payload_json, '$.phone') as phone,
            json_extract(payload_json, '$.company') as company,
            json_extract(payload_json, '$.service') as service,
            json_extract(payload_json, '$.city') as city,
            json_extract(payload_json, '$.state') as state,
            MAX(ts) as last_sms_ts
        FROM actions
        WHERE action_type='sms.attempt'
          AND agent_id='agent.sms.twilio.v1'
          AND ts >= ?
          AND ts <= ?
          AND COALESCE(json_extract(payload_json, '$.outcome'), '') = 'delivered'
          AND COALESCE(json_extract(payload_json, '$.phase'), 'initial') = 'initial'
        GROUP BY json_extract(payload_json, '$.lead_id')
        ORDER BY last_sms_ts ASC
        LIMIT ?
        """,
        (floor_iso, threshold_iso, max(0, int(max_rows))),
    ).fetchall()


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
        enabled = truthy(env.get("AUTO_SMS_ENABLED") or "")
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

        # Skip if lead already replied via SMS today (avoid double-messaging)
        if _has_inbound_reply_since(store, lead_id=lead_id, since_iso=today_start):
            result.skipped += 1
            continue

        if not _is_business_hours(state, cfg.start_hour, cfg.end_hour, allow_weekends=cfg.allow_weekends):
            result.skipped += 1
            continue

        now_iso = datetime.now(UTC).isoformat()
        payload: dict[str, Any] = {
            "lead_id": lead_id,
            "attempted_at": now_iso,
            "outcome": "pending",
            "phase": "initial",
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
            with contextlib.suppress(Exception):
                error_body = exc.read().decode("utf-8", errors="replace")
            error_data: dict[str, Any] = {}
            with contextlib.suppress(Exception):
                error_data = json.loads(error_body)
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

    if cfg.second_nudge_enabled and cfg.second_nudge_max_per_run > 0:
        candidates = _load_second_nudge_candidates(
            store,
            min_hours=cfg.second_nudge_min_hours,
            max_rows=cfg.second_nudge_max_per_run,
        )
        for row in candidates:
            lead_id = str(row["lead_id"] or "").strip().lower()
            if not lead_id:
                result.skipped += 1
                continue
            phone_raw = str(row["phone"] or "")
            phone = normalize_phone(phone_raw)
            if not phone:
                result.skipped += 1
                continue
            if _is_opted_out(store, lead_id):
                result.skipped += 1
                continue

            last_sms_ts = str(row["last_sms_ts"] or "")
            if not last_sms_ts:
                result.skipped += 1
                continue
            if _has_inbound_reply_since(store, lead_id=lead_id, since_iso=last_sms_ts):
                result.skipped += 1
                continue
            if _has_conversion_since(store, lead_id=lead_id, since_iso=last_sms_ts):
                result.skipped += 1
                continue
            if _second_nudge_already_sent_since(store, lead_id=lead_id, since_iso=last_sms_ts):
                result.skipped += 1
                continue

            state = str(row["state"] or "")
            if not _is_business_hours(state, cfg.start_hour, cfg.end_hour, allow_weekends=cfg.allow_weekends):
                result.skipped += 1
                continue

            now_iso = datetime.now(UTC).isoformat()
            payload: dict[str, Any] = {
                "lead_id": lead_id,
                "attempted_at": now_iso,
                "outcome": "pending",
                "phase": "second_nudge",
                "company": str(row["company"] or ""),
                "service": str(row["service"] or ""),
                "phone": phone_raw,
                "city": str(row["city"] or ""),
                "state": state,
                "prior_sms_ts": last_sms_ts,
                "twilio": {},
            }

            try:
                resp = send_sms(cfg, to_number=phone, body_override=cfg.second_nudge_body)
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
                with contextlib.suppress(Exception):
                    error_body = exc.read().decode("utf-8", errors="replace")
                error_data: dict[str, Any] = {}
                with contextlib.suppress(Exception):
                    error_data = json.loads(error_body)
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
            store.log_action(
                agent_id="agent.sms.twilio.v1",
                action_type="sms.attempt",
                trace_id=f"twilio_sms:{payload['twilio'].get('sid', now_iso)}",
                payload=payload,
            )

    with contextlib.suppress(Exception):
        store.conn.close()

    return result
