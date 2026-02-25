#!/usr/bin/env python3
import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path

# Support running as a script (launchd uses absolute paths).
if __package__ is None:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autonomy.engine import load_config
from autonomy.tools.fastmail_inbox_sync import load_dotenv
from autonomy.orchestrator import OrchestrationState, run_state_machine
from autonomy.orchestrator_nodes import (
    IngestionNode,
    HygieneNode,
    AuditNode,
    OutreachNode,
    ReportingNode,
    ReflectionNode,
)

log = logging.getLogger(__name__)

def main() -> None:
    parser = argparse.ArgumentParser(description="CallCatcher Ops - Agentic Orchestrator")
    parser.add_argument("--config", default="autonomy/state/config.callcatcherops.live.json")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    
    # Resolve config with fallback to tracked version
    requested = (repo_root / args.config).resolve()
    if not requested.exists():
        requested = (repo_root / "autonomy" / "config.callcatcherops.json").resolve()
    
    cfg = load_config(requested)
    env = load_dotenv(repo_root / args.env_file)
    
    sqlite_raw = Path(cfg.storage["sqlite_path"])
    audit_raw = Path(cfg.storage["audit_log"])
    sqlite_path = sqlite_raw if sqlite_raw.is_absolute() else (repo_root / sqlite_raw).resolve()
    audit_log = audit_raw if audit_raw.is_absolute() else (repo_root / audit_raw).resolve()

    # 1. Initialize State
    state = OrchestrationState(
        session_id=hashlib.sha256(str(time.time()).encode()).hexdigest()[:8],
        repo_root=repo_root,
        config=cfg,
        env=env,
        sqlite_path=sqlite_path,
        audit_log_path=audit_log,
    )

    # 2. Run Pipeline (Ozkary Agentic Pattern)
    pipeline = [
        IngestionNode,
        HygieneNode,
        AuditNode,
        OutreachNode,
        ReflectionNode,
        ReportingNode,
    ]

    final_state = run_state_machine(state, pipeline)

    # 3. Final Summary
    print(f"Orchestration session {final_state.session_id} completed.")
    print(f"Leads generated: {final_state.leads_generated}")
    print(f"Leads cleaned: {final_state.leads_cleaned}")
    print(f"Calls attempted: {final_state.calls_attempted}")
    print(f"SMS sent: {final_state.sms_sent}")
    if final_state.errors:
        print(f"Errors encountered: {len(final_state.errors)}")
        for err in final_state.errors:
            print(f" - {err}")

if __name__ == "__main__":
    main()
