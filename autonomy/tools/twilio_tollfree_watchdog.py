#!/usr/bin/env python3
"""Twilio toll-free verification watchdog.

Automates the last-mile compliance loop:
- Poll the current toll-free verification state
- Auto-remediate known fixable rejections (for example 30485)
- Emit a structured result for reporting/alerting
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from autonomy.context_store import ContextStore
from autonomy.tools.agent_commerce import request_json
from autonomy.tools.fastmail_inbox_sync import load_dotenv
from autonomy.utils import UTC, truthy


@dataclass(frozen=True)
class TwilioTollfreeWatchdogConfig:
    enabled: bool
    account_sid: str
    auth_token: str
    phone_number: str
    legal_business_name: str
    doing_business_as: str
    business_type: str
    auto_fix_enabled: bool
    auto_fix_error_codes: tuple[int, ...]
    stale_review_hours: int
    alert_cooldown_hours: int
    notify_on_status_change: bool
    notify_on_approved: bool


@dataclass
class TwilioTollfreeWatchdogResult:
    reason: str = "ok"
    phone_number: str = ""
    phone_number_sid: str = ""
    verification_sid: str = ""
    trust_product_sid: str = ""
    status: str = ""
    error_code: int | None = None
    rejection_reason: str = ""
    business_name: str = ""
    doing_business_as: str = ""
    business_type: str = ""
    edit_allowed: bool | None = None
    auto_fix_attempted: bool = False
    auto_fix_applied: bool = False
    auto_fix_error: str = ""
    previous_status: str = ""
    status_changed: bool = False
    should_alert: bool = False
    alert_reason: str = ""
    alert_suppressed: bool = False
    date_updated: str = ""
    poll_utc: str = ""
    url: str = ""
    state_path: str = ""


def _parse_int_set(raw: str, default: tuple[int, ...]) -> tuple[int, ...]:
    vals: list[int] = []
    for part in (raw or "").split(","):
        token = part.strip()
        if not token:
            continue
        try:
            vals.append(int(token))
        except Exception:
            continue
    if vals:
        return tuple(sorted(set(vals)))
    return tuple(default)


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _parse_dt_utc(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _normalize_status(raw: str) -> str:
    return (raw or "").strip().upper()


def load_twilio_tollfree_watchdog_config(
    env: dict[str, str],
    *,
    company_name: str = "",
) -> TwilioTollfreeWatchdogConfig | None:
    sid = (env.get("TWILIO_ACCOUNT_SID") or "").strip()
    token = (env.get("TWILIO_AUTH_TOKEN") or "").strip()
    phone = (env.get("TWILIO_SMS_FROM_NUMBER") or env.get("TWILIO_FROM_NUMBER") or "").strip()
    if not sid or not token or not phone.startswith("+"):
        return None

    legal_name = (
        (env.get("TWILIO_BUSINESS_LEGAL_NAME") or "").strip()
        or (env.get("BUSINESS_LEGAL_NAME") or "").strip()
    )
    dba_name = (
        (env.get("TWILIO_BUSINESS_DBA_NAME") or "").strip()
        or (env.get("TWILIO_DBA_NAME") or "").strip()
        or (company_name or "").strip()
    )
    business_type = ((env.get("TWILIO_BUSINESS_TYPE") or "").strip() or "SOLE_PROPRIETOR").upper()
    stale_review_hours = max(1, int((env.get("TWILIO_TOLLFREE_STALE_REVIEW_HOURS") or "24").strip() or "24"))
    alert_cooldown_hours = max(1, int((env.get("TWILIO_TOLLFREE_ALERT_COOLDOWN_HOURS") or "12").strip() or "12"))
    auto_fix_codes = _parse_int_set(
        env.get("TWILIO_TOLLFREE_AUTOFIX_ERROR_CODES") or "",
        default=(30485,),
    )
    return TwilioTollfreeWatchdogConfig(
        enabled=truthy(env.get("TWILIO_TOLLFREE_WATCHDOG_ENABLED"), default=True),
        account_sid=sid,
        auth_token=token,
        phone_number=phone,
        legal_business_name=legal_name,
        doing_business_as=dba_name,
        business_type=business_type,
        auto_fix_enabled=truthy(env.get("TWILIO_TOLLFREE_AUTOFIX_ENABLED"), default=True),
        auto_fix_error_codes=auto_fix_codes,
        stale_review_hours=stale_review_hours,
        alert_cooldown_hours=alert_cooldown_hours,
        notify_on_status_change=truthy(env.get("TWILIO_TOLLFREE_NOTIFY_ON_STATUS_CHANGE"), default=True),
        notify_on_approved=truthy(env.get("TWILIO_TOLLFREE_NOTIFY_ON_APPROVED"), default=True),
    )


def _auth_header(cfg: TwilioTollfreeWatchdogConfig) -> str:
    raw = f"{cfg.account_sid}:{cfg.auth_token}".encode("utf-8")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"Basic {b64}"


def _request_json(
    *,
    cfg: TwilioTollfreeWatchdogConfig,
    method: str,
    url: str,
    data: dict[str, str] | None = None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = None
    headers = {"Authorization": _auth_header(cfg)}
    if data is not None:
        payload = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"

    parsed = request_json(
        method=method,
        url=url,
        headers=headers,
        payload=payload,
        timeout_secs=20,
        agent_id="agent.twilio.tollfree_watchdog.v1",
        env=env,
        urlopen_func=urllib.request.urlopen,
    )
    if not isinstance(parsed, dict):
        return {}
    return parsed


def _fetch_phone_number_sid(cfg: TwilioTollfreeWatchdogConfig, *, env: dict[str, str] | None = None) -> str:
    phone_q = urllib.parse.quote(cfg.phone_number, safe="")
    payload = _request_json(
        cfg=cfg,
        method="GET",
        url=(
            f"https://api.twilio.com/2010-04-01/Accounts/{cfg.account_sid}/IncomingPhoneNumbers.json"
            f"?PhoneNumber={phone_q}"
        ),
        env=env,
    )
    rows = payload.get("incoming_phone_numbers")
    if not isinstance(rows, list):
        return ""
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("phone_number") or "").strip() == cfg.phone_number:
            return str(row.get("sid") or "").strip()
    return ""


def _fetch_latest_verification(
    cfg: TwilioTollfreeWatchdogConfig,
    *,
    phone_sid: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    payload = _request_json(
        cfg=cfg,
        method="GET",
        url=(
            "https://messaging.twilio.com/v1/Tollfree/Verifications"
            f"?TollfreePhoneNumberSid={urllib.parse.quote(phone_sid, safe='')}&PageSize=20"
        ),
        env=env,
    )
    rows = payload.get("verifications")
    if not isinstance(rows, list):
        return {}
    candidates: list[dict[str, Any]] = [row for row in rows if isinstance(row, dict)]
    if not candidates:
        return {}

    def _key(item: dict[str, Any]) -> tuple[int, float]:
        ts = _parse_dt_utc(str(item.get("date_updated") or item.get("date_created") or ""))
        return (1 if ts else 0, ts.timestamp() if ts else 0.0)

    candidates.sort(key=_key, reverse=True)
    return candidates[0]


def _update_verification(
    cfg: TwilioTollfreeWatchdogConfig,
    *,
    verification_sid: str,
    payload: dict[str, str],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _request_json(
        cfg=cfg,
        method="POST",
        url=f"https://messaging.twilio.com/v1/Tollfree/Verifications/{verification_sid}",
        data=payload,
        env=env,
    )


def _apply_verification(result: TwilioTollfreeWatchdogResult, verification: dict[str, Any]) -> None:
    result.verification_sid = str(verification.get("sid") or "").strip()
    result.trust_product_sid = str(verification.get("trust_product_sid") or "").strip()
    result.status = str(verification.get("status") or "").strip()
    result.error_code = _safe_int(verification.get("error_code"))
    result.rejection_reason = str(verification.get("rejection_reason") or "").strip()
    result.business_name = str(verification.get("business_name") or "").strip()
    result.doing_business_as = str(verification.get("doing_business_as") or "").strip()
    result.business_type = str(verification.get("business_type") or "").strip()
    if verification.get("edit_allowed") is None:
        result.edit_allowed = None
    else:
        result.edit_allowed = bool(verification.get("edit_allowed"))
    result.date_updated = str(verification.get("date_updated") or "").strip()
    result.url = str(verification.get("url") or "").strip()


def _maybe_build_fix_payload(
    *,
    cfg: TwilioTollfreeWatchdogConfig,
    result: TwilioTollfreeWatchdogResult,
) -> dict[str, str]:
    payload: dict[str, str] = {}
    if cfg.legal_business_name and cfg.legal_business_name != result.business_name:
        payload["BusinessName"] = cfg.legal_business_name
    if cfg.doing_business_as and cfg.doing_business_as != result.doing_business_as:
        payload["DoingBusinessAs"] = cfg.doing_business_as
    if cfg.business_type and cfg.business_type != (result.business_type or "").upper():
        payload["BusinessType"] = cfg.business_type
    return payload


def _evaluate_alert_state(*, cfg: TwilioTollfreeWatchdogConfig, result: TwilioTollfreeWatchdogResult) -> None:
    status = (result.status or "").strip().upper()
    now = datetime.now(UTC)
    if status in {"TWILIO_APPROVED", "APPROVED"}:
        result.should_alert = False
        result.alert_reason = ""
        return
    if status in {"TWILIO_REJECTED", "REJECTED"}:
        result.should_alert = True
        result.alert_reason = "twilio_rejected"
        return
    if status in {"IN_REVIEW", "PENDING_REVIEW"}:
        updated = _parse_dt_utc(result.date_updated)
        if updated is not None and (now - updated) >= timedelta(hours=int(cfg.stale_review_hours)):
            result.should_alert = True
            result.alert_reason = "stale_in_review"
            return
        result.should_alert = False
        result.alert_reason = ""
        return
    result.should_alert = True
    result.alert_reason = "unknown_status"


def _apply_transition_logic(
    *,
    cfg: TwilioTollfreeWatchdogConfig,
    result: TwilioTollfreeWatchdogResult,
    prior_state: dict[str, Any],
) -> None:
    current = _normalize_status(result.status)
    previous = _normalize_status(str(prior_state.get("last_status") or ""))
    result.previous_status = previous
    result.status_changed = bool(previous and current and previous != current)

    if not result.status_changed or not cfg.notify_on_status_change:
        return

    if current in {"TWILIO_APPROVED", "APPROVED"}:
        if cfg.notify_on_approved:
            result.should_alert = True
            result.alert_reason = "status_changed_approved"
        return
    if current in {"TWILIO_REJECTED", "REJECTED"}:
        result.should_alert = True
        result.alert_reason = "status_changed_rejected"
        return
    result.should_alert = True
    result.alert_reason = "status_changed"


def _apply_alert_cooldown(
    *,
    cfg: TwilioTollfreeWatchdogConfig,
    result: TwilioTollfreeWatchdogResult,
    prior_state: dict[str, Any],
) -> None:
    if not result.should_alert:
        return
    prior_reason = str(prior_state.get("last_alert_reason") or "").strip()
    prior_alert_ts = _parse_dt_utc(str(prior_state.get("last_alert_utc") or ""))
    if not prior_reason or prior_alert_ts is None:
        return
    if prior_reason != (result.alert_reason or ""):
        return
    cooldown = timedelta(hours=int(cfg.alert_cooldown_hours))
    if datetime.now(UTC) - prior_alert_ts < cooldown:
        result.should_alert = False
        result.alert_suppressed = True


def run_twilio_tollfree_watchdog(
    *,
    sqlite_path: Path,
    audit_log: Path,
    env: dict[str, str],
    company_name: str = "",
    state_path: Path | None = None,
) -> TwilioTollfreeWatchdogResult:
    resolved_state_path = state_path or (Path(sqlite_path).resolve().parent / "twilio_tollfree_watchdog_state.json")
    prior_state = _read_json(resolved_state_path)
    cfg = load_twilio_tollfree_watchdog_config(env, company_name=company_name)
    poll_utc = datetime.now(UTC).replace(microsecond=0).isoformat()
    if cfg is None:
        return TwilioTollfreeWatchdogResult(
            reason="missing_twilio_env",
            should_alert=True,
            alert_reason="missing_twilio_env",
            poll_utc=poll_utc,
            state_path=str(resolved_state_path),
        )
    if not cfg.enabled:
        return TwilioTollfreeWatchdogResult(
            reason="disabled",
            phone_number=cfg.phone_number,
            poll_utc=poll_utc,
            state_path=str(resolved_state_path),
        )

    result = TwilioTollfreeWatchdogResult(
        reason="ok",
        phone_number=cfg.phone_number,
        poll_utc=poll_utc,
        state_path=str(resolved_state_path),
    )
    try:
        phone_sid = _fetch_phone_number_sid(cfg, env=env)
        result.phone_number_sid = phone_sid
        if not phone_sid:
            result.reason = "phone_not_found"
            result.should_alert = True
            result.alert_reason = "phone_not_found"
            return result

        verification = _fetch_latest_verification(cfg, phone_sid=phone_sid, env=env)
        if not verification:
            result.reason = "verification_not_found"
            result.should_alert = True
            result.alert_reason = "verification_not_found"
            return result

        _apply_verification(result, verification)
        status = (result.status or "").strip().upper()
        if (
            cfg.auto_fix_enabled
            and status in {"TWILIO_REJECTED", "REJECTED"}
            and result.error_code is not None
            and result.error_code in set(cfg.auto_fix_error_codes)
            and bool(result.edit_allowed)
        ):
            payload = _maybe_build_fix_payload(cfg=cfg, result=result)
            if payload:
                result.auto_fix_attempted = True
                try:
                    updated = _update_verification(cfg, verification_sid=result.verification_sid, payload=payload, env=env)
                    _apply_verification(result, updated)
                    result.auto_fix_applied = True
                    result.reason = "auto_fix_applied"
                except Exception as exc:
                    result.auto_fix_error = f"{type(exc).__name__}: {exc}"
                    result.reason = "auto_fix_failed"
                    result.should_alert = True
                    result.alert_reason = "auto_fix_failed"
                    return result
            else:
                result.reason = "rejected_no_fix_delta"

        _evaluate_alert_state(cfg=cfg, result=result)
        _apply_transition_logic(cfg=cfg, result=result, prior_state=prior_state)
        _apply_alert_cooldown(cfg=cfg, result=result, prior_state=prior_state)
    except Exception as exc:
        result.reason = "watchdog_error"
        result.should_alert = True
        result.alert_reason = "watchdog_error"
        result.auto_fix_error = f"{type(exc).__name__}: {exc}"
    finally:
        next_state: dict[str, Any] = {
            "last_poll_utc": result.poll_utc,
            "last_status": result.status,
            "last_error_code": result.error_code,
            "last_alert_reason": str(prior_state.get("last_alert_reason") or ""),
            "last_alert_utc": str(prior_state.get("last_alert_utc") or ""),
            "last_date_updated": result.date_updated,
        }
        if result.should_alert:
            next_state["last_alert_reason"] = result.alert_reason
            next_state["last_alert_utc"] = result.poll_utc
        with contextlib.suppress(Exception):
            _write_json(resolved_state_path, next_state)

        with contextlib.suppress(Exception):
            store = ContextStore(sqlite_path=str(sqlite_path), audit_log=str(audit_log))
            trace = f"twilio_tollfree_watchdog:{result.verification_sid or result.phone_number}:{int(time.time())}"
            store.log_action(
                agent_id="agent.compliance.twilio_tollfree.v1",
                action_type="compliance.twilio_tollfree_watchdog",
                trace_id=trace,
                payload=asdict(result),
            )
            if result.auto_fix_attempted:
                store.log_action(
                    agent_id="agent.compliance.twilio_tollfree.v1",
                    action_type="compliance.twilio_tollfree_fix",
                    trace_id=f"{trace}:fix",
                    payload={
                        "verification_sid": result.verification_sid,
                        "status": result.status,
                        "auto_fix_applied": bool(result.auto_fix_applied),
                        "auto_fix_error": result.auto_fix_error,
                    },
                )
            store.conn.close()

    return result


def _resolve_path(repo_root: Path, raw: str) -> Path:
    root = repo_root.resolve()
    path = Path(raw).expanduser()
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"path must stay inside repo root: {raw}")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Twilio toll-free verification watchdog.")
    parser.add_argument(
        "--dotenv",
        default=".env",
        help="Comma-separated dotenv paths relative to repo root (later wins).",
    )
    parser.add_argument("--sqlite-path", default="autonomy/state/autonomy_live.sqlite3")
    parser.add_argument("--audit-log", default="autonomy/state/autonomy_live.jsonl")
    parser.add_argument(
        "--state-path",
        default="autonomy/state/twilio_tollfree_watchdog_state.json",
        help="State file used for transition/cooldown dedupe.",
    )
    parser.add_argument("--company-name", default="CallCatcher Ops")
    parser.add_argument(
        "--exit-on-alert",
        action="store_true",
        help="Exit 2 when watchdog determines an alert should fire.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    env: dict[str, str] = {}
    for rel in [p.strip() for p in str(args.dotenv or "").split(",") if p.strip()]:
        env.update(load_dotenv(_resolve_path(repo_root, rel)))

    # Keep env vars visible for dependent libs/tools that read process env.
    for key, value in env.items():
        os.environ.setdefault(key, value)

    result = run_twilio_tollfree_watchdog(
        sqlite_path=_resolve_path(repo_root, args.sqlite_path),
        audit_log=_resolve_path(repo_root, args.audit_log),
        env=env,
        company_name=args.company_name,
        state_path=_resolve_path(repo_root, args.state_path),
    )
    print(json.dumps(asdict(result), indent=2, sort_keys=True))

    if args.exit_on_alert and result.should_alert:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
