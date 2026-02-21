#!/usr/bin/env python3
"""
AI Receptionist — Retell AI / Vapi voice agent integration for dental practices.

Provides an inbound phone receptionist that:
- Greets callers and collects name, phone, and reason for visit
- Handles scheduling, insurance, and emergency routing
- Is HIPAA-conscious: no PHI in logs, no patient discussion

Supported backends: Retell AI, Vapi

Usage:
    python3 -m autonomy.tools.ai_receptionist --provider retell --action create-agent \
        --practice-name "Coral Springs Dental"
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Dental-specific system prompt
# ---------------------------------------------------------------------------

_DENTAL_SYSTEM_PROMPT = """\
You are a friendly AI receptionist for {practice_name}. Your job is to help \
callers with scheduling, insurance questions, and urgent needs. Always be warm, \
professional, and concise.

GREETING:
Begin every call with: "Thanks for calling {practice_name}, this is Alex. How \
can I help you today?"

SCHEDULING:
If the caller wants an appointment, ask: "I'd be happy to help schedule that. \
What day works best for you?" Then collect: full name, best callback number, \
and reason for visit (new patient, cleaning, pain, etc.).

INSURANCE:
If the caller asks about insurance, say: "We accept most major insurance plans \
including Delta Dental, Cigna, Aetna, and BlueCross. Could I get your provider \
name so I can confirm coverage?"

EMERGENCIES:
If the caller describes severe pain, a broken tooth, swelling, or bleeding, say: \
"That sounds urgent. Let me transfer you to our on-call line right away." Then \
transfer to the emergency extension.

INFORMATION COLLECTION:
Always collect before ending: full name, best callback phone number, reason for \
call. Read the number back to confirm.

HIPAA RULES (CRITICAL):
- Never discuss other patients by name or imply knowledge of any patient record.
- Never repeat PHI back in a way that could be overheard by a third party.
- Do not log or repeat sensitive health details; just collect the reason category.
- If asked about medical records, say: "Our office manager handles records \
requests — I'll have them call you back."

