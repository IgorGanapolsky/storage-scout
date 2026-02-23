#!/usr/bin/env python3
"""AI Receptionist Manager: Configure and deploy Retell AI voice agents.

Usage:
    python3 -m autonomy.tools.ai_receptionist \
        --action create_agent \
        --name "Dental Receptionist" \
        --prompt-file business/callcatcherops/prompts/dental_receptionist.md \
        --voice-id "11labs-Adrian"

    python3 -m autonomy.tools.ai_receptionist \
        --action list_agents

    python3 -m autonomy.tools.ai_receptionist \
        --action buy_number \
        --agent-id <agent_id> \
        --area-code 954

Requires: RETELL_API_KEY in env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import requests

@dataclass
class RetellConfig:
    api_key: str
    base_url: str = "https://api.retellai.com"

class RetellClient:
    def __init__(self, config: RetellConfig):
        self.config = config
        self.headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }

    def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.config.base_url}{endpoint}"
        try:
            # Note: requests uses system CA bundle and secure TLS defaults by default.
            resp = requests.post(url, headers=self.headers, json=data)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"Error calling {endpoint}: {e}")
            if e.response is not None:
                print(f"Response: {e.response.text}")
            sys.exit(1)

    def _get(self, endpoint: str) -> Dict[str, Any]:
        url = f"{self.config.base_url}{endpoint}"
        try:
            resp = requests.get(url, headers=self.headers)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            print(f"Error calling {endpoint}: {e}")
            if e.response is not None:
                print(f"Response: {e.response.text}")
            sys.exit(1)

    def create_retell_llm(self, name: str, prompt: str, model: str = "gpt-4o") -> str:
        """Create a Retell LLM configuration."""
        data = {
            "general_prompt": prompt,
            "general_tools": [],
            "states": [
                {
                    "name": "start",
                    "state_prompt": "You are a helpful receptionist. Follow the general prompt for detailed instructions.",
                    "edges": [],
                    "tools": []
                }
            ],
            "starting_state": "start",
            "begin_message": "Hi, thanks for calling Bright Smile Dental. This is Sarah. How can I help you?",
            "model": model,
        }
        resp = self._post("/create-retell-llm", data)
        return resp["llm_id"]

    def create_agent(self, name: str, llm_id: str, voice_id: str) -> Dict[str, Any]:
        """Create a new agent in Retell linked to an LLM."""
        data = {
            "agent_name": name,
            "voice_id": voice_id,
            "response_engine": {
                "llm_id": llm_id,
                "type": "retell-llm"
            }
        }
        resp = self._post("/create-agent", data)
        return resp

    def list_agents(self) -> list[Dict[str, Any]]:
        """List existing agents."""
        resp = self._get("/list-agents")
        return resp

    def buy_phone_number(self, agent_id: str, area_code: int = 954) -> Dict[str, Any]:
        """Buy a phone number and bind to an agent."""
        data = {
            "agent_id": agent_id,
            "area_code": area_code,
        }
        resp = self._post("/create-phone-number", data)
        return resp

    def register_phone_number(self, agent_id: str, phone_number: str) -> Dict[str, Any]:
        """Register an existing Twilio phone number and bind to an agent."""
        data = {
            "agent_id": agent_id,
            "phone_number": phone_number,
        }
        resp = self._post("/create-phone-number", data)
        return resp

def load_prompt(file_path: str) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {file_path}")
    return path.read_text(encoding="utf-8")

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Manage Retell AI Receptionist Agents")
    p.add_argument("--action", required=True, choices=["create_agent", "list_agents", "buy_number", "register_phone"], help="Action to perform")
    p.add_argument("--name", help="Name of the agent (for create_agent)")
    p.add_argument("--prompt-file", help="Path to prompt markdown file (for create_agent)")
    p.add_argument("--voice-id", default="11labs-Adrian", help="Voice ID (default: 11labs-Adrian)")
    p.add_argument("--agent-id", help="Agent ID (for buy_number/register_phone)")
    p.add_argument("--phone-number", help="Phone number (for register_phone)")
    p.add_argument("--area-code", type=int, default=954, help="Area code for phone number (for buy_number)")
    return p.parse_args()

def main() -> None:
    api_key = os.environ.get("RETELL_API_KEY")
    if not api_key:
        print("Error: RETELL_API_KEY environment variable not set.")
        sys.exit(1)

    config = RetellConfig(api_key=api_key)
    client = RetellClient(config)
    args = parse_args()

    if args.action == "create_agent":
        if not args.name or not args.prompt_file:
            print("Error: --name and --prompt-file are required for create_agent")
            sys.exit(1)

        print(f"Loading prompt from {args.prompt_file}...")
        prompt_text = load_prompt(args.prompt_file)

        print(f"Creating LLM for '{args.name}'...")
        try:
             llm_id = client.create_retell_llm(args.name, prompt_text)
             print(f"LLM created: {llm_id}")
        except Exception as e:
            print(f"Failed to create LLM: {e}")
            sys.exit(1)

        print(f"Creating Agent '{args.name}' with voice '{args.voice_id}'...")
        agent = client.create_agent(args.name, llm_id, args.voice_id)
        print("Agent created successfully!")
        print(json.dumps(agent, indent=2))

        print("\nNext step: Register your Twilio number for this agent using:")
        print(f"  python3 -m autonomy.tools.ai_receptionist --action register_phone --agent-id {agent['agent_id']} --phone-number <your_twilio_number>")

    elif args.action == "list_agents":
        agents = client.list_agents()
        print(json.dumps(agents, indent=2))

    elif args.action == "buy_number":
        if not args.agent_id:
             print("Error: --agent-id is required for buy_number")
             sys.exit(1)

        print(f"Buying number in area code {args.area_code} for agent {args.agent_id}...")
        number = client.buy_phone_number(args.agent_id, args.area_code)
        print("Phone number purchased successfully!")
        print(json.dumps(number, indent=2))

    elif args.action == "register_phone":
        if not args.agent_id or not args.phone_number:
             print("Error: --agent-id and --phone-number are required for register_phone")
             sys.exit(1)

        print(f"Registering number {args.phone_number} for agent {args.agent_id}...")
        number = client.register_phone_number(args.agent_id, args.phone_number)
        print("Phone number registered successfully!")
        print(json.dumps(number, indent=2))

if __name__ == "__main__":
    main()
