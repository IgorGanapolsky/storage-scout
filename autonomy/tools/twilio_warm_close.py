#!/usr/bin/env python3
"""Send autonomous close-loop SMS to warm leads.

Targets high-intent leads (default: replied/interested) with a direct booking +
paid kickoff CTA. Designed to run inside live_job with explicit daily caps.
"""

from __future__ import annotations

import base64
import contextlib
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore
from autonomy.tools.agent_commerce import request_json
from autonomy.tools.twilio_inbox_sync import load_twilio_inbox_config
from autonomy.utils import UTC, normalize_us_phone, truthy


@dataclass(frozen=True)
class WarmCloseConfig:
    account_sid: str
    auth_token: str
    from_number: str
    booking_url: str
    kickoff_url: str
    statuses: tuple[str, ...]
    max_per_run: int
    min_score: int
    cooldown_hours: int
    lookback_days: int


@dataclass
class WarmCloseResult:
    reason: str = "ok"
    candidates: int = 0
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    converted_skipped: int = 0


def _auth_header(account_sid: str, auth_token: str) -> str:
    raw = f"{account_sid}:{auth_token}".encode("utf-8")
    return f"Basic {base64.b64encode(raw).decode('ascii')}"


def _send_sms(
    *,
    cfg: WarmCloseConfig,
    to_number: str,
    body: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/Messages.json"
    data = urllib.parse.urlencode({"To": to_number, "From": cfg.from_number, "Body": body}).encode("utf-8")
    headers = {
        "Authorization": _auth_header(cfg.account_sid, cfg.auth_token),
        "Content-Type": "application/x-www-form-urlencoded",
    }
    return request_json(
        method="POST",
        url=url,
        headers=headers,
        payload=data,
        timeout_secs=20,
        agent_id="agent.sms.twilio.warm_close.v1",
        env=env,
        urlopen_func=urllib.request.urlopen,
    )


def _parse_iso(raw: str) -> datetime | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _normalize_phone(phone_raw: str) -> str:
    phone = normalize_us_phone(phone_raw)
    return phone if phone.startswith("+") else ""


def _build_close_body(*, booking_url: str, kickoff_url: str) -> str:
    return (
        "Quick close loop: if you want your AI visibility baseline, book here: "
        f"{booking_url} "
        "If you're ready to start this week, reserve kickoff here: "
        f"{kickoff_url} Reply STOP to opt out."
    )


def _already_closed_recently(
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
            WHERE action_type='sms.warm_close'
              AND ts >= ?
              AND COALESCE(json_extract(payload_json, '$.lead_id'), '') = ?
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
            WHERE action_type='sms.warm_close'
              AND ts >= ?
              AND COALESCE(json_extract(payload_json, '$.to_phone_e164'), '') = ?
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


def has_conversion_after(store: ContextStore, *, lead_id: str, since_iso: str) -> bool:
    if not lead_id:
        return False
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE ts >= ?
          AND (
            (action_type='call.attempt'
             AND COALESCE(json_extract(payload_json, '$.lead_id'), '') = ?
             AND COALESCE(json_extract(payload_json, '$.outcome'), '') = 'booked')
            OR
            (action_type IN ('conversion.booking', 'conversion.payment')
             AND COALESCE(json_extract(payload_json, '$.lead_id'), '') = ?)
          )
        LIMIT 1
        """,
        (since_iso, lead_id, lead_id),
    ).fetchone()
    return row is not None


def _parse_statuses(raw: str | None) -> tuple[str, ...]:
    values = tuple(
        sorted(
            {
                str(part).strip().lower()
                for part in str(raw or "").split(",")
                if str(part).strip()
            }
        )
    )
    return values or ("interested", "replied")


def _load_config(env: dict[str, str], *, booking_url: str, kickoff_url: str) -> WarmCloseConfig | None:
    if not truthy(env.get("AUTO_WARM_CLOSE_ENABLED"), default=True):
        return None

    inbox_cfg = load_twilio_inbox_config(env, booking_url=booking_url, kickoff_url=kickoff_url)
    if inbox_cfg is None:
        return None

    min_score_raw = (
        env.get("AUTO_WARM_CLOSE_MIN_SCORE")
        or env.get("HIGH_INTENT_EMAIL_MIN_SCORE")
        or "70"
    )
    return WarmCloseConfig(
        account_sid=inbox_cfg.account_sid,
        auth_token=inbox_cfg.auth_token,
        from_number=inbox_cfg.from_number,
        booking_url=inbox_cfg.booking_url,
        kickoff_url=inbox_cfg.kickoff_url,
        statuses=_parse_statuses(env.get("AUTO_WARM_CLOSE_STATUSES")),
        max_per_run=max(1, int((env.get("AUTO_WARM_CLOSE_MAX_PER_RUN") or "3").strip() or 3)),
        min_score=max(0, int(str(min_score_raw).strip() or 0)),
        cooldown_hours=max(1, int((env.get("AUTO_WARM_CLOSE_COOLDOWN_HOURS") or "24").strip() or 24)),
        lookback_days=max(1, int((env.get("AUTO_WARM_CLOSE_LOOKBACK_DAYS") or "30").strip() or 30)),
    )


def run_warm_close_loop(
    *,
    sqlite_path: Path,
    audit_log: Path,
    env: dict[str, str],
    booking_url: str = "",
    kickoff_url: str = "",
) -> WarmCloseResult:
    cfg = _load_config(env, booking_url=booking_url, kickoff_url=kickoff_url)
    if cfg is None:
        enabled = truthy(env.get("AUTO_WARM_CLOSE_ENABLED"), default=True)
        return WarmCloseResult(reason="missing_twilio_env" if enabled else "disabled")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    result = WarmCloseResult()
    now = datetime.now(UTC)
    cooldown_cutoff_iso = (now - timedelta(hours=int(cfg.cooldown_hours))).isoformat()
    lookback_start_iso = (now - timedelta(days=int(cfg.lookback_days))).isoformat()
    body = _build_close_body(booking_url=cfg.booking_url, kickoff_url=cfg.kickoff_url)

    status_placeholders = ",".join(["?"] * len(cfg.statuses))
    params: list[Any] = [*cfg.statuses, int(cfg.min_score), lookback_start_iso, int(cfg.max_per_run) * 6]
    sql = f"""
        SELECT
          id,
          COALESCE(phone, '') AS phone,
          COALESCE(status, '') AS status,
          COALESCE(score, 0) AS score,
          COALESCE(updated_at, created_at, '') AS lead_ts
        FROM leads
        WHERE lower(COALESCE(status, '')) IN ({status_placeholders})
          AND TRIM(COALESCE(phone, '')) <> ''
          AND COALESCE(score, 0) >= ?
          AND COALESCE(updated_at, created_at, '') >= ?
        ORDER BY COALESCE(updated_at, created_at, '') ASC
        LIMIT ?
    """

    try:
        rows = store.conn.execute(sql, tuple(params)).fetchall()
        seen: set[str] = set()
        for row in rows:
            if result.sent >= int(cfg.max_per_run):
                break
            lead_id = str(row[0] or "").strip().lower()
            phone_e164 = _normalize_phone(str(row[1] or ""))
            lead_status = str(row[2] or "").strip().lower()
            lead_score = int(row[3] or 0)
            lead_ts = str(row[4] or "")

            dedupe_key = lead_id or phone_e164
            if not dedupe_key or dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            result.candidates += 1

            if not phone_e164:
                result.skipped += 1
                continue

            if (lead_id and store.is_opted_out(lead_id)) or _has_phone_opt_out(store, phone_e164=phone_e164):
                result.skipped += 1
                continue

            if _already_closed_recently(
                store,
                lead_id=lead_id,
                phone_e164=phone_e164,
                cutoff_iso=cooldown_cutoff_iso,
            ):
                result.skipped += 1
                continue

            conversion_since_iso = lead_ts if _parse_iso(lead_ts) is not None else lookback_start_iso
            if has_conversion_after(store, lead_id=lead_id, since_iso=conversion_since_iso):
                result.converted_skipped += 1
                result.skipped += 1
                continue

            payload: dict[str, Any] = {
                "lead_id": lead_id,
                "lead_status": lead_status,
                "lead_score": int(lead_score),
                "to_phone_e164": phone_e164,
                "booking_url": cfg.booking_url,
                "kickoff_url": cfg.kickoff_url,
                "twilio": {},
            }
            result.attempted += 1
            try:
                resp = _send_sms(cfg=cfg, to_number=phone_e164, body=body, env=env)
                sid = str(resp.get("sid") or "").strip()
                payload["twilio"] = {
                    "sid": sid,
                    "status": str(resp.get("status") or ""),
                    "error_code": resp.get("error_code"),
                    "error_message": resp.get("error_message"),
                }
                store.log_action(
                    agent_id="agent.sms.twilio.warm_close.v1",
                    action_type="sms.warm_close",
                    trace_id=f"twilio_warm_close:{sid or lead_id or phone_e164}",
                    payload=payload,
                )
                result.sent += 1
            except Exception as exc:
                payload["error_type"] = type(exc).__name__
                payload["error"] = str(exc)
                store.log_action(
                    agent_id="agent.sms.twilio.warm_close.v1",
                    action_type="sms.warm_close_failed",
                    trace_id=f"twilio_warm_close_failed:{lead_id or phone_e164}",
                    payload=payload,
                )
                result.failed += 1
    except Exception as exc:
        result.reason = f"error:{type(exc).__name__}"
    finally:
        with contextlib.suppress(Exception):
            store.conn.close()

    return result
