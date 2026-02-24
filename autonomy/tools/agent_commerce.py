from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

UTC = timezone.utc
REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = (REPO_ROOT / "autonomy" / "state").resolve()


def _resolve_state_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (REPO_ROOT / candidate).resolve()
    if resolved != STATE_DIR and STATE_DIR not in resolved.parents:
        raise ValueError(f"Refusing path outside {STATE_DIR}: {resolved}")
    return resolved


def _now_iso_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _payload_sha256(payload: bytes | None) -> str:
    if not payload:
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(payload).hexdigest()


def _agent_headers(
    *,
    method: str,
    url: str,
    payload: bytes | None,
    agent_id: str,
    env: dict[str, str] | None,
) -> tuple[dict[str, str], str]:
    env_map = env if isinstance(env, dict) else {}
    effective_agent = (env_map.get("AGENT_COMMERCE_AGENT_ID") or agent_id or "").strip() or "agent.unknown.v1"
    protocol = (env_map.get("AGENT_COMMERCE_PROTOCOL") or "acp-lite/2026-02").strip()
    request_id = str(uuid4())
    ts = _now_iso_utc()

    headers = {
        "X-Agent-Protocol": protocol,
        "X-Agent-Id": effective_agent,
        "X-Agent-Request-Id": request_id,
        "X-Agent-Timestamp": ts,
    }
    signing_key = (env_map.get("AGENT_COMMERCE_SIGNING_KEY") or os.getenv("AGENT_COMMERCE_SIGNING_KEY") or "").strip()
    if signing_key:
        canonical = (
            f"{method.upper()}\n{url}\n{_payload_sha256(payload)}\n{ts}\n{effective_agent}\n{request_id}".encode(
                "utf-8"
            )
        )
        signature = hmac.new(signing_key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
        headers["X-Agent-Signature-Alg"] = "HMAC-SHA256"
        headers["X-Agent-Signature"] = signature
    return headers, request_id


def _meter_enabled(env: dict[str, str] | None) -> bool:
    env_map = env if isinstance(env, dict) else {}
    val = (env_map.get("AGENT_COMMERCE_METERING_ENABLED") or os.getenv("AGENT_COMMERCE_METERING_ENABLED") or "1").strip().lower()
    return val not in {"0", "false", "no", "off"}


def _meter_path(env: dict[str, str] | None) -> Path:
    env_map = env if isinstance(env, dict) else {}
    raw = (env_map.get("AGENT_API_METER_FILE") or os.getenv("AGENT_API_METER_FILE") or "autonomy/state/agent_api_metering.jsonl").strip()
    return _resolve_state_path(raw)


def _write_meter_event(*, env: dict[str, str] | None, event: dict[str, object]) -> None:
    if not _meter_enabled(env):
        return
    try:
        out = _meter_path(env)
    except Exception:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")


def request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str] | None,
    payload: bytes | None,
    timeout_secs: int,
    agent_id: str,
    env: dict[str, str] | None = None,
    urlopen_func=None,
) -> dict[str, object]:
    base_headers = dict(headers or {})
    ac_headers, request_id = _agent_headers(method=method, url=url, payload=payload, agent_id=agent_id, env=env)
    base_headers.update(ac_headers)
    req = urllib.request.Request(url, data=payload, headers=base_headers, method=method.upper())
    t0 = time.perf_counter()

    def _base_event(*, ok: bool, status_code: int, error_type: str = "") -> dict[str, object]:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        # Redact query params from URL to avoid storing secrets in clear text
        parsed_url = urllib.parse.urlparse(url)
        safe_url = urllib.parse.urlunparse(parsed_url._replace(query="REDACTED" if parsed_url.query else ""))
        return {
            "ts": _now_iso_utc(),
            "agent_id": agent_id,
            "request_id": request_id,
            "method": method.upper(),
            "url": safe_url,
            "status_code": int(status_code),
            "ok": bool(ok),
            "error_type": error_type,
            "duration_ms": duration_ms,
            "request_bytes": int(len(payload or b"")),
        }

    opener = urlopen_func or urllib.request.urlopen
    try:
        with opener(req, timeout=timeout_secs) as resp:
            body = resp.read()
            status = int(getattr(resp, "status", 200) or 200)
        parsed = json.loads(body.decode("utf-8"))
        if not isinstance(parsed, dict):
            parsed = {}
        event = _base_event(ok=True, status_code=status)
        event["response_bytes"] = int(len(body or b""))
        _write_meter_event(env=env, event=event)
        return parsed
    except urllib.error.HTTPError as exc:
        event = _base_event(ok=False, status_code=int(exc.code or 0), error_type=type(exc).__name__)
        _write_meter_event(env=env, event=event)
        raise
    except Exception as exc:
        event = _base_event(ok=False, status_code=0, error_type=type(exc).__name__)
        _write_meter_event(env=env, event=event)
        raise
