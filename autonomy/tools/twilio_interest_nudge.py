#!/usr/bin/env python3
"""Send automated SMS nudges to inbound "interested" leads.

This tool nudges high-intent leads that replied via Twilio SMS but have not yet
booked. It is designed to run inside the daily live job with strict limits:
- disabled via env flag
- cooldown between nudges
- opt-out safety checks
- max-per-run cap
"""

from __future__ import annotations

import base64
import contextlib
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore
from autonomy.tools.twilio_inbox_sync import load_twilio_inbox_config
from autonomy.utils import UTC, normalize_us_phone, truthy


@dataclass(frozen=True)
class InterestNudgeConfig:
    account_sid: str
    auth_token: str
    from_number: str
    booking_url: str
    kickoff_url: str
    max_per_run: int
    min_age_minutes: int
    cooldown_hours: int
    lookback_days: int


@dataclass
class InterestNudgeResult:
    reason: str = "ok"
    candidates: int = 0
    attempted: int = 0
    nudged: int = 0
    failed: int = 0
    skipped: int = 0


def _auth_header(account_sid: str, auth_token: str) -> str:
    raw = f"{account_sid}:{auth_token}".encode("utf-8")
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


def _send_sms(*, cfg: InterestNudgeConfig, to_number: str, body: str) -> dict[str, Any]:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
    data = urllib.parse.urlencode({"To": to_number, "From": cfg.from_number, "Body": body}).encode("utf-8")
    headers = {
        "Authorization": _auth_header(cfg.account_sid, cfg.auth_token),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_iso(raw: str) -> datetime | None:
    val = (raw or "").strip()
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _normalize_phone(payload_phone_e164: str, payload_phone_raw: str) -> str:
    p = (payload_phone_e164 or "").strip()
    if p.startswith("+"):
        return p
    return normalize_us_phone(payload_phone_raw)


def _build_nudge_body(*, booking_url: str, kickoff_url: str) -> str:
    return (
        "Quick follow-up: if you want your missed-call recovery baseline, book here: "
        f"{booking_url} "
        "Need priority setup? Reserve kickoff here: "
        f"{kickoff_url} Reply STOP to opt out."
    )


def _already_nudged_recently(
    store: ContextStore,
    *,
    lead_id: str,
    phone_e164: str,
    cutoff_iso: str,
) -> bool:
    if lead_id:
        row = store.conn.execute(
            """
            SELECT 1
            FROM actions
            WHERE action_type='sms.interest_nudge'
              AND ts >= ?
              AND json_extract(payload_json, '$.lead_id') = ?
            LIMIT 1
            """,
            (cutoff_iso, lead_id),
        ).fetchone()
        if row is not None:
            return True
    if phone_e164:
        row = store.conn.execute(
            """
            SELECT 1
            FROM actions
            WHERE action_type='sms.interest_nudge'
              AND ts >= ?
              AND json_extract(payload_json, '$.to_phone_e164') = ?
            LIMIT 1
            """,
            (cutoff_iso, phone_e164),
        ).fetchone()
        if row is not None:
            return True
    return False


def _has_phone_opt_out(store: ContextStore, *, phone_e164: str) -> bool:
    if not phone_e164:
        return False
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type='sms.inbound'
          AND json_extract(payload_json, '$.classification') = 'opt_out'
          AND json_extract(payload_json, '$.from_phone_e164') = ?
        LIMIT 1
        """,
        (phone_e164,),
    ).fetchone()
    return row is not None


def _has_booked_call_after(store: ContextStore, *, lead_id: str, since_iso: str) -> bool:
    if not lead_id:
        return False
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type='call.attempt'
          AND ts >= ?
          AND json_extract(payload_json, '$.lead_id') = ?
          AND json_extract(payload_json, '$.outcome') = 'booked'
        LIMIT 1
        """,
        (since_iso, lead_id),
    ).fetchone()
    return row is not None


def _load_config(env: dict[str, str], *, booking_url: str, kickoff_url: str) -> InterestNudgeConfig | None:
    if not truthy(env.get("AUTO_INTEREST_NUDGE_ENABLED"), default=True):
        return None

    inbox_cfg = load_twilio_inbox_config(env, booking_url=booking_url, kickoff_url=kickoff_url)
    if inbox_cfg is None:
        return None

    return InterestNudgeConfig(
        account_sid=inbox_cfg.account_sid,
        auth_token=inbox_cfg.auth_token,
        from_number=inbox_cfg.from_number,
        booking_url=inbox_cfg.booking_url,
        kickoff_url=inbox_cfg.kickoff_url,
        max_per_run=max(1, int((env.get("AUTO_INTEREST_NUDGE_MAX_PER_RUN") or "6").strip() or 6)),
        min_age_minutes=max(0, int((env.get("AUTO_INTEREST_NUDGE_MIN_AGE_MINUTES") or "120").strip() or 120)),
        cooldown_hours=max(1, int((env.get("AUTO_INTEREST_NUDGE_COOLDOWN_HOURS") or "24").strip() or 24)),
        lookback_days=max(1, int((env.get("AUTO_INTEREST_NUDGE_LOOKBACK_DAYS") or "14").strip() or 14)),
    )


