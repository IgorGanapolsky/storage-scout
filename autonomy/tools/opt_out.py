#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

# Support running as a script: `python3 autonomy/tools/opt_out.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from autonomy.context_store import ContextStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Record an outreach opt-out email (CAN-SPAM).")
    parser.add_argument("--email", required=True, help="Email address to opt out.")
    parser.add_argument("--sqlite", default="autonomy/state/autonomy.sqlite3", help="Path to autonomy sqlite DB.")
    parser.add_argument("--audit", default="autonomy/state/audit.jsonl", help="Path to autonomy audit log.")
    args = parser.parse_args()

    store = ContextStore(sqlite_path=args.sqlite, audit_log=args.audit)
    store.add_opt_out(args.email)
    print({"opted_out": args.email.strip().lower()})


if __name__ == "__main__":
    main()
