"""Wire Retell AI receptionist to existing Twilio phone number.

Creates a Retell agent (if needed), generates a web-call demo link, and
optionally registers the Twilio number as inbound (requires Retell billing).

Usage:
    python3 -m autonomy.tools.wire_retell                 # web demo (free)
    python3 -m autonomy.tools.wire_retell --bind-phone    # phone binding (requires billing)
    python3 -m autonomy.tools.wire_retell --dry-run
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import requests

from autonomy.tools.ai_receptionist import RetellClient, RetellConfig

log = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

_DEFAULT_PROMPT = """\
You are a friendly AI receptionist for a dental practice. Your job is to help \
callers with scheduling, insurance questions, and urgent needs. Always be warm, \
professional, and concise.

GREETING:
Begin every call with: "Thanks for calling, this is Alex. How can I help you today?"

SCHEDULING:
If the caller wants an appointment, ask: "I'd be happy to help schedule that. \
What day works best for you?" Then collect: full name, best callback number, \
and reason for visit (new patient, cleaning, pain, etc.).

INSURANCE:
If the caller asks about insurance, say: "We accept most major insurance plans. \
Could I get your provider name so I can confirm coverage?"

EMERGENCIES:
If the caller describes severe pain, a broken tooth, swelling, or bleeding, say: \
"That sounds urgent. Let me get someone to help you right away."

INFORMATION COLLECTION:
Always collect before ending: full name, best callback phone number, reason for call.

CLOSING:
End every call with: "Thanks so much for calling. Have a great day!"
"""


def _load_env() -> dict[str, str]:
    """Load .env file into a dict (does NOT modify os.environ)."""
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition("=")
        env[key.strip()] = val.strip()
    return env


def _append_env(key: str, value: str) -> None:
    """Append a key=value to .env if not already present."""
    content = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    if re.search(rf"^{re.escape(key)}=", content, re.MULTILINE):
        log.info("%s already in .env, skipping", key)
        return
    with ENV_PATH.open("a", encoding="utf-8") as f:
        f.write(f"\n{key}={value}\n")
    log.info("Appended %s to .env", key)


def create_web_call(api_key: str, agent_id: str) -> dict:
    """Create a Retell web call (free, no phone number needed).

    Returns the web call object with access_token for browser-based demo.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    resp = requests.post(
        "https://api.retellai.com/v2/create-web-call",
        headers=headers,
        json={"agent_id": agent_id},
    )
    resp.raise_for_status()
    return resp.json()


def wire(*, dry_run: bool = False, bind_phone: bool = False) -> dict[str, str]:
    """Set up Retell agent + create web demo call.

    If bind_phone=True, also attempts to register the Twilio number
    (requires Retell billing — HTTP 402 if no card on file).

    Returns {"agent_id": ..., "web_call": ..., "phone_registration": ...}.
    """
    env = _load_env()

    api_key = env.get("RETELL_API_KEY", "")
    if not api_key:
        raise RuntimeError("RETELL_API_KEY not found in .env")

    phone = env.get("TWILIO_FROM_NUMBER", "")
    agent_id = env.get("RETELL_AGENT_ID", "") or os.getenv("RETELL_AGENT_ID", "")

    config = RetellConfig(api_key=api_key)
    client = RetellClient(config)

    result: dict[str, str] = {}

    # Step 1: Create agent if we don't have one.
    if not agent_id:
        if dry_run:
            print("[DRY RUN] Would create Retell LLM + agent for 'CallCatcher Ops Demo'")
            result["agent_id"] = "(dry-run)"
        else:
            print("Creating Retell LLM...")
            llm_id = client.create_retell_llm("CallCatcher Ops Demo", _DEFAULT_PROMPT)
            print(f"LLM created: {llm_id}")

            print("Creating Retell AI agent...")
            agent_resp = client.create_agent(
                "CallCatcher Ops Demo", llm_id, "11labs-Adrian"
            )
            agent_id = agent_resp.get("agent_id", "")
            if not agent_id:
                raise RuntimeError(f"Agent creation failed: {json.dumps(agent_resp)}")
            result["agent_id"] = agent_id
            print(f"Agent created: {agent_id}")
            _append_env("RETELL_AGENT_ID", agent_id)
    else:
        print(f"Using existing agent: {agent_id}")
        result["agent_id"] = agent_id

    # Step 2: Create web call (free demo).
    if dry_run:
        print("[DRY RUN] Would create web call for browser demo")
        result["web_call"] = "(dry-run)"
    else:
        print("Creating web call for browser demo...")
        web_call = create_web_call(api_key, agent_id)
        call_id = web_call.get("call_id", "")
        result["web_call_id"] = call_id
        result["web_call_status"] = web_call.get("call_status", "")
        print(f"Web call created: {call_id}")

    # Step 3: Optionally bind phone number.
    if bind_phone:
        if not phone:
            print("TWILIO_FROM_NUMBER not in .env — skipping phone binding")
            result["phone_registration"] = "skipped_no_number"
        elif dry_run:
            print(f"[DRY RUN] Would register {phone} with agent {agent_id}")
            result["phone_registration"] = "(dry-run)"
        else:
            print(f"Registering {phone} with Retell agent {agent_id}...")
            try:
                phone_resp = client.register_phone_number(agent_id, phone)
                result["phone_registration"] = json.dumps(phone_resp)
                print(f"Phone registered: {json.dumps(phone_resp, indent=2)}")
            except Exception as exc:
                error_msg = str(exc)
                if "payment" in error_msg.lower() or "402" in error_msg:
                    print(f"Phone binding requires Retell billing: {error_msg}")
                    result["phone_registration"] = "requires_billing"
                elif "already" in error_msg.lower() or "exists" in error_msg.lower():
                    print(f"Phone already registered: {error_msg}")
                    result["phone_registration"] = "already_registered"
                else:
                    raise

    return result


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Wire Retell AI to Twilio number.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen.")
    parser.add_argument("--bind-phone", action="store_true", help="Also register Twilio number (requires Retell billing).")
    args = parser.parse_args()

    result = wire(dry_run=args.dry_run, bind_phone=args.bind_phone)
    print(f"\nResult: {json.dumps(result, indent=2)}")