def run_interest_nudges(
    *,
    sqlite_path: Path,
    audit_log: Path,
    env: dict[str, str],
    booking_url: str = "",
    kickoff_url: str = "",
) -> InterestNudgeResult:
    cfg = _load_config(env, booking_url=booking_url, kickoff_url=kickoff_url)
    if cfg is None:
        enabled = truthy(env.get("AUTO_INTEREST_NUDGE_ENABLED"), default=True)
        return InterestNudgeResult(reason="missing_twilio_env" if enabled else "disabled")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    result = InterestNudgeResult()
    now = datetime.now(UTC)
    min_age_cutoff = now - timedelta(minutes=int(cfg.min_age_minutes))
    cooldown_cutoff_iso = (now - timedelta(hours=int(cfg.cooldown_hours))).isoformat()
    lookback_start_iso = (now - timedelta(days=int(cfg.lookback_days))).isoformat()
    msg_body = _build_nudge_body(booking_url=cfg.booking_url, kickoff_url=cfg.kickoff_url)

    try:
        rows = store.conn.execute(
            """
            SELECT
              ts,
              COALESCE(json_extract(payload_json, '$.lead_id'), '') AS lead_id,
              COALESCE(json_extract(payload_json, '$.from_phone_e164'), '') AS from_phone_e164,
              COALESCE(json_extract(payload_json, '$.from_phone'), '') AS from_phone,
              COALESCE(json_extract(payload_json, '$.inbound_sid'), '') AS inbound_sid
            FROM actions
            WHERE action_type='sms.inbound'
              AND ts >= ?
              AND COALESCE(json_extract(payload_json, '$.classification'), '') = 'interested'
            ORDER BY ts DESC
            LIMIT ?
            """,
            (lookback_start_iso, int(cfg.max_per_run) * 5),
        ).fetchall()

        # One nudge candidate per lead/phone per run.
        candidates: list[tuple[str, str, str, str, str]] = []
        seen: set[str] = set()
        for row in rows:
            ts = str(row[0] or "")
            lead_id = str(row[1] or "").strip().lower()
            phone = _normalize_phone(str(row[2] or ""), str(row[3] or ""))
            inbound_sid = str(row[4] or "").strip()
            key = lead_id or phone
            if not key or key in seen:
                continue
            seen.add(key)
            candidates.append((ts, lead_id, phone, inbound_sid, key))
            if len(candidates) >= int(cfg.max_per_run) * 2:
                break

        # Process oldest-first to reduce starvation.
        candidates.sort(key=lambda r: r[0])

        for ts, lead_id, phone_e164, inbound_sid, _ in candidates:
            if result.nudged >= int(cfg.max_per_run):
                break
            result.candidates += 1

            if not phone_e164:
                result.skipped += 1
                continue

            interested_ts = _parse_iso(ts)
            if interested_ts is None or interested_ts > min_age_cutoff:
                result.skipped += 1
                continue

            if (lead_id and store.is_opted_out(lead_id)) or _has_phone_opt_out(store, phone_e164=phone_e164):
                result.skipped += 1
                continue

            if _already_nudged_recently(
                store,
                lead_id=lead_id,
                phone_e164=phone_e164,
                cutoff_iso=cooldown_cutoff_iso,
            ):
                result.skipped += 1
                continue

            if _has_booked_call_after(store, lead_id=lead_id, since_iso=ts):
                result.skipped += 1
                continue

            payload: dict[str, Any] = {
                "lead_id": lead_id,
                "to_phone_e164": phone_e164,
                "source_inbound_sid": inbound_sid,
                "source_interested_ts": ts,
                "booking_url": cfg.booking_url,
                "kickoff_url": cfg.kickoff_url,
                "twilio": {},
            }
            result.attempted += 1

            try:
                resp = _send_sms(cfg=cfg, to_number=phone_e164, body=msg_body)
                sid = str(resp.get("sid") or "").strip()
                payload["twilio"] = {
                    "sid": sid,
                    "status": str(resp.get("status") or ""),
                    "error_code": resp.get("error_code"),
                    "error_message": resp.get("error_message"),
                }
                store.log_action(
                    agent_id="agent.sms.twilio.nudge.v1",
                    action_type="sms.interest_nudge",
                    trace_id=f"twilio_interest_nudge:{sid or inbound_sid or phone_e164}",
                    payload=payload,
                )
                result.nudged += 1
            except Exception as exc:
                payload["error_type"] = type(exc).__name__
                payload["error"] = str(exc)
                store.log_action(
                    agent_id="agent.sms.twilio.nudge.v1",
                    action_type="sms.interest_nudge_failed",
                    trace_id=f"twilio_interest_nudge_failed:{inbound_sid or phone_e164}",
                    payload=payload,
                )
                result.failed += 1
    except Exception as exc:
        result.reason = f"error:{type(exc).__name__}"
    finally:
        with contextlib.suppress(Exception):
            store.conn.close()

    return result