CLOSING:
End every call with: "Thanks so much for calling {practice_name}. Have a great \
day!"
"""


def _build_system_prompt(practice_name: str) -> str:
    return _DENTAL_SYSTEM_PROMPT.format(practice_name=practice_name)


# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------


def _http_request(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout_secs: int = 20,
) -> dict[str, Any]:
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers = {**headers, "Content-Type": "application/json"}
    req = urllib.request.Request(
        url, data=body, headers=headers, method=method.upper()
    )
    try:
        import ssl

        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout_secs, context=ctx) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = b""
        try:
            raw = exc.read()
        except Exception:
            pass
        raise RuntimeError(
            f"HTTP {exc.code} from {url}: {raw.decode('utf-8', errors='replace')[:300]}"
        ) from exc
    return json.loads(raw.decode("utf-8")) if raw.strip() else {}


# ---------------------------------------------------------------------------
# Retell AI backend
# ---------------------------------------------------------------------------

_RETELL_API_BASE = "https://api.retellai.com"


@dataclass
class RetellReceptionist:
    """Retell AI voice agent for inbound dental practice calls."""

    api_key: str
    agent_id: str = ""
    phone_number: str = ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def register_phone_number(self) -> dict[str, Any]:
        """Register a Twilio phone number with Retell as an inbound agent.

        Returns the Retell phone number object on success.
        """
        if not self.phone_number:
            raise ValueError("phone_number must be set before registering")
        if not self.agent_id:
            raise ValueError("agent_id must be set before registering a phone number")
        payload: dict[str, Any] = {
            "phone_number": self.phone_number,
            "inbound_agent_id": self.agent_id,
        }
        return _http_request(
            method="POST",
            url=f"{_RETELL_API_BASE}/create-phone-number",
            headers=self._headers(),
            payload=payload,
        )

    def create_agent(self, *, practice_name: str = "Our Dental Practice") -> dict[str, Any]:
        """Create a Retell AI agent with the dental-specific system prompt.

        Returns the created agent object (including agent_id).
        """
        system_prompt = _build_system_prompt(practice_name)
        payload: dict[str, Any] = {
            "agent_name": f"AI Receptionist — {practice_name}",
            "voice_id": "11labs-Adrian",
            "response_engine": {
                "type": "retell-llm",
                "llm_id": "gpt-4o",
            },
            "language": "en-US",
            "llm_websocket_url": None,
            "general_prompt": system_prompt,
            "general_tools": [
                {
                    "type": "end_call",
                    "name": "end_call",
                    "description": "End the call after collecting caller information.",
                },
                {
                    "type": "transfer_call",
                    "name": "transfer_to_emergency",
                    "description": "Transfer caller to on-call line for dental emergencies.",
                    "number": self.phone_number or "+10000000000",
                },
            ],
            "begin_message": f"Thanks for calling {practice_name}, this is Alex. How can I help you today?",
        }
        # Remove None values — Retell rejects unexpected nulls
        payload = {k: v for k, v in payload.items() if v is not None}
        result = _http_request(
            method="POST",
            url=f"{_RETELL_API_BASE}/create-agent",
            headers=self._headers(),
            payload=payload,
        )
        if "agent_id" in result:
            self.agent_id = str(result["agent_id"])
        return result

    def handle_webhook(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process a Retell webhook event (call_started, call_ended, call_analyzed).

        Returns a structured summary dict. PHI is intentionally excluded from
        the returned payload to keep logs HIPAA-safe.
        """
        event_type = str(event.get("event") or "").strip()
        call = event.get("call") or {}
        call_id = str(call.get("call_id") or "")
        agent_id = str(call.get("agent_id") or "")
        from_number = str(call.get("from_number") or "")
        to_number = str(call.get("to_number") or "")
        start_timestamp = call.get("start_timestamp")
        end_timestamp = call.get("end_timestamp")
        duration_ms = call.get("duration_ms")

        result: dict[str, Any] = {
            "event_type": event_type,
            "call_id": call_id,
            "agent_id": agent_id,
            # Partial masking of caller number for HIPAA-safe logging
            "caller_suffix": from_number[-4:] if len(from_number) >= 4 else "****",
            "to_number": to_number,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "duration_ms": duration_ms,
        }

        if event_type == "call_started":
            result["action"] = "call_in_progress"
        elif event_type == "call_ended":
            disconnect_reason = str(call.get("disconnection_reason") or "")
            result["action"] = "call_completed"
            result["disconnect_reason"] = disconnect_reason
        elif event_type == "call_analyzed":
            analysis = call.get("call_analysis") or {}
            result["action"] = "call_analyzed"
            # Only store non-PHI summary fields
            result["call_successful"] = analysis.get("call_successful")
            result["agent_task_completion_rating"] = analysis.get(
                "agent_task_completion_rating"
            )
            result["user_sentiment"] = analysis.get("user_sentiment")
        else:
            result["action"] = "unknown_event"

        return result

    def get_call_summary(self, call_id: str) -> dict[str, Any]:
        """Retrieve call transcript and summary from Retell for a given call_id.

        Transcript text is returned as-is; callers should treat it as PHI.
        """
        if not call_id:
            raise ValueError("call_id is required")
        result = _http_request(
            method="GET",
            url=f"{_RETELL_API_BASE}/get-call/{urllib.parse.quote(call_id, safe='')}",
            headers=self._headers(),
        )
        transcript = result.get("transcript") or ""
        analysis = result.get("call_analysis") or {}
        return {
            "call_id": call_id,
            "status": result.get("call_status"),
            "duration_ms": result.get("duration_ms"),
            "transcript": transcript,
            "summary": analysis.get("call_summary"),
            "call_successful": analysis.get("call_successful"),
            "user_sentiment": analysis.get("user_sentiment"),
            "agent_task_completion_rating": analysis.get("agent_task_completion_rating"),
        }


# ---------------------------------------------------------------------------
# Vapi backend (same interface)
# ---------------------------------------------------------------------------

_VAPI_API_BASE = "https://api.vapi.ai"


