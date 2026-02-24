#!/usr/bin/env python3
import os
import subprocess
import sys
from pathlib import Path

LABEL = "com.callcatcherops.autonomy.tollfree_watchdog"


def _plist_content(*, python_exe: str, repo_root: Path) -> str:
    job_script = repo_root / "autonomy" / "tools" / "twilio_tollfree_watchdog.py"
    out_log = repo_root / "autonomy" / "state" / "launchd_tollfree_watchdog.out.log"
    err_log = repo_root / "autonomy" / "state" / "launchd_tollfree_watchdog.err.log"

    # Poll hourly. This keeps review/rejection handling autonomous and near-real-time.
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
    <string>--dotenv</string>
    <string>.env</string>
    <string>--sqlite-path</string>
    <string>autonomy/state/autonomy_live.sqlite3</string>
    <string>--audit-log</string>
    <string>autonomy/state/autonomy_live.jsonl</string>
    <string>--state-path</string>
    <string>autonomy/state/twilio_tollfree_watchdog_state.json</string>
    <string>--company-name</string>
    <string>CallCatcher Ops</string>
  </array>

  <key>StartInterval</key>
  <integer>3600</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>{out_log}</string>
  <key>StandardErrorPath</key>
  <string>{err_log}</string>
</dict>
</plist>
"""


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    python_exe = sys.executable

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(_plist_content(python_exe=python_exe, repo_root=repo_root), encoding="utf-8")

    uid = os.getuid()
    domain = f"gui/{uid}"

    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True, text=True)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=True)
    subprocess.run(["launchctl", "enable", f"{domain}/{LABEL}"], check=False, capture_output=True, text=True)
    subprocess.run(["launchctl", "kickstart", "-k", f"{domain}/{LABEL}"], check=False, capture_output=True, text=True)

    print(f"Installed and loaded LaunchAgent: {LABEL}")
    print(f"Plist: {plist_path}")


if __name__ == "__main__":
    main()

