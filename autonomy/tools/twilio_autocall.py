#!/usr/bin/env python3
"""
Optional: place outbound calls via Twilio and log them into the outreach DB.

This exists to support a "100% automated" execution loop without requiring a
human to dial numbers. It is **disabled by default** and requires explicit
environment config + paid Twilio credentials.

Safety defaults:
- Disabled unless AUTO_CALLS_ENABLED=1
- Skips opted-out leads
- Skips leads called within the last N days (cooldown)
- Only calls during local business hours (best-effort TZ by US state)

This tool logs attempts as `call.attempt` so `autonomy/tools/scoreboard.py` and
the daily report can track progress.
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore
from autonomy.tools.retell_caller import (
    get_retell_call,
    load_retell_config,
    map_retell_to_outcome,
    place_retell_call,
)
from autonomy.utils import UTC, normalize_us_phone, now_utc_iso, state_tz, truthy

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")



def normalize_us_phone_e164(raw_phone: str) -> str | None:
    """Normalize common US phone formats into E.164 (e.g. +19546211439)."""
    result = normalize_us_phone(raw_phone)
    return result or None


def _state_tz(state: str) -> str:
    """Backward-compatible state timezone helper used by tests and callers."""
    return state_tz(state)


def _is_business_hours(*, state: str, start_hour: int, end_hour: int, allow_weekends: bool = False) -> bool:
    """Local business-hours check that remains monkeypatch-friendly in tests."""
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        return True

    tz_name = _state_tz(state)
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("America/New_York")

    now_local = datetime.now(tz)
    if not bool(allow_weekends) and now_local.weekday() >= 5:
        return False
    return int(start_hour) <= int(now_local.hour) < int(end_hour)


def _default_twiml() -> str:
    # Short, natural voicemail — no "automated call" language, clear CTA.
    msg = (
        "Hey there, this is a quick message for the office manager. "
        "My name is Igor with CallCatcher. "
        "We work with local practices that are missing calls after hours or during busy times. "
        "I'd love to send over a free one page report showing how many calls your office might be missing each week. "
        "If you're interested, just text the word yes back to this number, "
        "or visit callcatcherops dot com. "
        "Thanks so much, have a great day."
    )
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Say voice="Polly.Matthew">{msg}</Say></Response>'


def _is_reasonable_email(value: str) -> bool:
    email = (value or "").strip().lower()
    if not _EMAIL_RE.match(email):
        return False
    domain = email.split("@", 1)[1]
    parts = domain.rsplit(".", 1)
    tld = parts[1] if len(parts) == 2 else ""
    # Filter out common scrape artifacts like "asset-1@3x.png".
    return tld not in {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "css", "js", "pdf"}


def _format_exception_notes(exc: Exception) -> tuple[str, dict[str, Any]]:
    details: dict[str, Any] = {"error_type": type(exc).__name__}
    notes = f"exception={type(exc).__name__}"
    if isinstance(exc, urllib.error.HTTPError):
        details["http_status"] = int(exc.code)
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
        except Exception:
            raw = ""
        if raw:
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {}
            if isinstance(parsed, dict):
                code = parsed.get("code")
                message = str(parsed.get("message") or "").strip()
                more_info = str(parsed.get("more_info") or "").strip()
                if code not in (None, ""):
                    details["error_code"] = code
                if message:
                    details["error_message"] = message[:200]
                if more_info:
                    details["error_more_info"] = more_info[:200]
                notes = (
                    f"exception=HTTPError status={int(exc.code)} "
                    f"code={code if code not in (None, '') else ''} "
                    f"message={message[:120]}".strip()
                )
            else:
                notes = f"exception=HTTPError status={int(exc.code)}"
        else:
            notes = f"exception=HTTPError status={int(exc.code)}"
    return notes, details


@dataclass(frozen=True)
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str
    twiml: str
    ring_timeout_secs: int
    poll_timeout_secs: int
    poll_interval_secs: float
    machine_detection: bool


def load_twilio_config(env: dict[str, str]) -> TwilioConfig | None:
    sid = (env.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (env.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (env.get("TWILIO_FROM_NUMBER") or "").strip()
    if not sid or not token or not from_num:
        return None
    twiml = (env.get("AUTO_CALLS_TWIML") or "").strip() or _default_twiml()

    ring_timeout = int((env.get("AUTO_CALLS_RING_TIMEOUT_SECS") or "20").strip() or 20)
    poll_timeout = int((env.get("AUTO_CALLS_POLL_TIMEOUT_SECS") or "120").strip() or 120)
    poll_interval = float((env.get("AUTO_CALLS_POLL_INTERVAL_SECS") or "2.0").strip() or 2.0)
    machine_detection = truthy(env.get("AUTO_CALLS_MACHINE_DETECTION") or "")

    # Basic sanity: Twilio requires E.164 for From numbers.
    if not from_num.startswith("+"):
        return None

    return TwilioConfig(
        account_sid=sid,
        auth_token=token,
        from_number=from_num,
        twiml=twiml,
        ring_timeout_secs=max(5, min(ring_timeout, 60)),
        poll_timeout_secs=max(20, min(poll_timeout, 600)),
        poll_interval_secs=max(0.5, min(poll_interval, 10.0)),
        machine_detection=machine_detection,
    )


def _auth_header(cfg: TwilioConfig) -> str:
    raw = f"{cfg.account_sid}:{cfg.auth_token}".encode()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"Basic {b64}"


def _twilio_request(
    *,
    cfg: TwilioConfig,
    method: str,
    path: str,
    data: dict[str, str] | None = None,
    timeout_secs: int = 20,
) -> dict[str, Any]:
    url = f"https://api.twilio.com{path}"
    payload = None
    headers = {"Authorization": _auth_header(cfg)}
    if data is not None:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout_secs) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def create_call(cfg: TwilioConfig, *, to_number: str) -> dict[str, Any]:
    data: dict[str, str] = {
        "To": to_number,
        "From": cfg.from_number,
        "Twiml": cfg.twiml,
        "Timeout": str(int(cfg.ring_timeout_secs)),
    }
    if cfg.machine_detection:
        data["MachineDetection"] = "Enable"
    return _twilio_request(
        cfg=cfg,
        method="POST",
        path=f"/2010-04-01/Accounts/{cfg.account_sid}/Calls.json",
        data=data,
    )


def fetch_call(cfg: TwilioConfig, *, call_sid: str) -> dict[str, Any]:
    return _twilio_request(
        cfg=cfg,
        method="GET",
        path=f"/2010-04-01/Accounts/{cfg.account_sid}/Calls/{call_sid}.json",
        data=None,
    )


def wait_for_call_terminal_status(cfg: TwilioConfig, *, call_sid: str) -> dict[str, Any]:
    terminal = {"completed", "busy", "failed", "no-answer", "canceled"}
    deadline = time.monotonic() + float(cfg.poll_timeout_secs)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = fetch_call(cfg, call_sid=call_sid)
        status = str(last.get("status") or "").strip().lower()
        if status in terminal:
            return last
        time.sleep(float(cfg.poll_interval_secs))
    return last


def map_twilio_call_to_outcome(call: dict[str, Any]) -> tuple[str, str]:
    """Map Twilio call resource -> (outcome, notes)."""
    status = str(call.get("status") or "").strip().lower()
    answered_by = str(call.get("answered_by") or "").strip().lower()
    error_code = call.get("error_code")

    if status in {"no-answer", "busy"}:
        return "no_answer", status
    if status in {"failed", "canceled"}:
        # Twilio uses 21211 for invalid 'To' phone number.
        if str(error_code or "") == "21211":
            return "wrong_number", f"{status} error_code=21211"
        return "no_answer", f"{status} error_code={error_code or ''}".strip()
    if status == "completed":
        if answered_by.startswith("machine"):
            return "voicemail", f"answered_by={answered_by}"
        if answered_by:
            return "spoke", f"answered_by={answered_by}"
        return "spoke", "completed"
    return "no_answer", status or "unknown"


@dataclass(frozen=True)
class AutoCallResult:
    attempted: int
    completed: int
    spoke: int
    voicemail: int
    no_answer: int
    wrong_number: int
    failed: int
    skipped: int
    reason: str


def _lead_called_recently(store: ContextStore, *, lead_id: str, cooldown_days: int) -> bool:
    cutoff = (datetime.now(UTC) - timedelta(days=int(cooldown_days))).isoformat()
    row = store.conn.execute(
        """
        SELECT 1
        FROM actions
        WHERE action_type='call.attempt'
          AND json_extract(payload_json, '$.lead_id') = ?
          AND COALESCE(json_extract(payload_json, '$.outcome'), '') <> 'failed'
          AND ts >= ?
        LIMIT 1
        """,
        (lead_id, cutoff),
    ).fetchone()
    return row is not None




def run_auto_calls(
    *,
    sqlite_path: Path,
    audit_log: Path,
    env: dict[str, str],
    call_rows: list[dict[str, Any]],
) -> AutoCallResult:
    if not truthy(env.get("AUTO_CALLS_ENABLED") or ""):
        return AutoCallResult(
            attempted=0,
            completed=0,
            spoke=0,
            voicemail=0,
            no_answer=0,
            wrong_number=0,
            failed=0,
            skipped=0,
            reason="disabled",
        )

    # Prefer Retell AI for conversational calls when configured.
    retell_cfg = load_retell_config(env)
    use_retell = retell_cfg is not None

    cfg = load_twilio_config(env)
    if cfg is None and not use_retell:
        return AutoCallResult(
            attempted=0,
            completed=0,
            spoke=0,
            voicemail=0,
            no_answer=0,
            wrong_number=0,
            failed=0,
            skipped=0,
            reason="missing_twilio_env",
        )

    max_calls = int((env.get("AUTO_CALLS_MAX_PER_RUN") or "10").strip() or 10)
    cooldown_days = int((env.get("AUTO_CALLS_COOLDOWN_DAYS") or "7").strip() or 7)
    start_hour = int((env.get("AUTO_CALLS_START_HOUR_LOCAL") or "9").strip() or 9)
    end_hour = int((env.get("AUTO_CALLS_END_HOUR_LOCAL") or "17").strip() or 17)
    allow_weekends = truthy(env.get("AUTO_CALLS_ALLOW_WEEKENDS"), default=False)

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))

    attempted = 0
    completed = 0
    spoke = 0
    voicemail = 0
    no_answer = 0
    wrong_number = 0
    failed = 0
    skipped = 0

    try:
        for row in call_rows:
            if attempted >= max_calls:
                break

            if isinstance(row, dict):
                row_map = row
            elif hasattr(row, "__dataclass_fields__"):
                row_map = asdict(row)
            else:
                row_map = {}

            lead_id = str(row_map.get("email") or "").strip().lower()
            if not _is_reasonable_email(lead_id):
                skipped += 1
                continue
            if store.is_opted_out(lead_id):
                skipped += 1
                continue
            if _lead_called_recently(store, lead_id=lead_id, cooldown_days=cooldown_days):
                skipped += 1
                continue

            state = str(row_map.get("state") or "").strip()
            if not _is_business_hours(
                state=state,
                start_hour=start_hour,
                end_hour=end_hour,
                allow_weekends=allow_weekends,
            ):
                skipped += 1
                continue

            to_phone = normalize_us_phone_e164(str(row_map.get("phone") or ""))
            if not to_phone:
                skipped += 1
                continue

            # Place call and wait for terminal status (best-effort).
            attempted_at = now_utc_iso()
            try:
                if use_retell:
                    metadata = {
                        "lead_id": lead_id,
                        "company": str(row_map.get("company") or ""),
                        "service": str(row_map.get("service") or ""),
                    }
                    created = place_retell_call(retell_cfg, to_phone, metadata)
                    call_id = str(created.get("call_id") or "")
                    final = get_retell_call(retell_cfg, call_id) if call_id else created
                    outcome, notes = map_retell_to_outcome(final)
                else:
                    created = create_call(cfg, to_number=to_phone)
                    call_sid = str(created.get("sid") or "")
                    final = wait_for_call_terminal_status(cfg, call_sid=call_sid) if call_sid else created
                    outcome, notes = map_twilio_call_to_outcome(final)
            except Exception as exc:
                notes, error_details = _format_exception_notes(exc)
                outcome = "failed"
                final = {"status": "exception", **error_details}

            attempted += 1

            if outcome == "spoke":
                spoke += 1
            elif outcome == "voicemail":
                voicemail += 1
            elif outcome == "wrong_number":
                wrong_number += 1
            elif outcome == "no_answer":
                no_answer += 1
            else:
                failed += 1

            if str(final.get("status") or "").strip().lower() == "completed":
                completed += 1

            # Minimal lead status update: new -> contacted when we attempt a call.
            if store.get_lead_status(lead_id) == "new":
                store.mark_contacted(lead_id)

            if use_retell:
                retell_call_id = str(final.get("call_id") or "").strip()
                trace_id = f"retell:{retell_call_id}" if retell_call_id else f"retell:{attempted_at}"
                analysis = final.get("call_analysis") or {}
                agent_id_str = "agent.autocall.retell.v1"
                provider_payload = {
                    "retell": {
                        "call_id": retell_call_id,
                        "call_status": str(final.get("call_status") or ""),
                        "disconnection_reason": str(final.get("disconnection_reason") or ""),
                        "transcript": str(final.get("transcript") or ""),
                        "call_summary": str(analysis.get("call_summary") or ""),
                        "call_successful": analysis.get("call_successful"),
                        "in_voicemail": analysis.get("in_voicemail"),
                        "user_sentiment": str(analysis.get("user_sentiment") or ""),
                    },
                }
            else:
                twilio_sid = str(final.get("sid") or "").strip()
                trace_id = f"twilio:{twilio_sid}" if twilio_sid else f"twilio:{attempted_at}"
                agent_id_str = "agent.autocall.twilio.v1"
                provider_payload = {
                    "twilio": {
                        "status": str(final.get("status") or ""),
                        "answered_by": str(final.get("answered_by") or ""),
                        "sid": str(final.get("sid") or ""),
                        "error_code": final.get("error_code"),
                        "http_status": final.get("http_status"),
                        "error_type": final.get("error_type"),
                        "error_message": final.get("error_message"),
                        "error_more_info": final.get("error_more_info"),
                    },
                }

            store.log_action(
                agent_id=agent_id_str,
                action_type="call.attempt",
                trace_id=trace_id,
                payload={
                    "lead_id": lead_id,
                    "attempted_at": attempted_at,
                    "outcome": outcome,
                    "notes": notes,
                    "company": str(row_map.get("company") or ""),
                    "service": str(row_map.get("service") or ""),
                    "phone": str(row_map.get("phone") or ""),
                    "city": str(row_map.get("city") or ""),
                    "state": state,
                    **provider_payload,
                },
            )
    finally:
        with contextlib.suppress(Exception):
            store.conn.close()

    return AutoCallResult(
        attempted=attempted,
        completed=completed,
        spoke=spoke,
        voicemail=voicemail,
        no_answer=no_answer,
        wrong_number=wrong_number,
        failed=failed,
        skipped=skipped,
        reason="ok",
    )


def main() -> int:  # pragma: no cover
    # This CLI path is intentionally minimal; live_job is the intended entrypoint.
    raise SystemExit(
        "Run via autonomy/tools/live_job.py (AUTO_CALLS_ENABLED=1) so calls are included in the daily report."
    )


if __name__ == "__main__":
    raise SystemExit(main())
