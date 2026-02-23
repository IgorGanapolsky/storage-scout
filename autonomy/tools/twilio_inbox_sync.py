#!/usr/bin/env python3
"""Sync inbound Twilio SMS replies into the outreach database.

This keeps the phone-first loop fully autonomous:
- Poll inbound SMS replies sent to our Twilio number
- Classify intent (opt-out / interested / other)
- Update lead status and opt-out table
- Auto-reply with booking CTA when appropriate
"""

from __future__ import annotations

import base64
import contextlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore
from autonomy.utils import normalize_us_phone, truthy

_OPT_OUT_RE = re.compile(r"\b(stop|unsubscribe|cancel|quit|end|remove)\b", re.IGNORECASE)
_INTEREST_RE = re.compile(
    r"\b(yes|interested|book|booking|baseline|audit|call|pricing|price)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TwilioInboxConfig:
    account_sid: str
    auth_token: str
    from_number: str
    booking_url: str
    kickoff_url: str
    auto_reply_enabled: bool
    max_per_run: int


@dataclass
class TwilioInboxResult:
    reason: str = "ok"
    fetched: int = 0
    processed: int = 0
    ignored: int = 0
    interested: int = 0
    replied: int = 0
    opt_out: int = 0
    auto_replies_sent: int = 0
    auto_reply_failed: int = 0


def load_twilio_inbox_config(
    env: dict[str, str],
    *,
    booking_url: str = "",
    kickoff_url: str = "",
) -> TwilioInboxConfig | None:
    sid = (env.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (env.get("TWILIO_AUTH_TOKEN") or "").strip()
    from_num = (env.get("TWILIO_SMS_FROM_NUMBER") or env.get("TWILIO_FROM_NUMBER") or "").strip()
    if not sid or not token or not from_num or not from_num.startswith("+"):
        return None

    booking = (booking_url or "").strip() or "https://calendly.com/igorganapolsky/audit-call"
    kickoff = (
        (kickoff_url or "").strip()
        or (env.get("PRIORITY_KICKOFF_URL") or "").strip()
        or "https://buy.stripe.com/4gMaEX0I4f5IdWh6i73sI01"
    )
    return TwilioInboxConfig(
        account_sid=sid,
        auth_token=token,
        from_number=from_num,
        booking_url=booking,
        kickoff_url=kickoff,
        auto_reply_enabled=truthy(env.get("AUTO_SMS_INBOUND_REPLY_ENABLED"), default=True),
        max_per_run=max(1, int((env.get("AUTO_SMS_INBOUND_MAX_PER_RUN") or "50").strip() or 50)),
    )


def _auth_header(cfg: TwilioInboxConfig) -> str:
    raw = f"{cfg.account_sid}:{cfg.auth_token}".encode()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"Basic {b64}"


def _twilio_request(
    *,
    cfg: TwilioInboxConfig,
    method: str,
    path: str,
    query: dict[str, str] | None = None,
    data: dict[str, str] | None = None,
) -> dict[str, Any]:
    url = f"https://api.twilio.com{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"

    payload = None
    headers = {"Authorization": _auth_header(cfg)}
    if data is not None:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read()
    return json.loads(body.decode("utf-8"))


def _list_messages(cfg: TwilioInboxConfig) -> list[dict[str, Any]]:
    payload = _twilio_request(
        cfg=cfg,
        method="GET",
        path=f"/2010-04-01/Accounts/{cfg.account_sid}/Messages.json",
        query={"To": cfg.from_number, "PageSize": str(int(cfg.max_per_run))},
    )
    messages = payload.get("messages")
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _send_reply(cfg: TwilioInboxConfig, *, to_number: str, body: str) -> dict[str, Any]:
    return _twilio_request(
        cfg=cfg,
        method="POST",
        path=f"/2010-04-01/Accounts/{cfg.account_sid}/Messages.json",
        data={"To": to_number, "From": cfg.from_number, "Body": body},
    )


def _classify_reply(body: str) -> str:
    text = (body or "").strip().lower()
    if not text:
        return "other"
    if _OPT_OUT_RE.search(text):
        return "opt_out"
    if _INTEREST_RE.search(text):
        return "interested"
    return "other"


def _find_lead_by_phone(store: ContextStore, phone_e164: str) -> str:
    if not phone_e164:
        return ""
    rows = store.conn.execute(
        "SELECT id, COALESCE(phone,'') as phone FROM leads WHERE TRIM(COALESCE(phone,'')) <> ''"
    ).fetchall()
    for row in rows:
        if normalize_us_phone(str(row["phone"] or "")) == phone_e164:
            return str(row["id"] or "").strip().lower()
    return ""


def _already_processed(store: ContextStore, inbound_sid: str) -> bool:
    trace_id = f"twilio_inbound:{inbound_sid}"
    row = store.conn.execute(
        "SELECT 1 FROM actions WHERE action_type='sms.inbound' AND trace_id=? LIMIT 1",
        (trace_id,),
    ).fetchone()
    return row is not None


def _interest_reply_text(booking_url: str, kickoff_url: str) -> str:
    return (
        "Great, thanks for replying. Book your free 5-min missed-call baseline here: "
        f"{booking_url} "
        "Want priority setup? Reserve your kickoff here: "
        f"{kickoff_url} Reply STOP to opt out."
    )


def _generic_reply_text(booking_url: str) -> str:
    return (
        "Thanks for your message. If helpful, you can book a free 5-min baseline here: "
        f"{booking_url} Reply STOP to opt out."
    )


def run_twilio_inbox_sync(
    *,
    sqlite_path: Path,
    audit_log: Path,
    env: dict[str, str],
    booking_url: str = "",
    kickoff_url: str = "",
) -> TwilioInboxResult:
    cfg = load_twilio_inbox_config(env, booking_url=booking_url, kickoff_url=kickoff_url)
    if cfg is None:
        return TwilioInboxResult(reason="missing_twilio_env")

    store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
    result = TwilioInboxResult()
    try:
        messages = _list_messages(cfg)
        for msg in messages:
            result.fetched += 1
            direction = str(msg.get("direction") or "").strip().lower()
            inbound_sid = str(msg.get("sid") or "").strip()
            if not inbound_sid or not direction.startswith("inbound"):
                result.ignored += 1
                continue
            if _already_processed(store, inbound_sid):
                result.ignored += 1
                continue

            body = str(msg.get("body") or "")
            from_phone_raw = str(msg.get("from") or "")
            from_phone = normalize_us_phone(from_phone_raw)
            lead_id = _find_lead_by_phone(store, from_phone)
            classification = _classify_reply(body)

            if lead_id:
                if classification == "opt_out":
                    store.add_opt_out(lead_id)
                    store.mark_status_by_email(lead_id, "opted_out")
                else:
                    store.mark_status_by_email(lead_id, "replied")

            payload: dict[str, Any] = {
                "inbound_sid": inbound_sid,
                "lead_id": lead_id,
                "from_phone": from_phone_raw,
                "from_phone_e164": from_phone,
                "classification": classification,
                "body": body,
            }
            store.log_action(
                agent_id="agent.sms.twilio.inbox.v1",
                action_type="sms.inbound",
                trace_id=f"twilio_inbound:{inbound_sid}",
                payload=payload,
            )
            result.processed += 1

            if classification == "opt_out":
                result.opt_out += 1
                continue
            if classification == "interested":
                result.interested += 1
                reply_body = _interest_reply_text(cfg.booking_url, cfg.kickoff_url)
            else:
                result.replied += 1
                reply_body = _generic_reply_text(cfg.booking_url)

            if not cfg.auto_reply_enabled or not from_phone:
                continue

            try:
                resp = _send_reply(cfg, to_number=from_phone, body=reply_body)
                out_sid = str(resp.get("sid") or "").strip()
                result.auto_replies_sent += 1
                store.log_action(
                    agent_id="agent.sms.twilio.inbox.v1",
                    action_type="sms.reply",
                    trace_id=f"twilio_reply:{out_sid or inbound_sid}",
                    payload={
                        "lead_id": lead_id,
                        "inbound_sid": inbound_sid,
                        "outbound_sid": out_sid,
                        "to_phone": from_phone,
                        "classification": classification,
                    },
                )
            except Exception as exc:
                result.auto_reply_failed += 1
                store.log_action(
                    agent_id="agent.sms.twilio.inbox.v1",
                    action_type="sms.reply_failed",
                    trace_id=f"twilio_reply_failed:{inbound_sid}",
                    payload={
                        "lead_id": lead_id,
                        "inbound_sid": inbound_sid,
                        "to_phone": from_phone,
                        "classification": classification,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
    except Exception as exc:
        result.reason = f"error:{type(exc).__name__}"
    finally:
        with contextlib.suppress(Exception):
            store.conn.close()

    return result