@dataclass
class VapiReceptionist:
    """Vapi voice agent for inbound dental practice calls.

    Drop-in alternative to RetellReceptionist with identical public interface.
    """

    api_key: str
    agent_id: str = ""
    phone_number: str = ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def register_phone_number(self) -> dict[str, Any]:
        """Import a phone number into Vapi and assign this assistant as inbound handler."""
        if not self.phone_number:
            raise ValueError("phone_number must be set before registering")
        if not self.agent_id:
            raise ValueError("agent_id must be set before registering a phone number")
        payload: dict[str, Any] = {
            "number": self.phone_number,
            "provider": "twilio",
            "assistantId": self.agent_id,
        }
        return _http_request(
            method="POST",
            url=f"{_VAPI_API_BASE}/phone-number",
            headers=self._headers(),
            payload=payload,
        )

    def create_agent(self, *, practice_name: str = "Our Dental Practice") -> dict[str, Any]:
        """Create a Vapi assistant with the dental-specific system prompt.

        Returns the created assistant object (including id).
        """
        system_prompt = _build_system_prompt(practice_name)
        payload: dict[str, Any] = {
            "name": f"AI Receptionist — {practice_name}",
            "voice": {
                "provider": "11labs",
                "voiceId": "pNInz6obpgDQGcFmaJgB",  # Adam — neutral, clear
            },
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "messages": [
                    {"role": "system", "content": system_prompt},
                ],
            },
            "firstMessage": (
                f"Thanks for calling {practice_name}, this is Alex. "
                "How can I help you today?"
            ),
            "endCallFunctionEnabled": True,
            "recordingEnabled": False,  # Disable to simplify HIPAA posture
            "hipaaEnabled": True,
        }
        result = _http_request(
            method="POST",
            url=f"{_VAPI_API_BASE}/assistant",
            headers=self._headers(),
            payload=payload,
        )
        if "id" in result:
            self.agent_id = str(result["id"])
        return result

    def handle_webhook(self, event: dict[str, Any]) -> dict[str, Any]:
        """Process a Vapi webhook event.

        Vapi event types: assistant-request, status-update, transcript, end-of-call-report.
        Returns a HIPAA-safe structured summary.
        """
        message = event.get("message") or {}
        event_type = str(message.get("type") or "").strip()
        call = message.get("call") or {}
        call_id = str(call.get("id") or "")
        assistant_id = str(call.get("assistantId") or "")
        customer = call.get("customer") or {}
        from_number = str(customer.get("number") or "")
        started_at = call.get("startedAt")
        ended_at = call.get("endedAt")

        result: dict[str, Any] = {
            "event_type": event_type,
            "call_id": call_id,
            "agent_id": assistant_id,
            "caller_suffix": from_number[-4:] if len(from_number) >= 4 else "****",
            "started_at": started_at,
            "ended_at": ended_at,
        }

        if event_type == "status-update":
            result["action"] = "status_update"
            result["status"] = message.get("status")
        elif event_type == "end-of-call-report":
            result["action"] = "call_completed"
            result["ended_reason"] = message.get("endedReason")
            result["duration_seconds"] = message.get("durationSeconds")
            # Summary is a string produced by Vapi — may contain PHI; label clearly
            result["summary"] = message.get("summary")
            result["success_evaluation"] = message.get("successEvaluation")
        elif event_type == "transcript":
            result["action"] = "transcript_chunk"
            result["role"] = message.get("role")
            # Omit transcript text from structured log; use get_call_summary for full text
        else:
            result["action"] = "unknown_event"

        return result

    def get_call_summary(self, call_id: str) -> dict[str, Any]:
        """Retrieve call details and summary from Vapi for a given call_id."""
        if not call_id:
            raise ValueError("call_id is required")
        result = _http_request(
            method="GET",
            url=f"{_VAPI_API_BASE}/call/{urllib.parse.quote(call_id, safe='')}",
            headers=self._headers(),
        )
        return {
            "call_id": call_id,
            "status": result.get("status"),
            "duration_seconds": result.get("durationSeconds"),
            "transcript": result.get("transcript"),
            "summary": result.get("summary"),
            "ended_reason": result.get("endedReason"),
            "success_evaluation": result.get("successEvaluation"),
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type] = {
    "retell": RetellReceptionist,
    "vapi": VapiReceptionist,
}


