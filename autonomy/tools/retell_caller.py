"""Retell AI outbound caller — conversational calls via Retell's phone API.

Replaces static TwiML robocalls with AI-driven conversations. The Twilio number
is already imported into Retell and can make outbound calls directly.

Usage: imported by twilio_autocall.py when RETELL_API_KEY is set.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetellCallerConfig:
    api_key: str
    outbound_agent_id: str
    from_number: str
    poll_interval_secs: float = 3.0
    poll_timeout_secs: int = 300


def load_retell_config(env: dict[str, str]) -> RetellCallerConfig | None:
    """Load Retell config from env dict. Returns None if required vars missing."""
    api_key = (env.get("RETELL_API_KEY") or "").strip()
    agent_id = (env.get("RETELL_OUTBOUND_AGENT_ID") or "").strip()
    from_number = (env.get("TWILIO_FROM_NUMBER") or "").strip()
    if not api_key or not agent_id or not from_number:
        return None
    if not from_number.startswith("+"):
        return None
    return RetellCallerConfig(
        api_key=api_key,
        outbound_agent_id=agent_id,
        from_number=from_number,
    )


def _retell_request(
    *,
    config: RetellCallerConfig,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout_secs: int = 30,
) -> dict[str, Any]:
    """Make an authenticated request to the Retell API."""
    url = f"https://api.retellai.com{path}"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
    with urllib.request.urlopen(req, timeout=timeout_secs) as resp:
        raw = resp.read()
    return json.loads(raw.decode("utf-8"))


def place_retell_call(
    config: RetellCallerConfig,
    to_number: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Place an outbound call via Retell AI.

    Returns the call object with call_id for polling.
    """
    body: dict[str, Any] = {
        "from_number": config.from_number,
        "to_number": to_number,
        "override_agent_id": config.outbound_agent_id,
    }
    if metadata:
        body["metadata"] = metadata
    return _retell_request(
        config=config,
        method="POST",
        path="/v2/create-phone-call",
        body=body,
    )


def get_retell_call(config: RetellCallerConfig, call_id: str) -> dict[str, Any]:
    """Poll Retell for call status until terminal, or timeout."""
    terminal = {"ended", "error", "not_connected"}
    deadline = time.monotonic() + float(config.poll_timeout_secs)
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _retell_request(
            config=config,
            method="GET",
            path=f"/v2/get-call/{call_id}",
        )
        status = str(last.get("call_status") or "").strip().lower()
        if status in terminal:
            return last
        time.sleep(float(config.poll_interval_secs))
    return last


def map_retell_to_outcome(call_data: dict[str, Any]) -> tuple[str, str]:
    """Map Retell call data to the existing outcome taxonomy.

    Returns (outcome, notes) where outcome is one of:
        spoke, voicemail, no_answer, failed
    """
    status = str(call_data.get("call_status") or "").strip().lower()
    reason = str(call_data.get("disconnection_reason") or "").strip()
    analysis = call_data.get("call_analysis") or {}
    in_voicemail = analysis.get("in_voicemail", False)

    if status == "error":
        return "failed", f"retell_status=error reason={reason}"

    if status == "not_connected":
        return "no_answer", f"retell_status=not_connected reason={reason}"

    if status == "ended":
        if in_voicemail:
            return "voicemail", f"retell_status=ended in_voicemail=true reason={reason}"
        return "spoke", f"retell_status=ended reason={reason}"

    # Non-terminal or unknown status — treat as no_answer.
    return "no_answer", f"retell_status={status} reason={reason}"
