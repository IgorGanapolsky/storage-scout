#!/usr/bin/env python3
"""
Install a LaunchAgent that runs the live job on a fixed interval (war room mode).

This is intended for a phone-first sprint:
- Run frequently (default: every 30 minutes) to sync inbox + react to inbound interest
- Does NOT enable paid Twilio actions by default (AUTO_CALLS_ENABLED/AUTO_SMS_ENABLED remain opt-in in dotenv)

Usage:
  python autonomy/tools/install_launchd_war_room.py
  python autonomy/tools/install_launchd_war_room.py --interval-secs 1800
  python autonomy/tools/install_launchd_war_room.py --dotenv \".env,.env.war_room\"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.callcatcherops.autonomy.war_room"


def _plist_content(*, python_exe: str, repo_root: Path, interval_secs: int, dotenv_arg: str, config_rel: str) -> str:
    job_script = repo_root / "autonomy" / "tools" / "live_job.py"
    out_log = repo_root / "autonomy" / "state" / "launchd_war_room.out.log"
    err_log = repo_root / "autonomy" / "state" / "launchd_war_room.err.log"

    config_path = (repo_root / config_rel).resolve()
    if not config_path.exists() and config_rel == "autonomy/state/config.callcatcherops.live.json":
        fallback = (repo_root / "autonomy" / "config.callcatcherops.json").resolve()
        if fallback.exists():
            config_path = fallback

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{LABEL}</string>

  <key>WorkingDirectory</key>
  <string>{repo_root}</string>

  <key>ProgramArguments</key>
  <array>
    <string>{python_exe}</string>
    <string>{job_script}</string>
    <string>--config</string>
    <string>{config_path}</string>
    <string>--dotenv</string>
    <string>{dotenv_arg}</string>
    <string>--scoreboard-days</string>
    <string>30</string>
  </array>

  <key>StartInterval</key>
  <integer>{int(interval_secs)}</integer>

  <key>StandardOutPath</key>
  <string>{out_log}</string>
  <key>StandardErrorPath</key>
  <string>{err_log}</string>
</dict>
</plist>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Install LaunchAgent for CallCatcher Ops war room loop.")
    parser.add_argument("--interval-secs", type=int, default=1800, help="Run interval in seconds (default: 1800).")
    parser.add_argument(
        "--dotenv",
        default=".env,.env.war_room",
        help="Comma-separated dotenv paths to load (later wins).",
    )
    parser.add_argument(
        "--config",
        default="autonomy/state/config.callcatcherops.live.json",
        help="Config path (falls back to tracked autonomy/config.callcatcherops.json if missing).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    python_exe = sys.executable

    # Ensure state dir exists for logs/state.
    (repo_root / "autonomy" / "state").mkdir(parents=True, exist_ok=True)

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(
        _plist_content(
            python_exe=python_exe,
            repo_root=repo_root,
            interval_secs=max(300, int(args.interval_secs)),
            dotenv_arg=str(args.dotenv),
            config_rel=str(args.config),
        ),
        encoding="utf-8",
    )

    uid = os.getuid()
    domain = f"gui/{uid}"

    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True, text=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=False, capture_output=True, text=True)

    print(f"Installed and loaded LaunchAgent: {LABEL}")
    print(f"Interval secs: {max(300, int(args.interval_secs))}")
    print(f"Plist: {plist_path}")


if __name__ == "__main__":
    main()