def build_receptionist(
    provider: str,
    *,
    api_key: str,
    agent_id: str = "",
    phone_number: str = "",
) -> RetellReceptionist | VapiReceptionist:
    """Instantiate the correct receptionist backend by provider name."""
    cls = _PROVIDERS.get(provider.lower())
    if cls is None:
        raise ValueError(f"Unknown provider {provider!r}. Choose from: {sorted(_PROVIDERS)}")
    return cls(api_key=api_key, agent_id=agent_id, phone_number=phone_number)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m autonomy.tools.ai_receptionist",
        description="AI Receptionist CLI — manage Retell/Vapi dental voice agents",
    )
    parser.add_argument(
        "--provider",
        required=True,
        choices=list(_PROVIDERS),
        help="Voice platform backend",
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["create-agent", "register-phone", "get-call", "webhook-test"],
        help="Action to perform",
    )
    parser.add_argument("--api-key", default="", help="Platform API key (or set via env)")
    parser.add_argument("--agent-id", default="", help="Existing agent/assistant ID")
    parser.add_argument("--phone-number", default="", help="E.164 phone number, e.g. +15551234567")
    parser.add_argument("--practice-name", default="Our Dental Practice", help="Practice display name")
    parser.add_argument("--call-id", default="", help="Call ID for get-call action")
    return parser.parse_args(argv)


def _resolve_api_key(args: argparse.Namespace) -> str:
    import os

    key = args.api_key.strip()
    if not key:
        env_var = "RETELL_API_KEY" if args.provider == "retell" else "VAPI_API_KEY"
        key = (os.environ.get(env_var) or "").strip()
    if not key:
        env_var = "RETELL_API_KEY" if args.provider == "retell" else "VAPI_API_KEY"
        raise SystemExit(
            f"API key required. Pass --api-key or set ${env_var}"
        )
    return key


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    api_key = _resolve_api_key(args)

    receptionist = build_receptionist(
        args.provider,
        api_key=api_key,
        agent_id=args.agent_id,
        phone_number=args.phone_number,
    )

    if args.action == "create-agent":
        result = receptionist.create_agent(practice_name=args.practice_name)
        print(json.dumps(result, indent=2))

    elif args.action == "register-phone":
        result = receptionist.register_phone_number()
        print(json.dumps(result, indent=2))

    elif args.action == "get-call":
        if not args.call_id:
            raise SystemExit("--call-id is required for get-call action")
        result = receptionist.get_call_summary(args.call_id)
        print(json.dumps(result, indent=2))

    elif args.action == "webhook-test":
        # Emit a canned webhook event so developers can verify handle_webhook locally
        if args.provider == "retell":
            sample: dict[str, Any] = {
                "event": "call_ended",
                "call": {
                    "call_id": "test-call-001",
                    "agent_id": args.agent_id or "test-agent",
                    "from_number": "+15551234567",
                    "to_number": args.phone_number or "+15559876543",
                    "start_timestamp": 1700000000000,
                    "end_timestamp": 1700000120000,
                    "duration_ms": 120000,
                    "disconnection_reason": "user_hangup",
                },
            }
        else:
            sample = {
                "message": {
                    "type": "end-of-call-report",
                    "endedReason": "customer-ended-call",
                    "durationSeconds": 120,
                    "summary": "Caller scheduled a cleaning appointment.",
                    "successEvaluation": "true",
                    "call": {
                        "id": "test-call-001",
                        "assistantId": args.agent_id or "test-assistant",
                        "startedAt": "2024-01-01T10:00:00Z",
                        "endedAt": "2024-01-01T10:02:00Z",
                        "customer": {"number": "+15551234567"},
                    },
                }
            }
        handled = receptionist.handle_webhook(sample)
        print(json.dumps(handled, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
